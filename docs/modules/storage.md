# 存储引擎模块详解

## 目录
- [概述](#概述)
- [架构设计](#架构设计)
- [核心类详解](#核心类详解)
  - [StorageEngine](#storageengine)
  - [FileManager](#filemanager)
  - [PageAllocator](#pageallocator)
  - [Page](#page)
- [页布局与数据格式](#页布局与数据格式)
- [设计模式](#设计模式)
- [C++实现细节](#c实现细节)
- [Python接口](#python接口)
- [实验项目](#实验项目)
- [常见问题](#常见问题)

---

## 概述

存储引擎（Storage Engine）是数据库最底层的组件，负责管理磁盘上的数据文件。它提供**页式存储**抽象，将数据划分为固定大小的页面（通常4KB），并提供页面的分配、读取、写入和释放功能。

### 核心职责

1. **文件管理**：创建、打开、关闭数据库文件
2. **页面I/O**：按页读写磁盘数据
3. **页分配**：管理空闲页，分配新页给数据或索引
4. **页元数据**：维护页的类型、状态、校验和等信息

### 设计原则

- **简单性**：接口最小化，易于理解和实现
- **可靠性**：正确处理异常，保证数据完整性
- **可扩展**：支持不同的页分配策略和文件组织方式
- **性能**：高效的I/O和缓存友好

### 优雅关闭顺序

数据库系统在关闭时必须遵循特定的顺序，以确保数据不丢失和一致性：

```
关闭顺序（由高到低）：
1. Executor（查询执行器）
   ↓
2. DatabaseStorage（数据库存储层，包含表管理器、系统表）
   ↓
3. WAL Manager（预写日志，确保持久化）
   ↓
4. Buffer Pool（缓冲区池，flush所有脏页）
   ↓
5. Storage Engine（存储引擎，最后关闭）

反向依赖关系：
- 每个组件关闭前，必须先关闭依赖它的上层组件
- 例如：Buffer Pool 依赖 Storage Engine，所以 Buffer Pool 先于 Storage Engine 关闭
- DatabaseStorage.close() 内部顺序：_close_resources() → 底层 engine
```

**为什么要反向关闭？**
- **数据安全**：确保所有脏页都被flush到磁盘
- **日志完整**：WAL在所有数据操作后关闭，确保持久性
- **资源清理**：避免引用已释放的下层资源

---

## 架构设计

存储引擎采用分层架构：

```
┌─────────────────────────────────────┐
│     StorageEngine (高层API)          │
│  • create_or_open()                 │
│  • allocate_data_page()             │
│  • read_page() / write_page()       │
├─────────────────────────────────────┤
│     PageAllocator (页分配器)         │
│  • 位图 or 空闲链表                 │
│  • 跟踪空闲/已分配页                │
├─────────────────────────────────────┤
│     FileManager (文件I/O)           │
│  • read_page() / write_page()       │
│  • 文件扩展和管理                  │
└─────────────────────────────────────┘
```

**数据流**：
```
应用请求 → StorageEngine → PageAllocator → FileManager → 磁盘
          ↑
     返回Page对象
```

---

## 核心类详解

### StorageEngine

主存储引擎类，提供高层接口供上层组件（缓冲区池、WAL、索引）使用。

#### C++接口

```cpp
namespace db {

class StorageEngine {
public:
    StorageEngine();
    ~StorageEngine();  // RAII：自动flush和close

    // 生命周期
    bool create_or_open(const std::string& db_path);
    void close();
    bool is_open() const;
    std::string get_db_path() const;

    // 页面操作
    uint32_t allocate_data_page();
    uint32_t allocate_index_page();
    uint32_t allocate_metadata_page();
    void free_page(uint32_t page_id);
    std::unique_ptr<Page> read_page(uint32_t page_id);
    void write_page(Page* page);

    // 缓存控制
    void flush();  // 强制所有修改写回磁盘

    // 统计信息
    struct Stats {
        uint32_t total_pages;
        uint32_t allocated_pages;
        uint32_t free_pages;
        uint64_t file_size_bytes;
    } get_stats() const;

    // 异常
    class StorageException : public std::runtime_error {
    public:
        explicit StorageException(const std::string& msg);
    };
};

} // namespace db
```

#### Python接口

```python
class StorageEngine(ABC):
    """存储引擎抽象基类（供BufferPool使用）"""

    @abstractmethod
    def page_read(self, page_id: int) -> Optional[bytes]:
        """读取页面，返回bytes或None（页不存在）"""

    @abstractmethod
    def page_write(self, page_id: int, data: bytes) -> bool:
        """写入页面，成功返回True"""

    @abstractmethod
    def allocate_page(self) -> int:
        """分配新页面ID"""

    def get_page_size(self) -> int:
        """返回页面大小，默认4096"""
        return 4096
```

**Python实现示例**：

```python
class SimpleFileStorage(StorageEngine):
    """基于文件的存储引擎"""

    def __init__(self, file_path: str, page_size: int = 4096):
        self.file_path = file_path
        self.page_size = page_size
        self.file = None
        self._init_file()

    def _init_file(self):
        """初始化文件，预分配空间"""
        import os
        if not os.path.exists(self.file_path):
            # 预分配100个页面
            with open(self.file_path, 'wb') as f:
                f.write(b'\x00' * 100 * self.page_size)
        self.file = open(self.file_path, 'r+b')

    def page_read(self, page_id: int) -> Optional[bytes]:
        """读取指定页面"""
        try:
            self.file.seek(page_id * self.page_size)
            data = self.file.read(self.page_size)
            if len(data) < self.page_size:
                return None  # 超出文件范围
            return data
        except Exception as e:
            return None

    def page_write(self, page_id: int, data: bytes) -> bool:
        """写入指定页面（覆盖）"""
        if len(data) != self.page_size:
            return False
        try:
            self.file.seek(page_id * self.page_size)
            self.file.write(data)
            self.file.flush()
            return True
        except Exception as e:
            return False

    def allocate_page(self) -> int:
        """分配新页面（返回下一个可用ID）"""
        import os
        file_size = os.path.getsize(self.file_path)
        num_pages = file_size // self.page_size
        # 注意：这不是真正的分配，只是获取下一个ID
        # 真正的页分配器会跟踪哪些页已分配
        return num_pages

    def close(self):
        if self.file:
            self.file.close()
```

---

### FileManager

文件管理器，负责底层文件I/O操作。

#### 职责

- 打开/关闭数据库文件
- 按页读取和写入原始字节
- 文件扩展（自动增加文件大小）
- 缓存系统调用（使用`std::fstream`的缓冲）

#### C++类定义

```cpp
class FileManager {
public:
    FileManager();
    ~FileManager();

    bool open(const std::string& path);
    void close();
    bool is_open() const;
    std::string get_path() const;

    // 页I/O
    std::vector<char> read_page(uint32_t page_id);
    void write_page(uint32_t page_id, const std::vector<char>& data);

    // 文件信息
    uint32_t get_file_size() const;      // 以页为单位
    uint64_t get_file_size_bytes() const;
    void set_page_size(uint32_t size);

private:
    std::fstream file_;
    std::string path_;
    uint32_t page_size_;
};
```

#### 关键实现细节

```cpp
std::vector<char> FileManager::read_page(uint32_t page_id) {
    if (!file_.is_open()) {
        throw StorageException("File not open");
    }

    // 计算偏移量 = page_id * page_size
    std::streamoff offset = static_cast<std::streamoff>(page_id) * page_size_;
    file_.seekg(offset);
    if (!file_) {
        throw StorageException("Seek failed");
    }

    // 读取页面数据
    std::vector<char> buffer(page_size_);
    file_.read(buffer.data(), page_size_);
    if (!file_) {
        throw StorageException("Read failed");
    }

    return buffer;
}
```

---

### PageAllocator

页分配器，管理空闲空间分配和页面元数据。

#### 职责

- 从文件加载/保存页分配元数据
- 根据请求分配指定类型的页（数据、索引、元数据）
- 回收已释放的页
- 提供对页的访问（供`FileManager`使用）

#### 分配策略

**策略1：位图（Bitmap）**
```
位图：第i位表示第i页是否空闲（0=已分配，1=空闲）
优点：简单，快速查找
缺点：大数据库占用内存
```

**策略2：空闲链表（Free List）**
```
头指针 → 页号1 → 页号2 → 页号3 → ... → 空
优点：节省内存，支持任意大小分配
缺点：需要遍历查找
```

**策略3：伙伴分配器（Buddy）**
```
将空间按2的幂次分割，适合连续分配
优点：减少碎片
缺点：实现复杂，有内碎片
```

#### C++类定义

```cpp
class PageAllocator {
public:
    enum class PageType : uint8_t {
        DATA = 0,
        INDEX = 1,
        METADATA = 2
    };

    PageAllocator(FileManager* file_mgr);
    ~PageAllocator();

    // 初始化（从文件或新建）
    void initialize();

    // 分配/释放
    uint32_t allocate(PageType type);
    void free(uint32_t page_id);

    // 页面访问（供FileManager使用）
    std::unique_ptr<Page> get_page(uint32_t page_id);
    void put_page(Page* page);  // 回写修改的页

    // 统计
    uint32_t get_total_pages() const;
    uint32_t get_free_count(PageType type) const;
    uint32_t get_allocated_count(PageType type) const;

private:
    FileManager* file_mgr_;
    std::vector<bool> bitmap_;  // 位图：true=空闲
    std::vector<uint32_t> free_list_;  // 空闲链表（可选）
    uint32_t next_page_id_;
};
```

#### 实现示例（位图）

```cpp
uint32_t PageAllocator::allocate(PageType type) {
    // 在位图中查找空闲页
    for (uint32_t i = 0; i < bitmap_.size(); i++) {
        if (bitmap_[i]) {
            bitmap_[i] = false;  // 标记为已分配
            return i;
        }
    }

    // 没有空闲页，扩展文件
    uint32_t new_page = next_page_id_++;
    bitmap_.push_back(false);
    return new_page;
}

void PageAllocator::free(uint32_t page_id) {
    if (page_id >= bitmap_.size()) {
        throw StorageException("Invalid page ID");
    }
    if (bitmap_[page_id]) {
        throw StorageException("Double free");
    }
    bitmap_[page_id] = true;  // 标记为空闲
}
```

---

### Page

页面抽象类，表示固定大小的内存块。

#### 页布局

```
┌─────────────────────────────────────────────┐
│           Page Header (固定大小)            │
│  • page_id: uint32_t                        │
│  • page_type: PageType                      │
│  • checksum: uint32_t                       │
│  • lsn: uint64_t (日志序列号)               │
│  • next_page_id: uint32_t (链表)            │
│  • free_space_offset: uint16_t (堆表)       │
├─────────────────────────────────────────────┤
│                 Page Body                   │
│  • 变长数据（取决于页类型）                │
│  • 堆表：记录数据 + Slot Directory         │
│  • B+树：键值对 + 子节点指针               │
│  • WAL：日志记录数组                       │
└─────────────────────────────────────────────┘
```

#### C++类定义

```cpp
class Page {
public:
    using PageID = uint32_t;
    static constexpr PageID INVALID_PAGE_ID = static_cast<PageID>(-1);

    Page(PageID page_id, uint32_t size);
    virtual ~Page();

    // 元信息
    PageID get_page_id() const;
    void set_page_id(PageID id);
    uint32_t get_size() const;
    PageType get_type() const;
    void set_type(PageType type);

    // 数据访问
    std::vector<char>& get_data();
    const std::vector<char>& get_data() const;
    void set_data(const std::vector<char>& data);
    void set_data(const char* data, size_t len);

    // 校验和
    uint32_t compute_checksum() const;
    bool verify_checksum() const;
    void update_checksum();

    // 脏标记（供缓冲区池使用）
    bool is_dirty() const;
    void set_dirty(bool dirty);

    // LSN（用于WAL恢复）
    uint64_t get_lsn() const;
    void set_lsn(uint64_t lsn);

    // 序列化/反序列化
    virtual void serialize(std::ostream& out) const;
    virtual void deserialize(std::istream& in);
};

// 派生类示例：DataPage
class DataPage : public Page {
public:
    DataPage(PageID page_id, uint32_t size);
    // 堆表特定方法
    uint16_t get_free_space_offset() const;
    void set_free_space_offset(uint16_t offset);
    void add_record(const std::vector<char>& record);
    void delete_record(uint16_t slot_id);
    // ...
};
```

---

## 页布局与数据格式

### 数据页（DataPage）结构

ProjoDB使用**堆文件（Heap File）**组织数据页，每个表对应一个数据文件。

#### 页格式

```
┌─────────────────────────────────────────────┐
│ Header (32 bytes)                           │
│  • page_id (4)                              │
│  • page_type (1)                            │
│  • free_space_offset (2)                    │
│  • record_count (2)                         │
│  • checksum (4)                             │
│  • lsn (8)                                  │
│  • reserved (11)                            │
├─────────────────────────────────────────────┤
│ Record Area (变长)                          │
│  [record1][record2][record3]...            │
│  顺序存储，free_space_offset指向下一个空闲位置│
├─────────────────────────────────────────────┤
│ Slot Directory (变长)                       │
│  [offset, len] [offset, len] ... [0, 0]    │
│  逆序插入，便于删除（标记为0即可）           │
└─────────────────────────────────────────────┘
```

#### 记录格式（变长记录）

```
┌─────────────────────────────────┐
│ slot_len (2 bytes)              │  ← 总长度（包括自身）
│ null_bitmap (ceil(n/8) bytes)   │  ← 每列1 bit (1=NULL)
│ column1_value (变长)             │
│ column2_value (变长)             │
│ ...                             │
└─────────────────────────────────┘
```

**编码示例**（INT + VARCHAR(20) + BOOLEAN）：
```
记录：(42, "hello", true)
长度：2 + 1 + 4 + 1 + 5 + 1 = 14 字节

字节序列：
0E 00          ← slot_len = 14 (小端)
00             ← null bitmap = 0 (全非NULL)
32 00 00 00    ← INT 42
05             ← VARCHAR len = 5
68 65 6C 6C 6F ← "hello"
01             ← BOOLEAN true
```

---

## 设计模式

### 1. RAII（资源获取即初始化）

```cpp
{
    db::StorageEngine engine;
    engine.create_or_open("mydb.db");
    // 使用engine...
} // engine析构，自动flush并关闭文件
```

### 2. Factory（工厂模式）

根据页类型创建不同的Page子类：

```cpp
std::unique_ptr<Page> PageAllocator::create_page(PageType type, PageID id) {
    switch (type) {
        case PageType::DATA:
            return std::make_unique<DataPage>(id, page_size_);
        case PageType::INDEX:
            return std::make_unique<IndexPage>(id, page_size_);
        case PageType::METADATA:
            return std::make_unique<MetadataPage>(id, page_size_);
        default:
            return std::make_unique<Page>(id, page_size_);
    }
}
```

### 3. Flyweight（享元模式）

`get_page()`返回共享的页面对象（可能在缓冲区池中已存在），避免重复读取。

### 4. Strategy（策略模式）

可替换的页分配算法：

```cpp
class IPageAllocationStrategy {
public:
    virtual ~IPageAllocationStrategy() = default;
    virtual uint32_t allocate() = 0;
    virtual void free(uint32_t page_id) = 0;
};

class BitmapAllocation : public IPageAllocationStrategy { ... };
class FreeListAllocation : public IPageAllocationStrategy { ... };
```

---

## C++实现细节

### 文件映射 vs 读写

**方法1：使用`std::fstream`（简单）**
```cpp
std::fstream file;
file.open(path, std::ios::in | std::ios::out | std::ios::binary);
file.seekg(offset);
file.read(buffer, size);
```

**方法2：使用`mmap`（高性能，平台相关）**
```cpp
#include <sys/mman.h>
int fd = open(path, O_RDWR);
void* addr = mmap(nullptr, length, PROT_READ|PROT_WRITE, MAP_SHARED, fd, 0);
// 直接内存访问
munmap(addr, length);
close(fd);
```

### 异常安全

```cpp
bool StorageEngine::write_page(Page* page) {
    try {
        file_mgr_.write_page(page->get_page_id(), page->get_data());
        page->set_dirty(false);
        return true;
    } catch (const StorageException& e) {
        if (logger_) logger_->error("Write failed: {}", e.what());
        return false;
    }
}
```

---

## Python接口

Python实现的存储引擎用于快速原型开发和测试：

### 内置实现

1. **SimpleFileStorage**：基于文件的存储
2. **InMemoryStorage**：内存存储（单元测试）

### 自定义存储引擎

实现`StorageEngine`抽象基类：

```python
class MyStorage(StorageEngine):
    def page_read(self, page_id):
        # 你的逻辑
        pass

    def page_write(self, page_id, data):
        # 你的逻辑
        pass

    def allocate_page(self):
        # 你的逻辑
        pass
```

---

## 实验项目

### 实验1：实现位图分配器

**目标**：完成`PageAllocator`的位图实现。

**步骤**：
1. 在`page_allocator.cpp`中实现`allocate()`和`free()`
2. 使用`std::vector<bool>`或自定义位图容器
3. 编写单元测试：分配10页，释放第3页，再分配应得到3

**测试**：
```cpp
TEST(PageAllocatorTest, allocate_free) {
    PageAllocator allocator(&file_mgr);
    allocator.initialize();

    std::vector<uint32_t> ids;
    for (int i = 0; i < 10; i++) {
        ids.push_back(allocator.allocate(PageType::DATA));
    }
    EXPECT_EQ(ids[0], 0);
    EXPECT_EQ(ids[1], 1);

    allocator.free(ids[3]);
    uint32_t new_id = allocator.allocate(PageType::DATA);
    EXPECT_EQ(new_id, 3);  // 重用已释放的页
}
```

### 实验2：实现文件扩展

**目标**：当文件空间不足时自动扩展。

**步骤**：
1. 在`FileManager::write_page()`检测越界写
2. 使用`resize()`或`seek`到新位置扩展文件
3. 更新文件大小元数据

**测试**：分配超过初始大小的页，验证文件增长。

### 实验3：页校验和

**目标**：实现CRC32校验和检测数据损坏。

**步骤**：
1. 在`Page`中添加`checksum`字段
2. 写入页面时计算`compute_checksum()`
3. 读取页面时`verify_checksum()`
4. 损坏数据时抛出异常

---

## 常见问题

### Q1: 页大小如何选择？

**A**: 通常4KB是标准（与磁盘扇区对齐），但也支持8KB或16KB。更大的页减少元数据开销，但增加内部碎片。建议4KB。

### Q2: 如何管理不同类型的页？

**A**: `PageType`枚举区分DATA、INDEX、METADATA。`PageAllocator::allocate()`接受类型参数，可针对不同类型使用不同的分配策略（如索引页连续分配）。

### Q3: 文件扩展策略？

**A**: 预分配（启动时分配固定数量）或按需分配（需要时扩展）。建议预分配100-1000页，减少碎片。

### Q4: C++和Python实现如何选择？

**A**:
- **C++**：生产级性能，适合完整系统
- **Python**：教学和实验，快速迭代
- 推荐：先用Python实现所有模块，再用C++重写性能关键部分（存储、缓冲）

### Q5: 如何与缓冲区池集成？

**A**: `StorageEngine`提供`read_page()`/`write_page()`。缓冲区池调用：
- `read_page()`：从磁盘读取（未缓存时）
- `write_page()`：写回磁盘（置换或flush时）
- `allocate_page()`：分配新页（创建表时）

---

## 参考实现

- `src/core/storage_engine.cpp`：C++完整实现
- `src/core/storage_interface.py`：Python接口定义
- `src/core/storage_engine.cpp`中的类图和使用示例

---

**下一步**：学习 [缓冲区池模块](buffer.md) 或继续 [实验2：页分配器](docs/tutorials/exp2_allocator.md)
