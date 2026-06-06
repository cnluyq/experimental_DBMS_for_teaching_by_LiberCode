# 实验1：缓冲区池性能分析

## 一、实验目标

通过本实验，你将：

1. ✅ **理解LRU算法**：掌握缓冲区池LRU置换算法的工作原理
2. ✅ **性能测量**：学会设计和运行基准测试，测量缓存命中率
3. ✅ **参数影响分析**：分析缓冲区帧数、页面访问模式对性能的影响
4. ✅ **算法对比**：实现并对比不同的置换策略

## 二、实验环境

- **语言**：Python 3.8+
- **依赖**：无（仅使用标准库和项目代码）
- **前置条件**：已完成项目克隆和依赖安装

## 三、背景知识

### 3.1 什么是缓冲区池？

数据库将数据存储在磁盘上，但磁盘I/O速度远慢于内存。缓冲区池在内存中缓存常用数据页，减少磁盘访问。

**关键指标**：
- **命中率（Hit Rate）**：访问的页面在缓存中的比例
- **命中延迟**：缓存命中的访问时间（通常在纳秒级）
- **未命中延迟**：需要从磁盘读取的时间（通常在毫秒级）

### 3.2 LRU算法

LRU（Least Recently Used）基于**局部性原理**：最近被访问的页面很可能再次被访问。

**实现**：
- 维护一个按访问时间排序的链表
- 访问页面时移到链表头部
- 需要置换时选择链表尾部的页面

### 3.3 性能影响因素

1. **缓存大小**：帧数越多，命中率越高（但有 diminishing returns）
2. **访问模式**：
   - **顺序访问**：如果缓存足够大，可以全部命中
   - **随机访问**：命中率取决于缓存大小 vs 数据量
   - **Zipf分布**：热点数据集中在少数页面，高命中率
3. **置换算法**：LRU、FIFO、Clock、LFU等各有优劣

## 四、实验内容

### 任务1：理解现有实现

阅读 `src/core/buffer.py` 中的 `BufferPool` 类，重点关注：

- `read_page()` 方法：缓存命中和未命中的处理
- `_find_victim_frame()` 方法：LRU置换逻辑
- `get_buffer_stats()` 方法：统计收集
- `lru_list` 的维护：如何更新访问顺序

**问题**：画出LRU链表在以下几种操作后的状态变化：
1. 初始：空
2. 读入页面0,1,2
3. 再次读页面0（命中）
4. 读页面3（置换）

### 任务2：基准测试程序

创建文件 `experiments/exp1_buffer_benchmark.py`：

