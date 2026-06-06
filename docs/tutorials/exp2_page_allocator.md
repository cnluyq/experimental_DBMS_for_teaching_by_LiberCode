# 实验2：实现页位图分配器

## 一、实验目标

通过本实验，你将：

1. ✅ **理解页分配问题**：了解为什么需要页分配器及其设计挑战
2. ✅ **实现位图分配器**：从零实现基于位图的页分配算法
3. ✅ **性能优化**：测量位图与未优化方案的性能差异
4. ✅ **扩展能力**：学习添加新分配策略到系统中

## 二、实验环境

- **语言**：C++17 / Python（可选，用于测试）
- **前置知识**：位运算、内存布局
- **前置实验**：[实验1](exp1_buffer_analysis.md)（可选但推荐）

## 三、背景知识

### 3.1 为什么需要页分配器？

在数据库系统中，数据存储在固定大小的**页（page）**中（通常4KB）。存储引擎需要：

- 分配新页（用于数据、索引、日志）
- 删除页并回收空间（DELETE、DROP TABLE）
- 快速查找空闲页

如果没有高效的分配器，会出现：
- **碎片化**：大量不连续的空闲页无法使用
- **性能下降**：分配和查找耗时增加
- **空间浪费**：无法利用已释放的页

### 3.2 常见的页分配策略

#### 方案1：空闲链表（Free List）
- 在页头或外部维护一个链表，指向所有空闲页
- 分配：弹出链表头
- 释放：插入链表头
- **优点**：简单、快速O(1)
- **缺点**：不记录页使用状态，容易产生碎片

#### 方案2：位图（Bitmap）
- 使用一个bit数组，每个bit代表一个页是否空闲
- 分配：扫描位图找到第一个0位
- 释放：将对应bit设为1
- **优点**：紧凑、快速检查、支持O(1)查找（如有硬件指令）
- **缺点**：扫描可能O(n)，大数据库位图本身占用内存

#### 方案3：伙伴系统（Buddy System）
- 页按2的幂次分组，合并相邻空闲块
- **优点**：减少外部碎片，合并快
- **缺点**：内部碎片（可能浪费空间）

#### 方案4：分段/分桶
- 将页分桶（如每1000页为一组），每桶独立管理
- **优点**：平衡查找时间和位图大小
- **缺点**：跨桶分配复杂

### 3.3 位图分配器详解

假设有N个页（N ≤ 2³²），位图需要N个bit（约N/8字节）。

**示例**（16个页）：
```
位图: 1110 1111 0010 1110  (二进制, 从左到右)
      ~~~~           ~~
页0: 1 (已分配)   页8:  0 (空闲)
页1: 1            页9:  1
页2: 1            页10: 1
页3: 0 (空闲)     页11: 1
页4: 1            页12: 1
页5: 1            页13: 1
页6: 1            页14: 0
页7: 1            页15: 1
```

**分配第3页**：找到第一个0（第3位），设为1 → `1110 1111 0010 1110`

**释放第3页**：设为0 → `1110 1111 0010 1110`

**查找第一个空闲**：从左到右扫描字节。

### 3.4 位操作技巧

```cpp
// 假设位图存储在 vector<uint8_t> 中

// 计算byte索引和bit偏移
int page_id = 42;
int byte_idx = page_id / 8;      // 42 / 8 = 5
int bit_idx = page_id % 8;       // 42 % 8 = 2

uint8_t byte = bitmap[byte_idx];

// 测试bit是否为0（空闲）
bool is_free = !(byte & (1 << bit_idx));

// 分配：将bit设为1（已分配）
bitmap[byte_idx] |= (1 << bit_idx);

// 释放：将bit设为0（空闲）
bitmap[byte_idx] &= ~(1 << bit_idx);

// CPU指令：找到第一个为0的bit（GCC内置）
// __builtin_ffs(~byte) - 1  // 返回第一个0的bit位置（0-7）
```

## 四、实验内容

### 任务1：设计位图分配器接口

**目标**：为`PageAllocator`设计清晰的接口。

参考现有`PageAllocator`声明（或从头设计）：

```cpp
// src/include/page_allocator.h
class PageAllocator {
public:
    PageAllocator(FileManager* file_mgr);
    ~PageAllocator();

    void initialize();  // 从文件加载元数据或初始化
    uint32_t allocate(PageType type);  // 分配一页
    void free(uint32_t page_id);       // 释放一页
    std::unique_ptr<Page> get_page(uint32_t page_id);  // 读取页面
    void put_page(Page* page);         // 写回页面

    // 统计
    uint32_t get_total_pages() const;
    uint32_t get_free_count() const;
    uint32_t get_allocated_count() const;

private:
    FileManager* file_mgr_;  // 底层文件管理
    // TODO: 添加位图和其他数据结构
};
```

**问题**：
- `allocate()`应如何处理所有页已满的情况？
- 如何区分不同类型的页（数据、索引、元数据）？
- `get_page()`和`put_page()`如何与`FileManager`交互？

