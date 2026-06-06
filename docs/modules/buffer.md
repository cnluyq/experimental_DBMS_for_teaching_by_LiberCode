# LRU缓冲区池模块详解

## 目录
- [概述](#概述)
- [架构设计](#架构设计)
- [核心算法](#核心算法)
  - [LRU置换](#lru置换)
  - [钉住机制](#钉住机制)
  - [脏页写回](#脏页写回)
- [类详解](#类详解)
  - [BufferPool](#bufferpool)
  - [BufferFrame](#bufferframe)
- [性能统计](#性能统计)
- [线程安全](#线程安全)
- [使用模式](#使用模式)
- [实验项目](#实验项目)
- [常见问题](#常见问题)

---

## 概述

缓冲区池（Buffer Pool）是数据库性能的关键组件，它在内存中缓存热点数据页，减少昂贵的磁盘I/O。ProjoDB实现了经典的**LRU（最近最少使用）**置换算法，配合**钉住（Pin）**机制防止重要页面被驱逐。

### 为什么需要缓冲区池？

1. **性能**：内存访问速度比磁盘快10^5倍，缓存命中可大幅提升性能
2. **减少I/O**：合并多次小写为一次大写（缓冲写）
3. **并发控制**：统一管理页面访问，避免并发读写冲突
4. **预取**：预测访问模式，提前加载页面

### 核心参数

- **帧数（num_frames）**：内存中可同时缓存的页面数
- **页大小（page_size）**：通常4KB，由存储引擎决定
- **置换算法**：LRU、FIFO、Clock、LFU等
- **写策略**：延迟写（deferred write） vs 立即写（write-through）

---

## 架构设计

```
BufferPool（管理器）
├── 帧数组：BufferFrame[num_frames]
│   ├── frame_id: 0, 1, 2, ...
│   ├── page_id: 对应的页面ID（None表示空闲）
│   ├── data: 页面数据（bytearray，4KB）
│   ├── dirty: 是否脏（被修改过）
│   ├── pin_count: 钉住计数
│   └── access_time: 访问时间戳
│
├── LRU链表：frame_id列表（最新访问在头部）
│   ⇥ [帧5] ← [帧2] ← [帧7] ⇥  // 5最近使用，7最久未用
│
├── 页面映射：page_id → frame_id
│   { 100 → 3, 101 → 5, 102 → 1, ... }
│
└── 存储引擎：底层I/O接口
    StorageEngine.page_read(id)
    StorageEngine.page_write(id, data)
```

**核心数据结构**：
- `frames: Dict[int, BufferFrame]`：帧数组
- `lru_list: List[int]`：LRU列表（frame_id）
- `page_to_frame: Dict[int, int]`：页面到帧的映射

---

## 核心算法

### LRU置换

**目标**：当需要新页面但缓冲区已满时，选择一个**最久未使用**的帧淘汰。

**实现**：
```python
def _find_victim_frame(self) -> Optional[BufferFrame]:
    """寻找牺牲帧"""
    for frame_id in self.lru_list:  # 从尾部开始（最旧）
        frame = self.frames[frame_id]
        if not frame.is_pinned():
            return frame
    return None  # 所有帧都被钉住，无法替换
```

**LRU更新**：
每次页面访问（`read_page`命中）后：
```python
def _update_access(self, frame_id: int):
    """更新LRU顺序：将frame移到链表头部"""
    if frame_id in self.lru_list:
        self.lru_list.remove(frame_id)
    self.lru_list.insert(0, frame_id)  # 头部是最新
```

**复杂度**：`remove()`是O(n)，可以用`collections.deque`或双向链表优化。

---

### 钉住机制（Pin/Unpin）

**目的**：防止重要页面（如正在处理的页面）被意外置换。

**规则**：
- 只有`pin_count == 0`的帧才能被替换
- `pin()`：计数+1，表示"我正在使用这个页"
- `unpin()`：计数-1，表示"我用完了"

**使用模式**：
```python
frame = buffer.read_page(page_id, pin=True)  # 自动pin
try:
    process(frame.data)
finally:
    buffer.unpin_page(page_id)  # 必须显式unpin
```

**常见错误**：
- 忘记unpin → 内存泄漏（帧永远无法释放）
- 提前unpin → 页面可能被替换，继续访问会得到错误数据

---

### 脏页写回

**何时写回**：
1. **置换时**：牺牲帧是脏页 → 先写回磁盘
2. **显式刷新**：`flush_page()`、`flush_all()`
3. **关闭时**：`shutdown()`自动`flush_all()`

**算法**：
```python
def _evict_page(self, frame: BufferFrame) -> bool:
    """驱逐一个帧（需要先写回脏页）"""
    if frame.dirty:
        if not self._write_page_to_disk(frame):
            return False
        self.stats['writes_disk'] += 1
        frame.dirty = False

    # 清理帧状态
    frame.page_id = None
    frame.data = None
    return True
```

**写回策略**：
- **延迟写（deferred）**：脏页在置换或检查点时写回（默认）
- **立即写（through）**：每次修改后立即写回（低性能，保证强持久性）

---

## 类详解

### BufferPool

主管理器类，提供页面访问接口。

#### 构造

```python
BufferPool(
    num_frames: int,              # 缓冲区帧数（内存大小）
    storage_engine,               # StorageEngine实例
    logger=None,                  # 日志器（可选）
    algorithm='lru'               # 置换算法：'lru', 'fifo', 'clock'
)
```

#### 页面操作

```python
def read_page(page_id: int, pin: bool = True) -> Optional[BufferFrame]:
    """
    读取页面到缓冲区（缓存）

    Args:
        page_id: 页面ID
        pin: 是否自动钉住（推荐True）

    Returns:
        BufferFrame对象（含页面数据）
        或None（页面不存在或错误）

    流程：
    1. 查找page_id是否已在缓冲区（page_to_frame）
       → 命中：更新LRU，返回帧
       → 未命中：继续
    2. 寻找空闲帧或牺牲帧
    3. 从存储引擎读取页面数据
    4. 加载到帧，更新映射和LRU
    """
```

```python
def create_page(page_id: int, data: bytes, pin: bool = True) -> Optional[BufferFrame]:
    """创建新页面（分配或初始化）"""
```

```python
def mark_dirty(page_id: int) -> bool:
    """标记页面为脏（修改后调用）"""
    frame_id = self.page_to_frame.get(page_id)
    if frame_id is None:
        return False
    frame = self.frames[frame_id]
    frame.dirty = True
    return True
```

```python
def unpin_page(page_id: int) -> bool:
    """解除钉住（使用完毕后必须调用）"""
    frame_id = self.page_to_frame.get(page_id)
    if frame_id is None:
        return False
    frame = self.frames[frame_id]
    frame.unpin()
    return True
```

```python
def flush_page(page_id: int) -> bool:
    """强制写回单个页面到磁盘"""
    frame_id = self.page_to_frame.get(page_id)
    if frame_id is None:
        return False
    frame = self.frames[frame_id]
    if not self._write_page_to_disk(frame):
        return False
    frame.dirty = False
    return True
```

```python
def flush_all() -> bool:
    """写回所有脏页"""
    success = True
    for frame in self.frames.values():
        if frame.dirty and frame.page_id is not None:
            if not self._write_page_to_disk(frame):
                success = False
            else:
                frame.dirty = False
    return success
```

#### 查询与统计

```python
def get_frame_info(page_id: int) -> Optional[Dict[str, Any]]:
    """
    获取页面在缓冲区中的信息

    Returns:
        {
            'frame_id': 3,
            'page_id': 100,
            'dirty': True,
            'pin_count': 2,
            'access_time': 123456
        }
    """
```

```python
def get_buffer_stats(self) -> Dict[str, Any]:
    """
    获取缓冲区统计信息

    Returns:
        {
            'num_frames': 100,
            'used_frames': 42,
            'free_frames': 58,
            'reads_total': 1000,
            'hits': 850,
            'misses': 150,
            'hit_rate': 0.85,
            'reads_disk': 150,
            'writes_disk': 75,
            'evictions': 50,
            'evicted_dirty': 30
        }
    """
```

#### 生命周期

```python
def shutdown(self):
    """
    关闭缓冲区池

    1. 检查是否有未unpin的帧（警告）
    2. flush_all()写回所有脏页
    3. 清空状态
    """
```

---

### BufferFrame

单个缓冲区帧，封装页面数据和状态。

#### 属性

```python
class BufferFrame:
    frame_id: int          # 帧ID（0 ~ num_frames-1）
    page_id: Optional[int] # 缓存的页面ID（None表示空闲）
    data: bytearray        # 页面数据（4KB）
    dirty: bool            # 是否脏（True=已修改未写回）
    pin_count: int         # 钉住计数（>0不能替换）
    access_time: int       # 访问时间戳（用于LRU）
```

#### 方法

```python
def is_free(self) -> bool:
    """是否空闲（未缓存任何页面）"""
    return self.page_id is None

def is_pinned(self) -> bool:
    """是否被钉住"""
    return self.pin_count > 0

def pin(self):
    """钉住页面（pin_count++）"""
    self.pin_count += 1

def unpin(self):
    """解除钉住（pin_count--）"""
    if self.pin_count > 0:
        self.pin_count -= 1
    else:
        logger.warning("Unpin a non-pinned frame")

def set_page(self, page_id: int, data: bytes, dirty: bool = False):
    """设置帧内容（替换页面时调用）"""
    self.page_id = page_id
    self.data = bytearray(data)
    self.dirty = dirty
    self.pin_count = 0  # 重置钉住计数
```

---

## 性能统计

缓冲区池自动收集以下指标，用于性能分析和调优：

| 指标 | 说明 | 公式/计算 |
|------|------|-----------|
| `reads_total` | 总访问次数 | 每次`read_page()`递增 |
| `hits` | 命中次数 | page_id在缓冲区中 |
| `misses` | 未命中次数 | page_id不在缓冲区中 |
| `hit_rate` | 命中率 | hits / reads_total |
| `reads_disk` | 磁盘读取次数 | 每次miss时从存储引擎读 |
| `writes_disk` | 磁盘写入次数 | 脏页写回或置换 |
| `evictions` | 置换次数 | 替换牺牲帧 |
| `evicted_dirty` | 置换的脏页数 | 置换时dirty=True |
| `used_frames` | 已用帧数 | page_to_frame的大小 |
| `free_frames` | 空闲帧数 | num_frames - used_frames |

**示例**：
```python
stats = buffer.get_buffer_stats()
print(f"命中率: {stats['hit_rate']:.2%}")
print(f"平均每次访问磁盘I/O: {stats['reads_disk']/stats['reads_total']:.2f}")
```

---

## 线程安全

所有`BufferPool`的公共方法都使用`threading.RLock`保护：

```python
def read_page(self, page_id, pin=True):
    with self.lock:  # 获取锁（线程安全）
        # ... 操作共享数据结构
        return frame
```

**锁粒度**：
- 当前：整个方法一个锁（简单但可能成为瓶颈）
- 可选优化：每帧一个锁，或哈希锁（分片锁）

**死锁预防**：
- 不允许多次获取锁（RLock支持重入）
- 锁内不调用外部代码（避免回调死锁）
- 使用with语句确保异常时释放锁

---

## 使用模式

### 模式1：基本读写

```python
# 初始化
storage = SimpleFileStorage("test.db")
buffer = BufferPool(num_frames=100, storage_engine=storage)

# 读页面
frame = buffer.read_page(page_id=0, pin=True)
data = frame.data
# 修改数据
frame.data[0] = 0xFF
buffer.mark_dirty(page_id=0)

# 使用完毕必须unpin
buffer.unpin_page(page_id=0)

# 关闭
buffer.shutdown()
```

---

### 模式2：批量处理（避免重复pin/unpin）

```python
def batch_process(buffer, page_ids):
    frames = []
    try:
        # 一次性pin所有需要的页
        for pid in page_ids:
            frame = buffer.read_page(pid, pin=True)
            frames.append(frame)

        # 处理所有页面（此时不会被替换）
        for frame in frames:
            process(frame.data)

    finally:
        # 确保释放所有pin
        for frame in frames:
            buffer.unpin_page(frame.page_id)
```

---

### 模式3：预取（Prefetching）

顺序访问时，提前加载下一页：

```python
def sequential_scan(buffer, start_page_id, num_pages):
    for i in range(num_pages):
        page_id = start_page_id + i

        # 预取下一页（异步或提前）
        if i + 1 < num_pages:
            next_id = start_page_id + i + 1
            buffer.read_page(next_id, pin=False)  # 只缓存，不pin主流程

        # 处理当前页
        frame = buffer.read_page(page_id, pin=True)
        try:
            process(frame.data)
        finally:
            buffer.unpin_page(page_id)
```

---

### 模式4：性能测试

```python
def benchmark(buffer, workload):
    """基准测试：测量命中率"""
    for page_id in workload:
        frame = buffer.read_page(page_id, pin=True)
        # 简单操作（读取或修改）
        _ = frame.data[0]
        buffer.unpin_page(page_id)

    stats = buffer.get_buffer_stats()
    return stats['hit_rate']
```

**测试工作负载**：
- **顺序**：0, 1, 2, 3, ...
- **随机**：随机选择页面ID
- **Zipf分布**：少数页面访问频繁（模拟真实热点）

---

## 实验项目

### 实验1：实现不同置换算法

**目标**：扩展`BufferPool`支持FIFO和Clock算法。

**FIFO（先进先出）**：
```python
def _find_victim_frame_fifo(self):
    # 维护一个先进先出队列
    while self.fifo_queue:
        frame_id = self.fifo_queue.pop(0)
        frame = self.frames[frame_id]
        if not frame.is_pinned():
            return frame
    return None
```

**Clock（时钟）**：
```python
class ClockBufferPool(BufferPool):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.clock_hand = 0  # 时钟指针

    def _find_victim_frame_clock(self):
        n = self.num_frames
        for _ in range(n):
            frame = self.frames[self.clock_hand]
            self.clock_hand = (self.clock_hand + 1) % n
            if not frame.is_pinned():
                if not frame.reference_bit:
                    return frame  # 选中
                else:
                    frame.reference_bit = False  # 清除引用位
        return None
```

**任务**：
1. 实现FIFO，与LRU对比命中率（随机工作负载）
2. 实现Clock（二次机会），测试效果
3. 绘制不同帧数下的命中率曲线

---

### 实验2：测量Pin机制的影响

**目标**：理解Pin/Unpin的正确使用和内存泄漏后果。

**步骤**：
1. 创建一个测试：故意不unpin某些页面
2. 观察可用帧数下降，最终缓冲区满导致新页面无法加载
3. 使用`get_buffer_stats()`监控`used_frames`

**实验代码**：
```python
def test_pin_leak(buffer, num_iterations):
    for i in range(num_iterations):
        frame = buffer.read_page(page_id=i % 10, pin=True)
        # 忘了unpin！
        # 预期：前10次后缓冲区满，之后每次miss

    stats = buffer.get_buffer_stats()
    print(f"Used frames: {stats['used_frames']}")
    # 应该为min(num_iterations, num_frames)
```

---

### 实验3：预取优化

**目标**：为顺序访问添加预取，提升命中率。

**步骤**：
1. 修改`read_page()`，检测连续访问模式
2. 如果上次访问的page_id+1被预测，提前加载
3. 测量预取对顺序扫描的性能提升

**思考**：如何平衡预取的收益和额外I/O成本？

---

### 实验4：并发性能

**目标**：测试多线程并发访问缓冲区的性能。

**步骤**：
1. 创建多个线程，共享一个`BufferPool`
2. 线程访问模式：
   - 热点：所有线程访问少量页面（高冲突）
   - 均匀：每个线程访问不同页面（低冲突）
3. 测量吞吐量和锁竞争

```python
import threading

def worker(buffer, pages):
    for pid in pages:
        frame = buffer.read_page(pid)
        buffer.unpin_page(pid)

threads = []
for i in range(10):
    t = threading.Thread(target=worker, args=(buffer, range(100)))
    threads.append(t)
    t.start()
```

---

## 常见问题

### Q1: 如何选择合适的帧数？

**A**: 内存允许的情况下，帧数越多命中率越高（收益递减）。公式：**缓存大小 = 帧数 × 页大小**。建议：
- 教学/测试：100-500帧（0.4MB-2MB）
- 小型应用：1000-10000帧（4MB-40MB）
- 生产环境：数万到数十万帧（取决于内存大小）

使用**命中率-帧数曲线**找到拐点（提升变缓处）。

---

### Q2: 为什么需要Pin机制？不能简单靠LRU保护吗？

**A**:
- **LRU**只决定哪个页面"最可能不被使用"，不保证安全
- **应用场景**：一个事务可能同时访问多个页面（如JOIN），这些页面必须同时保持在内存中，直到操作完成
- **Pin**确保这些页面不会被替换，直到显式unpin
- **示例**：索引扫描时，当前叶子页和下一页同时pin，防止扫描过程中下一页被替换

---

### Q3: 如何检测和避免内存泄漏（未unpin）？

**A**:
1. 计数器监控：`shutdown()`时检查是否有`pin_count > 0`
2. 超时机制：页面pin超过一定时间自动警告
3. 日志记录：每次pin/unpin记录，用于调试
4. RAII封装（推荐）：

```python
class PinnedFrame:
    """上下文管理器：自动unpin"""
    def __init__(self, buffer, page_id):
        self.buffer = buffer
        self.page_id = page_id
        self.frame = None

    def __enter__(self):
        self.frame = self.buffer.read_page(self.page_id, pin=True)
        return self.frame

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.buffer.unpin_page(self.page_id)

# 使用
with PinnedFrame(buffer, page_id) as frame:
    process(frame.data)  # 自动pin/unpin
```

---

### Q4: 脏页写回失败怎么办？

**A**:
- **检测**：`_write_page_to_disk()`返回False
- **策略**：
  1. 重试几次（可能是临时I/O错误）
  2. 记录错误日志
  3. 如果持续失败，抛出异常或停止系统（数据安全优先）
  4. 对于非关键脏页，可以忽略（但数据会丢失）

**生产建议**：
- 使用WAL确保即使数据页丢失也能恢复
- 监控磁盘空间和I/O健康状态
- 定期检查点，减少恢复数据量

---

### Q5: LRU链表频繁remove/insert开销大，如何优化？

**A**:
1. **使用双向链表**：`collections.deque`或自定义`LinkedList`
2. **维护位置索引**：`frame_id → 链表节点指针`，O(1)删除
3. **近似LRU**：Clock算法，O(1)操作
4. **分段LRU**：热区和冷区，减少链表操作

---

## 参考代码

完整实现参考：
- `src/core/buffer.py`：Python实现，约400行
- `src/include/buffer.h`：C++头文件定义（待实现）
- `docs/modules/buffer.md`：本文档

---

**下一步**：学习 [SQL解析器模块](parser.md) 或继续 [实验1：缓冲区性能分析](docs/tutorials/exp1_buffer.md)