```python
#!/usr/bin/env python3
"""
实验1：缓冲区池性能分析
"""

import random
from src.core.buffer import BufferPool
from src.core.storage_interface import InMemoryStorage

def test_lru_algorithm():
    """测试LRU基本行为"""
    print("="*60)
    print("任务1：LRU算法行为验证")
    print("="*60)

    storage = InMemoryStorage(page_size=4096)
    buffer = BufferPool(num_frames=3, storage_engine=storage)

    # 初始化10个页面
    for i in range(10):
        data = f"Page {i}".encode().ljust(4096, b'\x00')
        storage.page_write(i, data)

    print("步骤1: 顺序读入页面 0,1,2（应填满缓冲区）")
    for i in range(3):
        frame = buffer.read_page(i, pin=False)
        print(f"  读页面 {i} -> Frame {frame.frame_id}")
        if i == 2:
            print(f"  当前LRU顺序（头→尾）: {buffer.lru_list}")

    print("\n步骤2: 再次读页面0（应命中）")
    frame = buffer.read_page(0, pin=False)
    print(f"  读页面 0 -> Frame {frame.frame_id}")
    print(f"  LRU顺序更新: {buffer.lru_list}")

    print("\n步骤3: 读页面3（应置换最久未使用的页面1）")
    frame = buffer.read_page(3, pin=False)
    print(f"  读页面 3 -> Frame {frame.frame_id}")
    print(f"  LRU顺序: {buffer.lru_list}")

    # 验证页面1被置换
    frame1_info = buffer.get_frame_info(1)
    print(f"\n验证: 页面1的缓冲区信息: {frame1_info}")
    assert frame1_info is None, "页面1应该已被置换出缓冲区"

    print("\n✅ LRU行为验证通过！\n")
    buffer.shutdown()


def measure_hit_rate_workload(workload, num_frames):
    """测量给定工作负载下的命中率"""
    storage = InMemoryStorage(page_size=4096)
    buffer = BufferPool(num_frames=num_frames, storage_engine=storage)

    # 准备数据（假设50个不同页面）
    num_pages = 50
    for i in range(num_pages):
        data = f"Data-{i}".encode().ljust(4096, b'\x00')
        storage.page_write(i, data)

    # 执行工作负载
    for page_id in workload:
        buffer.read_page(page_id, pin=False)

    stats = buffer.get_buffer_stats()
    buffer.shutdown()
    return stats['hit_rate']


def test_different_workloads():
    """测试不同访问模式对命中率的影响"""
    print("="*60)
    print("任务2：不同工作负载的命中率分析（缓冲区=10帧）")
    print("="*60)

    random.seed(42)

    workloads = {
        "顺序访问": list(range(50)),  # 访问50个不同页面一次
        "循环顺序": [i % 10 for i in range(100)],  # 循环访问10个页面
        "热点访问": [0]*70 + [i for i in range(1, 31)],  # 70%访问页面0，30%其他
        "随机访问": [random.randint(0, 49) for _ in range(100)],  # 50页中随机
        "Zipf分布": generate_zipf_workload(100, theta=1.0, num_pages=50),
    }

    for name, wl in workloads.items():
        hit_rate = measure_hit_rate_workload(wl, num_frames=10)
        print(f"  {name:15s} 命中率: {hit_rate:6.2%}")

    print()


def test_buffer_size_impact():
    """测试缓冲区大小对命中率的影响"""
    print("="*60)
    print("任务3：缓冲区大小对命中率的影响（随机工作负载）")
    print("="*60)

    random.seed(42)
    workload = [random.randint(0, 49) for _ in range(1000)]

    print(f"工作负载: 1000次随机访问（50个不同页面）\n")

    for frames in [5, 10, 20, 50, 100]:
        hit_rate = measure_hit_rate_workload(workload, frames)
        print(f"  帧数={frames:3d} → 命中率: {hit_rate:6.2%}")

    print("\n📊 分析：随着缓冲区增大，命中率如何变化？")
    print("   在高冲突工作负载（50页1000次随机）下，需要多大缓存才能达到90%命中率？\n")


def generate_zipf_workload(n, theta=1.0, num_pages=50):
    """生成Zipf分布的工作负载"""
    # 简化版Zipf：第i个页面的概率正比于 1/(i+1)^theta
    ranks = range(1, num_pages + 1)
    weights = [1.0 / (r ** theta) for r in ranks]
    total = sum(weights)
    probabilities = [w / total for w in weights]

    workload = []
    for _ in range(n):
        # 轮盘赌选择
        r = random.random()
        cumsum = 0
        for page_id, p in enumerate(probabilities):
            cumsum += p
            if r < cumsum:
                workload.append(page_id)
                break
    return workload


def test_varying_reference_patterns():
    """测试局部性对命中率的影响"""
    print("="*60)
    print("任务4：访问局部性分析（固定10帧缓冲区）")
    print("="*60)

    random.seed(42)

    # 模式1：完全随机（无局部性）
    wl1 = [random.randint(0, 99) for _ in range(500)]

    # 模式2：高局部性（循环访问10个页面）
    wl2 = [i % 10 for i in range(500)]

    # 模式3：中等局部性（20页中循环）
    wl3 = [i % 20 for i in range(500)]

    hit1 = measure_hit_rate_workload(wl1, 10)
    hit2 = measure_hit_rate_workload(wl2, 10)
    hit3 = measure_hit_rate_workload(wl3, 10)

    print(f"  完全随机(100页)    : {hit1:6.2%}")
    print(f"  高局部性(10页循环) : {hit2:6.2%}")
    print(f"  中等局部性(20页循环): {hit3:6.2%}")

    print("\n💡 结论：程序的访问局部性对缓存命中率有巨大影响！")
    print("   工程优化方向：\n")
    print("   1. 数据结构设计提高局部性（如数组连续存储）")
    print("   2. 预取（Prefetching）：预测未来访问提前加载")
    print("   3. 缓存友好算法：减少跨页访问\n")


def experiment_different_algorithms():
    """（选做）实现其他置换算法并对比"""
    print("="*60)
    print("任务5：置换算法对比（LRU vs FIFO vs Clock）")
    print("="*60)
    print("⚠️  此任务需要先扩展BufferPool类，添加新算法\n")

    # TODO: 扩展BufferPool，添加algorithm参数：
    #   buffer = BufferPool(num_frames, storage, algorithm='lru'|'fifo'|'clock')
    #
    # 实现建议：
    # - FIFO：维护一个FIFO队列（可用list模拟）
    # - Clock：维护环形链表+reference位
    #
    # 然后运行相同的测试，比较命中率

    print("  [待实现] 请在BufferPool中添加以下算法：")
    print("    • FIFO：先进先出")
    print("    • Clock：时钟算法（二次机会）")
    print("\n  实现后，用相同工作负载测试，绘制对比图表。\n")


def main():
    print("\n" + "="*60)
    print(" 实验1：缓冲区池性能分析")
    print("="*60 + "\n")

    # 任务1：验证LRU行为
    test_lru_algorithm()

    # 任务2：不同工作负载
    test_different_workloads()

    # 任务3：缓冲区大小影响
    test_buffer_size_impact()

    # 任务4：访问局部性
    test_varying_reference_patterns()

    # 任务5：算法对比（选做）
    experiment_different_algorithms()

    print("="*60)
    print("实验完成！请整理数据并撰写实验报告。")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
```