### 任务2：实现位图分配器

创建文件 `src/core/page_allocator_bitmap.cpp` 和头文件：

**步骤1：定义数据结构**

```cpp
// 位图元数据（存储在文件头或单独元数据页）
struct BitmapMetadata {
    uint32_t total_pages;    // 总页数
    uint32_t first_free;     // 第一个空闲页（缓存优化）
    // 位图数据（可选存储在文件中）
    // uint8_t* bitmap;
};

class BitmapPageAllocator : public PageAllocator {
private:
    std::unique_ptr<BitmapMetadata> metadata_;
    std::vector<uint8_t> bitmap_;  // 内存中的位图副本
    uint32_t page_size_;

    // 缓存最近使用的空闲页，加速分配
    std::stack<uint32_t> free_cache_;

    void load_bitmap_from_file();
    void flush_bitmap_to_file();
};
```

**步骤2：实现`initialize()`**

```cpp
void BitmapPageAllocator::initialize() {
    // 1. 检查文件是否已存在
    uint32_t file_pages = file_mgr_->get_file_size();

    if (file_pages == 0) {
        // 新数据库：初始化元数据页 + 初始位图
        metadata_->total_pages = INITIAL_PAGES;  // 如1000页
        allocate_metadata_page();
        bitmap_.resize((metadata_->total_pages + 7) / 8, 0xFF);  // 初始全1（已分配）
        // 标记元数据页为已分配，其余为空闲
        // ...
    } else {
        // 现有数据库：从文件读取位图
        load_bitmap_from_file();
    }

    // 初始化first_free缓存
    metadata_->first_free = find_first_free();
}
```

**步骤3：实现`allocate()`**

```cpp
uint32_t BitmapPageAllocator::allocate(PageType type) {
    std::lock_guard<std::mutex> lock(mutex_);

    // 1. 检查是否有空闲页
    if (metadata_->free_count == 0) {
        // 扩展文件：新增一页
        extend_file();
        // 添加新页到位图
        bitmap_.push_back(0x00);  // 新页为空闲
        metadata_->total_pages++;
    }

    // 2. 从缓存或位图查找空闲页
    uint32_t page_id;
    if (!free_cache_.empty()) {
        page_id = free_cache_.top();
        free_cache_.pop();
    } else {
        page_id = find_first_free();
    }

    // 3. 标记为已分配
    set_bit(page_id, false);  // false = 已分配
    metadata_->allocated_count++;

    // 4. 更新first_free缓存
    if (page_id == metadata_->first_free) {
        metadata_->first_free = find_first_free();
    }

    // 5. 可选：根据type初始化页类型
    auto page = get_page(page_id);
    page->set_type(type);

    // 6. 异步刷位图到文件（或延迟）
    schedule_bitmap_flush();

    return page_id;
}
```

**步骤4：实现`free()`**

```cpp
void BitmapPageAllocator::free(uint32_t page_id) {
    std::lock_guard<std::mutex> lock(mutex_);

    if (page_id >= metadata_->total_pages) {
        throw std::invalid_argument("Invalid page_id");
    }

    // 检查是否已空闲
    if (is_free(page_id)) {
        throw std::runtime_error("Double free detected");
    }

    // 标记为空闲
    set_bit(page_id, true);  // true = 空闲
    metadata_->allocated_count--;

    // 更新缓存
    if (page_id < metadata_->first_free) {
        metadata_->first_free = page_id;
    }
    free_cache_.push(page_id);

    schedule_bitmap_flush();
}
```

**步骤5：辅助函数**

```cpp
bool BitmapPageAllocator::is_free(uint32_t page_id) {
    int byte_idx = page_id / 8;
    int bit_idx = page_id % 8;
    return (bitmap_[byte_idx] & (1 << bit_idx)) != 0;
}

void BitmapPageAllocator::set_bit(uint32_t page_id, bool free) {
    int byte_idx = page_id / 8;
    int bit_idx = page_id % 8;
    if (free) {
        bitmap_[byte_idx] |= (1 << bit_idx);   // 设为1（空闲）
    } else {
        bitmap_[byte_idx] &= ~(1 << bit_idx);  // 设为0（已分配）
    }
}

uint32_t BitmapPageAllocator::find_first_free() {
    for (size_t i = 0; i < bitmap_.size(); i++) {
        if (bitmap_[i] != 0xFF) {  // 不是全1（有空闲位）
            // 找到byte中第一个0位
            uint8_t byte = bitmap_[i];
            for (int bit = 0; bit < 8; bit++) {
                if (!(byte & (1 << bit))) {
                    return i * 8 + bit;
                }
            }
        }
    }
    return INVALID_PAGE_ID;
}
```

### 任务3：测试你的分配器

创建 `tests/test_page_allocator.py`：

