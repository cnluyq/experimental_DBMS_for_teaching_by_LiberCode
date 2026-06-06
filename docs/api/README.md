# API参考文档

本文档提供ProjoDB核心模块的API参考。

## 📑 概述

ProjoDB C++ API以`db::StorageEngine`为核心，提供页式存储管理。

## 🗂️ 命名空间

所有类和函数都在`db`命名空间中。

## 🔧 核心类

### StorageEngine

主存储引擎类，提供高层数据访问接口。

#### 头文件
```cpp
#include "storage_engine.h"
```

#### 生命周期管理

```cpp
StorageEngine();  // 构造函数
~StorageEngine(); // 析构函数（自动刷新和关闭）
```

#### 方法

| 方法 | 返回 | 说明 |
|------|------|------|
| `bool create_or_open(const std::string& db_path)` | 成功/失败 | 创建或打开数据库文件 |
| `void close()` | void | 关闭数据库，刷新缓存 |
| `bool is_open() const` | 布尔 | 检查是否已打开 |
| `std::string get_db_path() const` | 路径 | 获取当前数据库路径 |
| `void flush()` | void | 将所有脏页写回磁盘 |

#### 页面操作

| 方法 | 返回 | 说明 |
|------|------|------|
| `uint32_t allocate_data_page()` | 页ID | 分配数据页 |
| `uint32_t allocate_index_page()` | 页ID | 分配索引页 |
| `uint32_t allocate_metadata_page()` | 页ID | 分配元数据页 |
| `void free_page(uint32_t page_id)` | void | 释放页 |
| `std::unique_ptr<Page> read_page(uint32_t page_id)` | Page指针 | 读取页（返回缓存副本） |
| `void write_page(Page* page)` | void | 写回页（可能缓存） |

#### 统计信息

```cpp
struct Stats {
    uint32_t total_pages;        // 总页数
    uint32_t allocated_pages;    // 已分配页数
    uint32_t free_pages;         // 空闲页数
    size_t file_size_bytes;      // 文件总字节数
};

Stats get_stats() const;
```

#### 异常

```cpp
class StorageException : public std::runtime_error {
public:
    explicit StorageException(const std::string& msg);
};
```

**可能抛出的异常**：
- `StorageException("Database already open")`
- `StorageException("Invalid page ID")`
- `StorageException("Failed to read page")`
- `StorageException("Failed to write page")`

#### 示例

```cpp
#include <iostream>
#include "storage_engine.h"

int main() {
    db::StorageEngine engine;

    // 打开数据库
    if (!engine.create_or_open("mydb.db")) {
        std::cerr << "Failed to open database\n";
        return 1;
    }

    try {
        // 分配数据页
        uint32_t page_id = engine.allocate_data_page();
        std::cout << "Allocated page: " << page_id << std::endl;

        // 读取页
        auto page = engine.read_page(page_id);
        page->set_data("Hello, DB!");

        // 写回页
        engine.write_page(page.get());

        // 刷新并关闭
        engine.flush();
        engine.close();
    } catch (const db::StorageException& e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
```

---

### Page

页面抽象类，表示固定大小的内存块。

#### 头文件
```cpp
#include "page.h"
```

#### 类型定义

```cpp
using PageID = uint32_t;
using PageSize = uint32_t;
constexpr PageSize DEFAULT_PAGE_SIZE = 4096;

enum class PageType : uint8_t {
    DATA = 0,      // 数据页
    INDEX = 1,     // 索引页
    METADATA = 2,  // 元数据页
    LOG = 3        // 日志页
};
```

#### 接口

```cpp
class Page {
public:
    Page(PageID page_id, PageSize size);
    virtual ~Page();

    // 页元信息
    PageID get_page_id() const;
    PageSize get_size() const;
    PageSize get_free_space() const;
    void set_type(PageType type);
    PageType get_type() const;

    // 数据访问
    std::vector<char>& get_data();
    const std::vector<char>& get_data() const;
    void set_data(const std::vector<char>& data);
    void set_data(const char* data, size_t len);

    // 检查
    bool is_dirty() const;
    void set_dirty(bool dirty);
};
```

#### 派生类（可选）

```cpp
class DataPage : public Page {
    // 堆表数据页：record_id列表 + 自由空间
};

class IndexPage : public Page {
    // B+树节点：内部节点或叶子
};

class LogPage : public Page {
    // WAL日志记录数组
};
```

---

### PageAllocator

页分配器，管理空闲空间。

#### 头文件
```cpp
#include "page_allocator.h"
```

#### 构造与初始化

```cpp
PageAllocator(FileManager* file_mgr);
void initialize();  // 从文件加载元数据或初始化
```

#### 分配与释放

```cpp
uint32_t allocate(PageType type);
void free(uint32_t page_id);
```

#### 页面访问（供FileManager使用）

```cpp
std::unique_ptr<Page> get_page(uint32_t page_id);
void put_page(Page* page);  // 回写修改的页
```

#### 统计

```cpp
uint32_t get_total_pages() const;
uint32_t get_free_count() const;
uint32_t get_allocated_count() const;
```

---

### FileManager

文件管理器，底层I/O操作。

#### 头文件
```cpp
#include "file_manager.h"
```

#### 文件操作

```cpp
bool open(const std::string& path);
void close();
bool is_open() const;
std::string get_path() const;
```

#### 页I/O

```cpp
std::vector<char> read_page(uint32_t page_id);
void write_page(uint32_t page_id, const std::vector<char>& data);
void flush();  // 强制刷盘
```

#### 文件信息

```cpp
uint32_t get_file_size() const;     // 以页为单位
uint64_t get_file_size_bytes() const;
void set_page_size(PageSize size);  // 通常只初始化一次
```

---

### BufferPool（Python）