运行基准测试：
```bash
cd projo
python experiments/exp1_buffer_benchmark.py
```

### 任务3：数据收集与分析

记录以下数据并绘制图表：

#### 图表1：缓冲区大小 vs 命中率
```
帧数 | 命中率（随机） | 命中率（循环）
-----|---------------|---------------
  5  |               |
 10  |               |
 20  |               |
 50  |               |
100  |               |
```

**问题**：
- 命中率增长何时趋于平缓？为什么？
- 要获得90%命中率需要多少帧？

#### 图表2：不同工作负载的命中率（固定10帧）
```
工作负载类型 | 命中率
------------|--------
顺序访问     |
循环顺序     |
热点访问     |
随机访问     |
Zipf(θ=1)   |
```

**分析**：
- 哪种工作负载命中率最高？为什么？
- Zipf分布的参数θ如何影响命中率？（尝试θ=0.5, 1.0, 2.0）

### 任务4：深入实验（选做）

#### 4.1 实现Clock算法

在 `BufferPool.__init__` 中添加 `algorithm` 参数：

```python
def __init__(self, num_frames, storage_engine, algorithm='lru', logger=None):
    self.algorithm = algorithm
    if algorithm == 'clock':
        self.clock_hand = 0  # 时钟指针
        # 为每个帧维护reference位
```

实现Clock置换（二次机会算法）：
```python
def _find_victim_frame_clock(self):
    while True:
        frame = self.frames[self.clock_hand]
        if not frame.is_pinned():
            if frame.reference_bit == 0:
                return frame  # 找到牺牲帧
            else:
                frame.reference_bit = 0  # 给第二次机会
        self.clock_hand = (self.clock_hand + 1) % self.num_frames
```

**对比**：相同工作负载下，Clock和LRU的命中率差异多少？

#### 4.2 实现预热（Warm-up）

在`read_page()`中，检测顺序访问模式并预取：
```python
# 如果连续访问同一区域的页面，预读下一批
if self.last_page_id and page_id == self.last_page_id + 1:
    for offset in range(1, 4):  # 预取3页
        next_pid = page_id + offset
        if next_pid not in self.page_to_frame:
            self._prefetch_page(next_pid)
```

测量预取对顺序扫描性能的提升。

## 五、实验要求

### 必做部分（60分）

1. ✅ 阅读并理解`BufferPool`的LRU实现（10分）
2. ✅ 完成基准测试程序（20分）
3. ✅ 运行测试并记录数据（15分）
4. ✅ 撰写实验报告（15分）

### 选做部分（40分）

5. 🔄 实现Clock置换算法（15分）
6. 🔄 实现预热预取（10分）
7. 🔄 测试并画出性能对比图表（10分）
8. 🔄 分析不同算法的适用场景（5分）

## 六、实验报告

报告应包含：

### 1. 实验概述
- 简单总结LRU算法原理
- 说明实验目的

### 2. 关键代码
- `BufferPool`类中LRU逻辑的核心代码片段
- 基准测试程序的结构说明

### 3. 实验数据
- 完整的测试结果表格
- 至少2张图表（缓冲区大小影响、工作负载对比）

### 4. 数据分析
- 命中率变化的解释
- 为什么不同工作负载差异这么大？
- 从实验中学到了什么？

### 5. 问题与解决
- 遇到的困难和解决方法
- 代码中的bug和修复过程

### 6. 总结与收获
- 理解缓冲区池的重要性
- LRU算法的优缺点
- 对未来DBMS学习的启示

### 7. 可选：扩展部分
- Clock算法实现思路
- 性能对比结果
- 优化建议

## 七、验收标准

提交以下内容给助教：

1. **代码文件**：`experiments/exp1_buffer_benchmark.py`
2. **实验报告**：`docs/tutorials/exp1_你的名字.md`
3. **运行输出**：在报告中包含测试程序的输出截图

## 八、思考题

1. LRU在实际实现中可能有哪些性能问题？（提示：链表操作）
2. 近似LRU（如Clock）在什么情况下可能比精确LRU更好？
3. 除了命中率，缓冲区池还需要关注哪些指标？

## 九、参考资料

- **教材**：《数据库系统实现》第8章
- **SQLite源码**：`src/pcache.c`（缓冲区池实现）
- **Linux内核**：`mm/vmscan.c`（LRU页面置换）
- **Wikipedia**：[Page replacement algorithms](https://en.wikipedia.org/wiki/Page_replacement_algorithm)

---

**祝实验顺利！** 🚀

有问题？查看`docs/modules/buffer_pool.md`或提问。