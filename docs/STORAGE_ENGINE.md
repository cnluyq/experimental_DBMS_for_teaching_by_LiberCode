# 存储引擎说明文档

## 概述

存储引擎是ProjoDB的核心模块，负责管理数据库文件的物理存储、页分配和记录存储。本模块提供以下核心功能：

- 文件创建、打开、关闭
- 页分配和回收（固定4KB页大小）
- 页读写抽象层
- 页类型定义（数据页、索引页、元数据页）
- 空闲页管理（基于链表）
- 基于槽目录的数据记录存储

## 文件格式

### 文件头结构

位于文件第0页（页ID 0），包含全局元数据：

```c
struct FileHeader {
    uint32_t magic;           // 魔数: 0x4442544D ("DBTM")
    uint32_t version;         // 版本号: 1
    uint32_t page_size;       // 页大小: 4096
    uint32_t total_pages;     // 总页数（包括文件头）
    uint32_t free_page_count; // 空闲页数量
    uint32_t first_free_page; // 空闲链表头
    uint8_t  reserved[40];    // 保留字段
};
```

### 空闲页管理

空闲页通过`PageHeader`中的`next_free`字段形成单链表：
- 文件头的`first_free_page`指向第一个空闲页
- 每个空闲页的页头中`next_free`指向下一个空闲页
- 值为0表示链表结束

### 页结构

每页固定4KB（4096字节），由以下部分组成：

```
┌─────────────────────────────────────┐
│           Page Header (28B)         │
├─────────────────────────────────────┤
│          Data Area (variable)       │
│  ┌──────┬──────┬──────┬──────┐    │
│  │Rec 0│Rec 1│Rec 2│ ...  │    │
│  └──────┴──────┴──────┴──────┘    │
├─────────────────────────────────────┤
│        Slot Directory (variable)    │
│  ┌──────────┬──────────┬─────────┐│
│  │[off,len] │[off,len] │[off,len]││
│  └──────────┴──────────┴─────────┘│
└─────────────────────────────────────┘
```

**PageHeader** (28字节):
```c
struct PageHeader {
    PageType type;       // 页类型
    uint32_t page_id;    // 页ID
    uint32_t next_free;  // 空闲链表next（仅空闲页使用）
    uint16_t free_space; // 空闲空间大小
    uint16_t slot_count; // 槽数量（数据页）
    uint16_t data_end;   // 数据区尾部偏移
    uint8_t  reserved[6]; // 保留
};
```

**Slot** (4字节):
```c
struct Slot {
    uint16_t offset;  // 记录偏移（相对数据区起始）
    uint16_t length;  // 记录长度
};
```

## 核心API

### StorageEngine

```c++
namespace db {

class StorageEngine {
public:
    StorageEngine();
    ~StorageEngine();

    // 创建或打开数据库文件
    bool create_or_open(const std::string& db_path);

    // 关闭数据库
    void close();

    // 检查是否打开
    bool is_open() const;

    // 分配新页
    uint32_t allocate_data_page();
    uint32_t allocate_index_page();
    uint32_t allocate_metadata_page();

    // 释放页
    void free_page(uint32_t page_id);

    // 读写页
    std::unique_ptr<Page> read_page(uint32_t page_id);
    void write_page(Page* page);

    // 刷新到磁盘
    void flush();

    // 获取统计信息
    struct Stats {
        uint32_t total_pages;
        size_t allocated_pages;
        size_t free_pages;
        size_t file_size_bytes;
    };
    Stats get_stats() const;
};

}
```

### Page（数据页记录操作）

```c++
class Page {
public:
    // 插入记录（数据页）
    // 返回值：槽ID（>=0）或-1（失败）
    int insert_record(const uint8_t* data, uint16_t len);

    // 删除记录（标记删除，不立即回收空间）
    bool delete_record(uint16_t slot_id);

    // 更新记录（仅支持相同长度原地更新）
    bool update_record(uint16_t slot_id, const uint8_t* data, uint16_t len);

    // 获取记录
    const uint8_t* get_record(uint16_t slot_id, uint16_t& out_len) const;

    // 遍历所有有效记录
    void iterate_records(
        void (*callback)(uint16_t slot_id, const uint8_t* data, uint16_t len, void* ctx),
        void* ctx = nullptr
    ) const;

    // 紧凑化页面（合并删除记录的碎片）
    void compact();

    // 获取信息
    uint16_t get_slot_count() const;
    uint16_t get_free_space() const;
    PageType get_type() const;
    uint32_t get_page_id() const;
};
```

## 使用示例

### 基本用例

```c++
#include "storage_engine.h"
using namespace db;

int main() {
    StorageEngine engine;

    // 打开数据库
    if (!engine.create_or_open("mydb.dat")) {
        return 1;
    }

    // 分配一个数据页
    uint32_t page_id = engine.allocate_data_page();

    // 读取页
    auto page = engine.read_page(page_id);

    // 插入记录
    const char* msg = "Hello, World!";
    int slot = page->insert_record(
        reinterpret_cast<const uint8_t*>(msg),
        strlen(msg) + 1
    );

    // 标记脏并写回
    page->set_dirty(true);
    engine.write_page(page.get());

    // 刷新并关闭
    engine.flush();
    engine.close();

    return 0;
}
```

### 遍历记录

```c++
auto page = engine.read_page(page_id);
page->iterate_records(
    [](uint16_t slot_id, const uint8_t* data, uint16_t len, void* ctx) {
        std::string record(reinterpret_cast<const char*>(data), len);
        std::cout << "Slot " << slot_id << ": " << record << std::endl;
    }
);
```

## 设计考量

1. **固定页大小（4KB）**: 简化内存管理和磁盘I/O，适合现代文件系统
2. **mmap内存映射**: 提高文件I/O性能，简化缓冲区管理
3. **槽目录设计**: 支持变长记录存储，记录删除不立即回收空间
4. **空闲链表**: 高效管理页面分配和回收
5. **页类型区分**: 数据页、索引页、元数据页使用不同处理逻辑

## 限制与未来扩展

### 当前限制

- `Page::allocate()`/`deallocate()`已废弃，需使用slot-based接口
- 页面compact()需手动调用，不自动触发
- 不支持跨页记录（记录必须完整在一页内）

### 未来扩展

- 自动compact策略（当碎片率超阈值时）
- 不同记录编码格式支持（NULL位图、变长整数等）
- 页校验和（用于完整性检查）
- 压缩存储

## 文件布局示例

典型数据库文件 `test.dat`:

```
Page 0: FileHeader (魔法数、元数据、空闲链表头)
Page 1: Data page (多个记录 + 槽目录)
Page 2: Data page
Page 3: Index page (B+树节点)
...
```

文件头(page 0)的`first_free_page`指向第一个空闲页（比如page 10），page 10的`next_free`指向page 11，依此类推，直到0表示链表结束。

## 测试

运行存储引擎测试:

```bash
make -f Makefile.storage test
# 或直接
./test_storage
```

测试覆盖：
- 数据库创建/打开/关闭
- 页分配和释放
- 记录插入、遍历
- 数据持久化验证

---

**模块完成度**: 95%  
**最后更新**: 2024-06-04  
**作者**: storage_engineer