LRU缓冲区池管理器。

#### 导入

```python
from src.core.buffer import BufferPool
```

#### 构造

```python
BufferPool(num_frames: int, storage_engine, logger=None, algorithm='lru')
```

**参数**：
- `num_frames`：缓冲区帧数（内存大小）
- `storage_engine`：存储引擎实例
- `logger`：日志记录器（可选）
- `algorithm`：置换算法（'lru'、'fifo'、'clock'）

#### 页面操作

```python
def read_page(page_id: int, pin: bool = True) -> Optional[BufferFrame]:
    """读取页面到缓冲区，返回BufferFrame"""

def create_page(page_id: int, data: bytes = b'', pin: bool = True) -> Optional[BufferFrame]:
    """创建新页面"""

def mark_dirty(page_id: int) -> bool:
    """标记页面为脏"""

def unpin_page(page_id: int) -> bool:
    """解除钉住"""

def flush_page(page_id: int) -> bool:
    """写回单个页面"""

def flush_all() -> bool:
    """写回所有脏页"""
```

#### 查询与统计

```python
def get_frame_info(page_id: int) -> Optional[Dict[str, Any]]:
    """获取页面在缓冲区中的信息"""

def get_buffer_stats() -> Dict[str, Any]:
    """获取缓冲区统计"""
    # 包含：hits, misses, hit_rate, reads_disk, writes_disk, evictions等

def get_lru_list() -> List[int]:
    """获取当前LRU顺序（帧ID列表）"""
```

#### 生命周期

```python
def shutdown():
    """关闭缓冲区（自动flush_all）"""
```

#### BufferFrame类

`read_page()`返回的`BufferFrame`对象：

```python
class BufferFrame:
    frame_id: int        # 帧ID
    page_id: int         # 页面ID（None表示空闲）
    data: bytearray      # 页面数据
    dirty: bool          # 是否脏
    pin_count: int       # 钉住计数
    access_time: int     # 访问时间戳
```

---

### Parser（Python）

SQL解析器。

#### 导入

```python
from src.parser import parse
```

#### parse函数

```python
def parse(sql: str):
    """
    解析SQL字符串

    Args:
        sql: SQL语句（以分号结尾）

    Returns:
        AST节点（SelectNode, InsertNode等）

    Raises:
        ParserError: 语法错误
    """
```

#### AST节点类型

```python
# DDL
class CreateTableNode:
    table_name: str
    columns: List[Tuple[str, str, List[str]]]  # (名, 类型, 约束)

class DropTableNode:
    table_name: str

# DML
class SelectNode:
    columns: List[str]
    table_name: str
    where_clause: Optional[Expression]

class InsertNode:
    table_name: str
    columns: List[str]
    values: List[Expression]

class UpdateNode:
    table_name: str
    set_clauses: List[Tuple[str, Expression]]
    where_clause: Optional[Expression]

class DeleteNode:
    table_name: str
    where_clause: Optional[Expression]

# 事务
class BeginNode: pass
class CommitNode: pass
class RollbackNode: pass

# 表达式
class BinaryOpNode:
    left: Expression
    op: str  # '=', '!=', '>', '<', '>=', '<=', 'AND', 'OR'
    right: Expression

class ColumnNode:
    column_name: str

class ValueNode:
    value: Any
    value_type: str  # 'integer', 'float', 'string'

class NullNode: pass
```

#### 示例

```python
from src.parser import parse

# 解析SELECT
ast = parse("SELECT * FROM users WHERE age > 18")
print(type(ast).__name__)  # SelectNode
print(ast.table_name)      # users
print(ast.where_clause)    # BinaryOpNode

# 解析CREATE TABLE
ast = parse("CREATE TABLE users (id INT, name VARCHAR(50))")
print(type(ast).__name__)  # CreateTableNode
print(ast.table_name)      # users
print(ast.columns)         # [('id', 'INT', []), ('name', 'VARCHAR(50)', [])]
```

---

## 🔌 存储引擎接口（Python）

自定义存储引擎需要实现以下接口：

```python
from src.core.storage_interface import StorageEngine

class MyStorageEngine:
    def page_read(self, page_id: int) -> Optional[bytes]:
        """读取页面，返回字节数据或None（页不存在）"""
        raise NotImplementedError

    def page_write(self, page_id: int, data: bytes):
        """写入页面（覆盖）"""
        raise NotImplementedError

    def allocate_page(self) -> int:
        """分配新页面，返回页面ID"""
        raise NotImplementedError

    def get_page_size(self) -> int:
        """返回页面大小"""
        raise NotImplementedError

    def get_free_pages(self) -> int:
        """返回空闲页数（可选，用于监控）"""
        return 0
```

**InMemoryStorage示例**：
```python
from src.core.storage_interface import InMemoryStorage

storage = InMemoryStorage(page_size=4096)
page_id = storage.allocate_page()
storage.page_write(page_id, b'x'*4096)
data = storage.page_read(page_id)
```

---

## 📊 错误代码

| 错误类型 | 场景 | 处理建议 |
|----------|------|----------|
| `StorageException` | 文件无法打开、页无效等 | 检查文件路径和权限 |
| `ParserError` | SQL语法错误 | 查看错误信息中的行列位置 |
| `std::out_of_range` | 访问超出范围的页 | 确保页ID有效 |
| `std::runtime_error` | 重复释放等 | 检查调用逻辑 |

---

## 🔄 版本兼容性

- **当前API版本**：1.0
- **向后兼容**：除非重大设计变更，API保持稳定
- **废弃**：标记为`[[deprecated]]`的函数将在下个版本移除

---

## 📚 更多信息

- [模块详细说明](../modules/README.md)
- [实验教程](../tutorials/README.md)
- [扩展建议](../extensions/README.md)