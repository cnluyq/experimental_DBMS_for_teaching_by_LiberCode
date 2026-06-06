# 核心模块说明

本文档详细介绍ProjoDB各核心模块的设计理念、实现细节和使用方法。

## 📑 目录

- [存储引擎 (Storage Engine)](#存储引擎-storage-engine)
- [LRU缓冲区池 (Buffer Pool)](#lru缓冲区池-buffer-pool)
- [SQL解析器 (SQL Parser)](#sql解析器-sql-parser)
- [WAL日志系统 (WAL)](#wal日志系统-wal)
- [B+树索引 (B+ Tree Index)](#b树索引-b-tree-index)

---

## 存储引擎 Storage Engine

### 概述

存储引擎是数据库最底层的组件，负责管理磁盘上的数据文件。它提供页式存储抽象，将数据划分为固定大小的页面（通常4KB），并提供页面的分配、读写和释放功能。

### 架构设计

```
┌─────────────────────────────────────┐
│         StorageEngine (高层API)      │
├─────────────────────────────────────┤
│         PageAllocator (页分配)       │
├─────────────────────────────────────┤
│         FileManager (文件I/O)        │
└─────────────────────────────────────┘
```

### 核心类

#### `StorageEngine`

主存储引擎类，提供以下功能：
- `create_or_open(db_path)`：创建或打开数据库文件
- `allocate_data_page()` / `allocate_index_page()`：分配页面
- `read_page(page_id)` / `write_page(page)`：读写页面
- `free_page(page_id)`：释放页面
- `flush()`：刷新缓存
- `get_stats()`：获取统计信息

#### `FileManager`

文件管理器，负责：
- 以读写模式打开数据库文件
- 按页读取和写入原始字节
- 文件大小管理（扩展）
- 缓存系统调用（缓冲I/O）

关键方法：
```cpp
bool open(const std::string& path);
void close();
std::vector<char> read_page(uint32_t page_id);
void write_page(uint32_t page_id, const std::vector<char>& data);
uint32_t get_file_size() const;  // 总页数
```

#### `PageAllocator`

页分配器，管理页面空间分配：
- 使用位图（bitmap）或空闲链表跟踪空闲页
- 区分不同页类型（数据、索引、元数据）
- 支持页面回收和重用

关键方法：
```cpp
void initialize();  // 初始化（从文件读取元数据）
uint32_t allocate(PageType type);
void free(uint32_t page_id);
std::unique_ptr<Page> get_page(uint32_t page_id);
void put_page(Page* page);  // 回写修改的页面
```

#### `Page`

页面抽象类，表示一个固定大小的内存块：
- 包含数据和元信息（页ID、类型、校验和等）
- 支持序列化和反序列化
- 可扩展为不同子类型（数据页、索引页、日志页）

### 页布局

一个典型的数据页结构（4KB）：
```
┌─────────────────────────────────────────────┐
│ 页头 (Header) - 固定大小                    │
├─────────────────────────────────────────────┤
│ 页体 (Body) - 变长数据                      │
│  • 记录数据（堆表）                         │
│  • 索引节点（B+树）                         │
│  • 日志记录（WAL）                          │
└─────────────────────────────────────────────┘
```

页头（PageHeader）通常包含：
- `page_id`：页面唯一标识
- `page_type`：页面类型（DATA/INDEX/METADATA/LOG）
- `next_page_id`：链表下一页（用于溢出页或日志）
- `checksum`：校验和（用于数据完整性检查）
- `lsn`：日志序列号（用于恢复）
- `free_space_offset`：空闲空间偏移（堆表）

### 设计模式

- **RAII（资源获取即初始化）**：`StorageEngine`在析构时自动清理
- **Factory（工厂模式）**：根据页类型创建不同的`Page`子类
- **Flyweight（享元模式）**：`get_page()`返回共享的页面对象
- **Strategy（策略模式）**：可替换的页分配算法

### 扩展建议

1. **实现不同的页分配策略**：
   - 伙伴分配器（Buddy Allocator）
   - 分段分配器（Segmented Allocator）
   - 自适应分配器

2. **添加页压缩**：
   - 前端压缩（如LZ4）
   - 字典压缩
   - 增量压缩

3. **实现多文件管理**：
   - 表空间（Tablespace）
   - 分区表（Partitioned Tables）
   - 归档存储

### 代码示例

```cpp
// 创建存储引擎并打开数据库
db::StorageEngine engine;
engine.create_or_open("mydb.db");

// 查看统计信息
auto stats = engine.get_stats();
std::cout << "Total pages: " << stats.total_pages << std::endl;
std::cout << "Allocated: " << stats.allocated_pages << std::endl;

// 分配和操作数据页
uint32_t data_page = engine.allocate_data_page();
auto page = engine.read_page(data_page);

// 写入数据（假设page有set_data方法）
page->set_data("Hello, ProjoDB!");

// 标记脏页并写回
engine.write_page(page.get());

// 关闭数据库（自动刷新）
engine.close();
```

---

## LRU缓冲区池 Buffer Pool

### 概述

缓冲区池是数据库性能的关键组件，它在内存中缓存热点数据页，减少昂贵的磁盘I/O。ProjoDB实现了经典的LRU（最近最少使用）置换算法，配合钉住机制防止重要页面被驱逐。

### 架构设计

```
BufferPool（管理器）
├── 帧数组：BufferFrame[num_frames]
├── LRU链表：维护访问顺序
├── 页面映射：page_id → frame_id
└── 存储引擎：底层I/O
```

### 核心算法

#### 1. LRU置换

```python
def _find_victim_frame(self):
    """寻找牺牲帧（LRU：选择最久未使用的"""
    for frame_id in self.lru_list:  # 从尾部开始（最旧）
        frame = self.frames[frame_id]
        if not frame.is_pinned():    # 未钉住
            return frame
    return None  # 没有可用帧
```

**访问页面时的LRU更新**：
```python
def read_page(self, page_id, pin=True):
    if page_id in self.page_to_frame:
        # 命中：更新LRU位置
        frame_id = self.page_to_frame[page_id]
        self._update_access_time(frame)
        self._move_to_lru_head(frame_id)  # 移到头部（最新）
```

#### 2. 脏页写回

脏页在以下时机写回磁盘：
- **置换时**：牺牲帧是脏页则先写回
- **显式刷新**：调用`flush_page()`或`flush_all()`
- **关闭时**：`shutdown()`调用`flush_all()`

```python
def _evict_page(self, frame):
    if frame.dirty:
        if not self._write_page_to_disk(frame):
            return False  # 写回失败
        self.stats['evicted_dirty'] += 1
    # 清除映射和状态
    del self.page_to_frame[frame.page_id]
    frame.set_page(None, b'', False)
```

#### 3. Pin/Unpin机制

防止重要页面被意外驱逐：
```python
frame.pin()      # 钉住，pin_count++
frame.unpin()    # 解除，pin_count--
# 只有pin_count == 0的页面才能被替换
```

**最佳实践**：访问页面后尽快unpin，避免内存泄漏。

### 性能统计

缓冲区池自动收集以下指标：

| 指标 | 说明 |
|------|------|
| `reads_total` | 总访问次数 |
| `hits` / `misses` | 缓存命中/未命中 |
| `hit_rate` | 命中率 = hits / reads_total |
| `reads_disk` | 实际磁盘读取次数 |
| `writes_disk` | 写回磁盘次数 |
| `evictions` | 页面置换次数 |
| `evicted_dirty` | 置换的脏页数 |
| `used_frames` / `free_frames` | 帧使用情况 |

### 线程安全

所有公共方法使用`threading.RLock`保护：
```python
def read_page(self, page_id, pin=True):
    with self.lock:  # 自动获取和释放锁
        # ... 操作共享数据 ...
```

**注意**：
- 锁粒度：整个方法一个锁（简单但可能成为瓶颈）
- 可优化：细粒度锁（每帧或每页一个锁）

### 使用模式

#### 基本读模式
```python
frame = buffer.read_page(page_id, pin=True)
# 使用 frame.data 读取/修改
if modified:
    buffer.mark_dirty(page_id)
buffer.unpin_page(page_id)  # 必须显式unpin
```

#### 批量处理模式
```python
def process_pages(buffer, page_ids):
    frames = []
    for pid in page_ids:
        frame = buffer.read_page(pid, pin=True)
        frames.append(frame)

    try:
        # 处理所有页面
        for frame in frames:
            process(frame)
    finally:
        # 确保释放所有钉住
        for frame in frames:
            buffer.unpin_page(frame.page_id)
```

#### 刷新模式
```python
# 刷新单个页面
buffer.flush_page(page_id)

# 刷新所有脏页
buffer.flush_all()

# 关闭（自动刷新）
buffer.shutdown()
```

### 实验项目

1. **基准测试**：
   - 测试不同工作负载（顺序、随机、Zipf分布）
   - 测量帧数对命中率的影响
   - 绘制命中率-帧数曲线

2. **算法替换**：
   - 实现Clock置换算法
   - 实现LFU（最不常用）算法
   - 比较LRU、Clock、LFU的性能

3. **预热分析**：
   - 实现预取（Prefetching）：顺序访问时预读下一页
   - 测量预取对性能的影响

4. **并发性能**：
   - 测试多线程并发访问
   - 分析锁竞争瓶颈
   - 尝试无锁数据结构（可选，高级）

---

## SQL解析器 SQL Parser

### 概述

SQL解析器将SQL字符串转换为抽象语法树（AST），供后续执行。采用经典的**递归下降**方法，配合词法分析器（Tokenizer）。

### 处理流程

```
SQL字符串 → Tokenizer → Token流 → Parser → AST
```

### 词法分析（Tokenizer）

**功能**：将原始SQL字符串分解为Token序列。

**Token类型**：
```python
Token(type='KEYWORD', value='SELECT', line=1, col=1)
Token(type='IDENTIFIER', value='users', line=1, col=8)
Token(type='INTEGER', value='123', line=2, col=5)
Token(type='STRING', value='hello', line=3, col=10)
Token(type='OPERATOR', value='=', line=1, col=15)
```

**关键规则**：
- 关键字：`SELECT`, `FROM`, `WHERE`, `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `DROP`等（大小写不敏感）
- 标识符：字母开头，可含字母数字下划线
- 字符串：单引号括起，支持转义
- 数字：整数和浮点数
- 运算符：`=`, `!=`, `>`, `<`, `>=`, `<=`, `AND`, `OR`
- 分隔符：`(`, `)`, `,`, `;`

**状态机实现**：
```python
def tokenize(self):
    while self.pos < len(self.sql):
        ch = self.sql[self.pos]

        if ch.isspace():
            self.pos += 1  # 跳过空白
        elif ch.isalpha() or ch == '_':
            yield self._read_identifier()
        elif ch.isdigit():
            yield self._read_number()
        elif ch == "'":
            yield self._read_string()
        # ...
```

### 语法分析（Parser）

**方法**：递归下降，每个非终结符对应一个`parse_*`方法。

**语法规则**（简化BNF）：
```
<statement> ::= <select_stmt>
              | <insert_stmt>
              | <update_stmt>
              | <delete_stmt>
              | <create_table_stmt>
              | <drop_table_stmt>
              | <begin_stmt>
              | <commit_stmt>
              | <rollback_stmt>

<select_stmt> ::= SELECT <column_list> FROM <identifier> [WHERE <expr>]
<insert_stmt> ::= INSERT INTO <identifier> [(<col_list>)] VALUES (<val_list>)
<update_stmt> ::= UPDATE <identifier> SET <set_list> [WHERE <expr>]
...
```

**优先级处理**（表达式）：
```
expr    → or_expr
or_expr → and_expr (OR and_expr)*
and_expr → cmp_expr (AND cmp_expr)*
cmp_expr → primary (EQ|NE|GT|LT|GE|LE primary)?
primary → IDENTIFIER | INTEGER | FLOAT | STRING | NULL | '(' expr ')'
```

### 抽象语法树（AST）

每个SQL语句类型对应一个AST节点类：

#### 数据定义
```python
class CreateTableNode:
    table_name: str
    columns: List[Tuple[str, str, List[str]]]  # (name, type, constraints)

class DropTableNode:
    table_name: str
```

#### 数据操作
```python
class SelectNode:
    columns: List[str]  # 或 ['*']
    table_name: str
    where_clause: Optional[Expression]

class InsertNode:
    table_name: str
    columns: List[str]  # 可选
    values: List[Expression]

class UpdateNode:
    table_name: str
    set_clauses: List[Tuple[str, Expression]]
    where_clause: Optional[Expression]

class DeleteNode:
    table_name: str
    where_clause: Optional[Expression]
```

#### 表达式
```python
class BinaryOpNode:
    left: Expression
    op: str  # '=', '!=', '>', '<', '>=', '<=', 'AND', 'OR'
    right: Expression

class ColumnNode:
    column_name: str

class ValueNode:
    value: Any
    value_type: str  # 'integer', 'float', 'string'

class NullNode:
    pass
```

### 使用示例

```python
from src.parser import parse

# 解析SQL字符串
sql = "SELECT name, age FROM users WHERE age > 18 AND status = 'active'"
ast = parse(sql)

# 检查语句类型
print(type(ast).__name__)  # 'SelectNode'

# 访问AST属性
print(ast.table_name)  # 'users'
print(ast.columns)     # ['name', 'age']
print(ast.where_clause)  # BinaryOpNode(AND)

# 遍历表达式树
def print_ast(node, indent=0):
    print('  ' * indent + type(node).__name__)
    if isinstance(node, BinaryOpNode):
        print_ast(node.left, indent + 1)
        print(f"{'  ' * (indent+1)}OP: {node.op}")
        print_ast(node.right, indent + 1)
    elif isinstance(node, ColumnNode):
        print(f"{'  ' * (indent+1)}column: {node.column_name}")
    elif isinstance(node, ValueNode):
        print(f"{'  ' * (indent+1)}value: {node.value} ({node.value_type})")

print_ast(ast.where_clause)
```

输出：
```
BinaryOpNode
  BinaryOpNode
    ColumnNode
      column: age
    OP: >
    ValueNode
      value: 18 (integer)
  OP: AND
  BinaryOpNode
    ColumnNode
      column: status
    OP: =
    ValueNode
      value: active (string)
```

### 错误处理

解析器提供详细的错误信息，包含行、列位置：

```python
try:
    ast = parse("SELECT * FROM WHERE age > 18")
except ParserError as e:
    print(e)
    # 输出：第 1 行, 列 13: 期望 IDENTIFIER 但得到 WHERE
```

### 实验项目

1. **扩展SQL支持**：
   - 添加`ORDER BY`、`GROUP BY`、`HAVING`
   - 支持`JOIN`（INNER, LEFT）
   - 添加子查询
   - 支持`INSERT ... SELECT`

2. **优化解析器**：
   - 实现预测分析法（LL(1)）减少回溯
   - 添加解析器生成器（如PLY, ANTLR）
   - 性能基准测试

3. **类型检查**：
   - 实现符号表（Symbol Table）记录表结构
   - 类型推断和检查（列是否存在、类型是否匹配）
   - 约束检查（主键、外键、非空）

---

## WAL日志系统 WAL

### 概述

Write-Ahead Logging（WAL）是确保数据库ACID特性的核心机制。其核心原则是：**在数据页修改之前，必须先将修改记录写入日志**。

### WAL协议

```
1. BEGIN TRANSACTION
   → 写入日志：[BEGIN, txn_id]

2. 修改数据页P
   → 内存中修改P（标记为脏）
   → 写入日志：[UPDATE, txn_id, page_id, old_data, new_data]

3. COMMIT
   → 写入日志：[COMMIT, txn_id]
   → 强制刷日志到磁盘（fsync）
   → 之后才能将数据页P写回数据文件（可选延迟）
```

### 崩溃恢复

**两个阶段**：

#### 1. 分析阶段（Analysis）
扫描日志，确定：
- 哪些事务已提交（有COMMIT记录）
- 哪些事务未完成（只有BEGIN，无COMMIT/ROLLBACK）
- 哪些页面需要重做（已提交事务修改的页）
- 哪些页面需要撤销（未提交事务修改的页）

#### 2. 重做/撤销阶段

**重做（Redo）**：
- 对已提交事务的每个UPDATE：
  - 如果数据页的LSN < 日志记录的LSN
  - 则从日志重做（用new_data覆盖）

**撤销（Undo）**：
- 对未提交事务的每个UPDATE：
  - 用old_data回滚数据页
  - 可生成补偿日志（Compensation Log Record, CLR）

### ProjoDB WAL实现（待完成）

**日志记录格式**（建议）：
```cpp
struct LogRecord {
    LSN lsn;              // 日志序列号（单调递增）
    LogType type;         // BEGIN/UPDATE/COMMIT/ROLLBACK/CKPT
    txn_id_t txn_id;      // 事务ID
    page_id_t page_id;    // 影响的页面（UPDATE）
    std::vector<char> old_data;  // 旧数据（UPDATE）
    std::vector<char> new_data;  // 新数据（UPDATE）
    // ... 其他字段
};
```

**WAL类接口**：
```cpp
class WAL {
public:
    WAL(const std::string& log_path);
    ~WAL();

    // 日志操作
    LSN log_begin(txn_id_t txn_id);
    LSN log_update(txn_id_t txn_id, page_id_t page_id,
                   const std::vector<char>& old_data,
                   const std::vector<char>& new_data);
    LSN log_commit(txn_id_t txn_id);
    LSN log_rollback(txn_id_t txn_id);
    LSN log_checkpoint(const CheckpointInfo& info);

    // 恢复
    RecoveryResult recover();

    // 刷日志
    void flush(LSN upto = MAX_LSN);

    // 读取日志（用于恢复或调优）
    LogRecord read_log(LSN lsn);
};
```

### 检查点（Checkpoint）

定期创建检查点，减少恢复时间：
- 将内存中的脏页信息写入日志
- 记录活跃事务列表
- 持久化后清空旧日志（归档或删除）

**检查点记录**：
```cpp
struct CheckpointRecord {
    std::vector<txn_id_t> active_txns;  // 活跃事务
    std::vector<DirtyPage> dirty_pages; // 脏页列表
    uint64_t log_seq;                   // 日志序列号
};
```

### 实验项目

1. **基础WAL实现**：
   - 实现日志文件顺序写入
   - 实现日志刷盘（fsync）
   - 支持BEGIN/UPDATE/COMMIT三种记录

2. **恢复算法**：
   - 实现分析阶段（扫描日志，构建事务表和脏页表）
   - 实现重做（Redo）阶段
   - 实现撤销（Undo）阶段（可选）

3. **性能优化**：
   - 日志组提交（Group Commit）
   - 日志缓冲（减少fsync频率）
   - 异步日志写入

4. **高级功能**：
   - 逻辑日志（Logical Logging）vs 物理日志
   - 影子页（Shadow Paging）与WAL对比
   - 逻辑 undo（如INSERT的UNDO是DELETE）

---

## B+树索引 B+ Tree Index

### 概述

B+树是数据库中最常用的索引结构，支持高效的点查询、范围查询和有序遍历。ProjoDB将实现一个可持久化的B+树，存储在数据页中。

### B+树特性

- **平衡**：所有叶子节点在同一层，保证O(log n)查询
- **高扇出**：内部节点有大量子节点（通常100+），树高度低（4层可存TB数据）
- **面向磁盘**：节点大小为页（4KB），一次I/O读取一个节点
- **叶子节点链表**：所有叶子节点通过指针连接，支持高效范围扫描

### 节点结构

```
内部节点（非叶子）
┌──────────────────────────────────────────┐
│ Header:                                │
│   - node_type (INTERNAL)               │
│   - num_keys                           │
│   - parent_page_id (可选)              │
├──────────────────────────────────────────┤
│ Keys[0]   Keys[1]   ...   Keys[n-1]    │
│ Pointers[0] Pointers[1] ... Pointers[n]│  pointers = keys + 1
└──────────────────────────────────────────┘

叶子节点
┌──────────────────────────────────────────┐
│ Header:                                │
│   - node_type (LEAF)                   │
│   - num_keys                           │
│   - next_leaf_page_id                  │
│   - parent_page_id                     │
├──────────────────────────────────────────┤
│ Keys[0]   Keys[1]   ...   Keys[n-1]    │
│ Values[0] Values[1] ... Values[n-1]    │  (Values可以是record_id或数据)
└──────────────────────────────────────────┘
```

**示例**（4阶B+树，页大小4KB，键8字节，指针8字节）：
- 内部节点：可容纳约 (4096 - 32) / (8+8) ≈ 255 个键
- 叶子节点：可容纳约 (4096 - 32) / (8+8) ≈ 255 条记录

### 核心操作

#### 搜索（Search）
```cpp
// 从根节点开始
node = read_page(root_id);
while (node.type != LEAF) {
    // 在内部节点中找到合适的分支
    i = find_key_position(key, node.keys);
    node = read_page(node.pointers[i]);
}
// 在叶子节点中查找
return linear_or_binary_search(key, node.keys, node.values);
```

#### 插入（Insert）
```cpp
// 1. 找到叶子节点L
L = find_leaf(key);

// 2. 如果L未满，直接插入
if (L.num_keys < ORDER - 1) {
    insert_into_leaf(L, key, value);
    write_page(L);
    return;
}

// 3. L已满，分裂成L和新节点L'
L' = create_leaf();
split_leaf(L, L');  // 移动一半键值对到L'

// 4. 将L'的最小键上推到父节点
parent = L.parent;
insert_into_internal(parent, L'.min_key, L'.page_id);

// 5. 如果父节点也满，递归分裂
```

**分裂策略**：将节点一半数据移动到新节点，中间键上推。

#### 删除（Delete）
```cpp
// 1. 找到叶子节点L
L = find_leaf(key);

// 2. 删除键值对
remove_from_leaf(L, key);

// 3. 如果L至少有ORDER/2个键，完成
if (L.num_keys >= ceil(ORDER/2) - 1) {
    write_page(L);
    return;
}

// 4. 尝试兄弟节点借键
if (borrow_from_left_sibling(L)) return;
if (borrow_from_right_sibling(L)) return;

// 5. 合并兄弟节点
if (has_left_sibling && left_sibling.num_keys < ceil(ORDER/2))
    merge_with_left(L, left_sibling);
else
    merge_with_right(L, right_sibling);

// 6. 如果父节点变空，递归删除父节点
```

### 与存储引擎集成

B+树作为存储引擎之上的一层：
```
StorageEngine ── reads/writes pages ──► B+Tree
   │                                      │
   └───────────── page cache ────────────┘
```

**API设计**：
```python
class BPlusTree:
    def __init__(self, storage_engine, root_page_id=None):
        self.storage = storage_engine
        self.root_id = root_page_id or storage.allocate_index_page()

    def search(self, key) -> Optional[Value]:
        # 递归或迭代查找
        return self._search_from(self.root_id, key)

    def insert(self, key, value):
        # 处理根节点分裂（树高增长）
        result = self._insert_from(self.root_id, key, value)
        if result.new_root:
            old_root = self.root_id
            self.root_id = self.storage.allocate_index_page()
            self._make_internal(self.root_id, [result.split_key],
                                [old_root, result.new_page_id])

    def delete(self, key):
        # 处理根节点收缩（树高降低）
        self._delete_from(self.root_id, key)
        # 如果根节点变空，调整树高

    def range_scan(self, low, high):
        # 找到起点，沿叶子链表遍历
        leaf = self._find_leaf(low)
        while leaf and leaf.min_key <= high:
            for k, v in leaf.entries:
                if low <= k <= high:
                    yield k, v
            leaf = self._read_leaf(leaf.next_page_id)
```

### 并发B+树（可选，高级）

多线程环境下需要加锁：
- **锁粒度**：节点级锁（coupling locks）
- **锁协议**：两阶段锁（2PL）
- **优化**：锁耦合（lock coupling）减少锁持有时间

```cpp
// 加锁向下遍历
node = root;
lock_node(node, SHARED);
while (node.type != LEAF) {
    child = choose_child(node, key);
    lock_node(child, SHARED);
    unlock_node(node);
    node = child;
}
// 现在持有叶子节点的共享锁
// 如果是插入/删除，需要升级为排他锁
```

### 实验项目

1. **基础实现**：
   - 实现固定阶（如4阶）B+树
   - 支持插入和点查询
   - 单元测试（插入1000条，随机查询）

2. **删除操作**：
   - 实现删除和合并
   - 处理根节点收缩
   - 边界情况测试

3. **持久化**：
   - 节点与页的映射（page_id ↔ node）
   - 实现节点序列化/反序列化
   - 与`PageAllocator`集成

4. **性能测试**：
   - 插入n条记录，测量时间和空间
   - 测试不同阶数（扇出）的性能
   - 与平衡二叉树（如AVL）对比

5. **优化**（可选）：
   - 批量插入（排序后批量构建）
   - 前缀压缩（key前缀共享）
   - 变长键支持（VARCHAR索引）

---

## 更多模块

更多模块文档正在完善中...

- **事务管理器**（Transaction Manager）
- **查询执行引擎**（Query Execution Engine）
- **锁管理器**（Lock Manager）
- **缓存管理器**（Cache Manager - 可选）

---

**下一步**：继续阅读 [实验指南](tutorials/README.md) 开始动手实验！