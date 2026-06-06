# LRU缓冲区池管理器

一个用于教学演示的经典LRU缓冲区池实现。

## 功能特性

- ✅ 固定数量的缓冲区帧管理
- ✅ 经典LRU页面置换算法
- ✅ 页面读取和写入接口
- ✅ 脏页管理和写回机制
- ✅ 支持页面钉住（Pin/Unpin）
- ✅ 完整的统计信息收集
- ✅ 线程安全设计
- ✅ 可插拔的存储引擎接口

## 项目结构

```
src/
├── core/
│   ├── buffer.py              # LRU缓冲区管理器核心实现
│   └── storage_interface.py   # 存储引擎接口定义
tests/
└── test_buffer.py             # 单元测试
```

## 快速开始

### 基本用法

```python
from src.core.buffer import BufferPool
from src.core.storage_interface import InMemoryStorage

# 1. 创建存储引擎（可以是InMemoryStorage或SimpleFileStorage）
storage = InMemoryStorage(page_size=4096)

# 2. 创建缓冲区池（指定帧数量）
buffer = BufferPool(num_frames=10, storage_engine=storage)

# 3. 读取页面（自动处理缓存命中/未命中）
frame = buffer.read_page(page_id=0)
if frame:
    # 使用页面数据
    data = frame.data
    
    # 修改页面（标记为脏页）
    buffer.mark_dirty(page_id=0)
    
    # 解除钉住（如果之前Pin了）
    buffer.unpin_page(page_id=0)

# 4. 写回所有脏页并关闭
buffer.flush_all()
buffer.shutdown()
```

### 创建新页面

```python
# 创建新页面
new_page_id = storage.allocate_page()
frame = buffer.create_page(
    page_id=new_page_id,
    data=b"Initial data".ljust(4096, b'\x00'),
    pin=True  # 创建后自动钉住
)
# ... 使用页面 ...
buffer.unpin_page(new_page_id)  # 完成后解除钉住
```

### 获取统计信息

```python
stats = buffer.get_buffer_stats()
print(f"命中率: {stats['hit_rate']:.2%}")
print(f"缓存命中: {stats['hits']}, 未命中: {stats['misses']}")
print(f"磁盘读取: {stats['reads_disk']}, 写回: {stats['writes_disk']}")
print(f"置换次数: {stats['evictions']}, 置换的脏页: {stats['evicted_dirty']}")
```

## 核心类说明

### BufferPool（缓冲区池）

主要方法：
- `read_page(page_id, pin=True)`: 读取页面，自动处理缓存
- `create_page(page_id, data, pin=True)`: 创建新页面
- `mark_dirty(page_id)`: 标记页面为脏
- `unpin_page(page_id)`: 解除页面钉住
- `flush_page(page_id)`: 强制写回指定页面
- `flush_all()`: 写回所有脏页
- `get_buffer_stats()`: 获取统计信息
- `shutdown()`: 关闭缓冲区（自动写回）

### BufferFrame（缓冲区帧）

内部使用的帧类，代表一个缓冲区位置：
- `page_id`: 页面ID（None表示空闲）
- `data`: 页面数据（bytearray）
- `dirty`: 是否脏页
- `pin_count`: 钉住计数
- `access_time`: 访问时间戳（LRU用）

### StorageEngine（存储引擎接口）

需要实现的抽象接口：
- `page_read(page_id)`: 从存储读取页面
- `page_write(page_id, data)`: 写入页面到存储
- `allocate_page()`: 分配新页面ID
- `get_page_size()`: 返回页面大小

## 实现细节

### LRU置换算法

缓冲区使用LRU（最近最少使用）算法：
1. 每次页面访问时更新时间戳
2. 维护一个LRU链表（按访问时间排序）
3. 需要置换时选择链表尾部的帧
4. 脏页在置换前会先写回磁盘

### 脏页管理

- 页面被修改后必须调用 `mark_dirty()` 标记
- 页面在以下情况会写回磁盘：
  - 显式调用 `flush_page()` 或 `flush_all()`
  - 被选为牺牲帧进行置换
  - 调用 `shutdown()` 关闭缓冲区
- 写回失败时不会强制置换

### 线程安全

- 使用 `threading.RLock()` 保护所有共享数据
- 所有公共方法都持有锁
- 支持多线程并发访问

### 页面钉住

- 使用Pin/Unpin机制防止重要页面被置换
- `read_page(pin=True)` 会自动Pin页面
- 必须显式调用 `unpin_page()` 释放钉住
- 钉住的页面不会被选为牺牲帧

## 运行测试

```bash
# 运行所有测试
python -m pytest tests/test_buffer.py -v

# 或使用unittest
python -m unittest tests.test_buffer -v
```

## 教学演示示例

```python
# 演示LRU算法工作原理
from src.core.buffer import BufferPool
from src.core.storage_interface import InMemoryStorage

# 创建小缓冲区（3帧）和大存储（10页面）
storage = InMemoryStorage(4096)
buffer = BufferPool(3, storage)

# 初始化10个页面
for i in range(10):
    data = f"Page {i}".encode().ljust(4096, b'\x00')
    storage.page_write(i, data)

# 1. 顺序读取0,1,2 -> 全部加载到缓冲区
print("加载页面 0,1,2:")
for i in range(3):
    frame = buffer.read_page(i)
    print(f"  Frame {frame.frame_id} <- Page {i}")

# 2. 再次读取0（应该在缓冲区中命中）
print("\n读取页面 0（应该命中）:")
frame = buffer.read_page(0)
print(f"  Hit! Frame {frame.frame_id}")

# 3. 读取页面3（应该置换页面1，因为页面1最久未使用）
print("\n读取页面 3（应该置换页面1）:")
frame = buffer.read_page(3)
print(f"  Page 3 loaded to Frame {frame.frame_id}")

# 4. 查看LRU顺序
print("\n当前LRU顺序（从新到旧）:")
for i, fid in enumerate(buffer.lru_list):
    frame = buffer.frames[fid]
    print(f"  {i}. Frame {fid} (Page {frame.page_id})")
```

## 设计原则

1. **简单清晰**: 代码结构简单，便于理解和修改
2. **教学友好**: 详细注释，清晰的函数名
3. **可扩展**: 使用接口抽象，便于替换存储引擎
4. **实用功能**: 包含统计、线程安全等实用特性
5. **正确性**: 通过完整测试保证正确性

## 待实现功能

- [ ] 支持不同的置换策略（如Clock、LFU）
- [ ] 异步I/O优化
- [ ] 预取（Prefetching）机制
- [ ] 批量操作优化
- [ ] 更详细的性能分析工具

## 许可证

MIT License - 用于教学目的