```python
import pytest
from src.core.page_allocator_bitmap import BitmapPageAllocator
from src.core.file_manager import FileManager

def test_basic_allocation():
    """测试基本分配和释放"""
    fm = FileManager()
    pa = BitmapPageAllocator(fm)
    pa.initialize()

    # 分配3页
    p1 = pa.allocate(PageType.DATA)
    p2 = pa.allocate(PageType.DATA)
    p3 = pa.allocate(PageType.INDEX)

    assert p1 != p2 != p3
    assert pa.get_free_count() + pa.get_allocated_count() == pa.get_total_pages()

    # 释放一页
    pa.free(p2)
    assert pa.get_free_count() == 1

    # 重新分配应该得到p2
    p4 = pa.allocate(PageType.DATA)
    assert p4 == p2  # 位图分配器通常返回最小空闲页

def test_double_free():
    """测试重复释放应抛出异常"""
    fm = FileManager()
    pa = BitmapPageAllocator(fm)
    pa.initialize()

    p1 = pa.allocate(PageType.DATA)
    pa.free(p1)

    with pytest.raises(RuntimeError):
        pa.free(p1)  # 重复释放

def test_exhausted_allocation():
    """测试所有页耗尽时自动扩展"""
    fm = FileManager()
    pa = BitmapPageAllocator(fm)
    pa.initialize(initial_pages=10)  # 初始10页

    # 分配10页，应该全部分配完
    pages = [pa.allocate(PageType.DATA) for _ in range(10)]
    assert len(pages) == 10

    # 第11次分配应该触发扩展
    p11 = pa.allocate(PageType.DATA)
    assert p11 == 10  # 新页ID从10开始
    assert pa.get_total_pages() > 10
```

运行测试：
```bash
pytest tests/test_page_allocator.py -v
```

### 任务4：性能基准测试

实现一个对比测试：

```python
import time
from src.core.page_allocator_bitmap import BitmapPageAllocator
from src.core.page_allocator_freelist import FreeListAllocator  # 现有或自己实现

def benchmark_allocation(allocator_class, num_operations=10000):
    """测试分配和释放性能"""
    fm = FileManager()
    alloc = allocator_class(fm)
    alloc.initialize(initial_pages=1000)

    start = time.time()

    pages = []
    for i in range(num_operations // 2):
        pages.append(alloc.allocate(PageType.DATA))

    for pid in pages:
        alloc.free(pid)

    elapsed = time.time() - start
    return elapsed

print("位图分配器:", benchmark_allocation(BitmapPageAllocator))
print("链表分配器:", benchmark_allocation(FreeListAllocator))
```

**预期结果**：
- 位图：每次操作O(1)（有缓存）或O(n/64)（扫描）
- 链表：每次操作O(1)
- 位图优势：内存紧凑，缓存友好（位图小可能进L1/L2缓存）
- 链表优势：无扫描开销

### 任务5：扩展功能（选做）

#### 5.1 支持多类型页池
- 为DATA、INDEX、METADATA维持独立的位图或分区
- `allocate(type)`只从对应类型的空闲列表中分配

#### 5.2 实现预分配策略
- 当空闲页低于阈值时，自动扩展文件
- 实现渐进式扩展（每次扩展2倍）

#### 5.3 添加统计和监控
- 统计分配/释放次数
- 记录最长扫描距离（find_first_free的代价）
- 碎片率：`free_count / total_pages`

#### 5.4 实现伙伴系统
- 作为另一种`PageAllocator`子类
- 与位图对比性能（内部碎片 vs 查找速度）

## 五、实验要求

### 必做（70分）

- [ ] 实现`BitmapPageAllocator`类（40分）
- [ ] 编写单元测试并通过（20分）
- [ ] 完成性能基准测试（10分）

### 选做（30分）

- [ ] 实现多类型页池（10分）
- [ ] 添加预分配和自动扩展（10分）
- [ ] 实现伙伴分配器并与位图对比（10分）

## 六、实验报告

### 必须包含

1. **位图算法描述**：如何表示、如何分配/释放
2. **关键代码**：核心函数（`allocate`、`free`、`find_first_free`）
3. **测试结果**：单元测试截图
4. **性能数据**：与链表分配的对比表格
5. **问题记录**：遇到的bug和解决过程

### 可选

- 扩展功能实现细节
- 不同分配策略的对比分析
- 内存占用和速度的权衡

## 七、思考题

1. 位图在N=1,000,000页时需要多少内存？
2. 如何优化`find_first_free()`扫描速度？（提示：使用`__builtin_ffs`或类似CPU指令）
3. 在什么情况下位图分配器可能比链表更慢？
4. 混合策略：位图+链表（位图记录大块，链表记录零散）如何实现？

## 八、参考资料

- SQLite `pcache1` 页分配器（`src/pcache1.c`）
- Linux内核伙伴系统（`mm/page_alloc.c`）
- 操作系统教材：内存分配算法章节

---

**下一步**：完成实验2后，继续 [实验3：B+树索引](exp3_bplus_tree.md) 或返回 [实验指南](../README.md)。