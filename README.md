# ProjoDB - 实验性教学数据库管理系统

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](https://python.org)
[![C++](https://img.shields.io/badge/C%2B%2B-17-orange)](https://isocpp.org)

ProjoDB是一个专为教学目的设计的实验性关系型数据库管理系统（RDBMS），旨在帮助学生和研究人员深入理解数据库内部工作原理。通过分模块实现存储引擎、缓冲区管理、WAL日志、B+树索引、SQL解析和查询执行等核心组件，为数据库系统学习提供完整的实践平台。

## 🎯 项目目标

- **教学导向**：代码简洁清晰，注释详尽，适合数据库课程实验和自学
- **模块化设计**：每个核心组件独立实现，便于单独学习和测试
- **实践性强**：提供完整的实验指南，从零开始构建DBMS
- **扩展灵活**：清晰的接口定义，方便学生添加新功能和研究

## 🏗️ 系统架构

ProjoDB采用经典的数据库分层架构，清晰分离关注点：

```
┌─────────────────────────────────────────────────────────────┐
│                    应用层 (Application)                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐    │
│  │   SQL接口   │  │  事务管理   │  │  查询执行引擎  │    │
│  └─────────────┘  └─────────────┘  └─────────────────┘    │
├─────────────────────────────────────────────────────────────┤
│                    处理层 (Processing)                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐    │
│  │   SQL解析器 │  │  查询优化器 │  │  表达式求值器  │    │
│  └─────────────┘  └─────────────┘  └─────────────────┘    │
├─────────────────────────────────────────────────────────────┤
│                  存储管理层 (Storage Mgmt)                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐    │
│  │  B+树索引   │  │   WAL日志   │  │  元数据管理    │    │
│  └─────────────┘  └─────────────┘  └─────────────────┘    │
├─────────────────────────────────────────────────────────────┤
│                  缓冲与物理存储 (Buffer & Disk)             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              LRU缓冲区池 (Buffer Pool)               │  │
│  └───────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              物理存储 (File Manager)                 │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 📁 项目结构

```
projo/
├── README.md                 # 项目说明（本文件）
├── LICENSE                  # 许可证
├── requirements.txt        # Python依赖
├── Makefile               # C++构建配置
├── config.py              # 项目配置
│
├── docs/                  # 文档目录
│   ├── DATABASE_DESIGN.md     # 详细设计方案
│   ├── STORAGE_ENGINE.md      # 存储引擎设计文档
│   ├── README.md              # 文档索引
│   ├── modules/               # 核心模块说明
│   │   ├── storage.md         # 存储引擎详解
│   │   ├── buffer.md          # 缓冲区池详解
│   │   ├── wal.md             # WAL日志系统详解
│   │   ├── parser.md          # SQL解析器详解
│   │   ├── executor.md        # 查询执行引擎详解
│   │   ├── transaction.md     # 事务管理器详解
│   │   └── index.md           # B+树索引详解
│   ├── tutorials/             # 实验教程
│   │   ├── README.md          # 实验指南索引
│   │   ├── exp1_buffer.md     # 实验1：缓冲区分析
│   │   ├── exp2_allocator.md  # 实验2：页分配器
│   │   ├── exp3_bptree.md     # 实验3：B+树实现
│   │   ├── exp4_wal.md        # 实验4：WAL日志
│   │   └── exp5_transaction.md # 实验5：事务管理
│   ├── api/                   # API参考
│   │   └── README.md          # API文档
│   └── extensions/            # 扩展项目建议
│       └── README.md
│
├── src/                     # 源代码目录
│   ├── core/               # C++核心组件
│   │   ├── buffer.py         # Python实现的缓冲区池
│   │   ├── storage_interface.py # 存储接口定义
│   │   ├── storage_engine.cpp/.h # 存储引擎实现
│   │   ├── file_manager.cpp/.h   # 文件管理
│   │   ├── page_allocator.cpp/.h # 页分配器
│   │   ├── page.cpp/.h          # 页面抽象
│   │   ├── wal.cpp/.h           # WAL日志
│   │   └── transaction.cpp/.h   # 事务管理
│   ├── parser/              # SQL解析器（Python）
│   │   ├── tokenizer.py     # 词法分析
│   │   ├── parser.py        # 语法分析
│   │   └── ast.py           # 抽象语法树
│   ├── executor/            # 查询执行引擎（Python）
│   │   ├── executor.py      # 执行器主类
│   │   ├── context.py       # 执行上下文
│   │   ├── plan.py          # 查询计划
│   │   ├── evaluator.py     # 表达式求值
│   │   └── table_manager.py # 表管理器
│   ├── index/               # B+树索引（Python）
│   │   ├── bplus_tree.py    # B+树实现
│   │   ├── bplus_node.py    # B+树节点
│   │   ├── iterator.py      # 迭代器
│   │   └── serializer.py    # 序列化
│   └── include/             # C++头文件
│       ├── storage_engine.h
│       ├── file_manager.h
│       ├── page_allocator.h
│       ├── page.h
│       ├── wal.h
│       └── transaction.h
│
├── tests/                  # 测试目录
│   ├── test_buffer.py
│   ├── test_storage.py
│   ├── test_wal.py
│   ├── test_bplus_tree.py
│   ├── parser/
│   │   └── test_sql_parser.py
│   └── executor/
│       └── test_executor_integration.py
│
├── examples/               # 示例程序
│   ├── demo_buffer.py
│   ├── demo_parser.py
│   ├── demo_storage.py
│   └── demo_wal.py
│
├── data/                   # 运行时数据文件（自动生成）
├── experiments/            # 实验脚本
├── build/                 # 构建输出（自动生成）
└── .tasks/                # 任务跟踪
```

## 🚀 快速开始

### 环境要求

- **操作系统**：Linux, macOS, Windows (WSL)
- **Python**：3.8+（用于解析器、执行器和测试）
- **C++编译器**：支持C++17标准
  - GCC 7+ 或 Clang 5+
  - 或 MSVC 2017+ (Windows)
- **CMake**：3.10+（可选，用于构建C++部分）
- **Make**：GNU Make 3.81+
- **Git**：版本控制

### 克隆与安装

```bash
# 1. 克隆项目
git clone <repository-url>
cd projo

# 2. 安装Python依赖
pip install -r requirements.txt

# 3. 构建C++核心库（可选，部分功能可用纯Python）
make build
```

### 快速验证

```bash
# 运行Python示例
python examples/demo_storage.py
python examples/demo_buffer.py
python examples/demo_parser.py

# 运行单元测试
pytest tests/ -v

# 或使用Make
make test
```

### 编译C++模块（可选）

```bash
# 构建静态库
make build
# 生成 libdb_storage.a

# 运行C++测试
make test
# 构建并运行 test_storage

# 清理
make clean
```

## 📚 核心模块说明

ProjoDB由以下核心模块组成，每个模块都可以独立学习和实验：

### 1. 存储引擎 (Storage Engine)

**位置**：`src/core/storage_engine.cpp`

**功能**：
- 数据库文件的创建、打开、关闭
- 页面的分配、读取、写入、释放
- 统一的存储抽象接口
- 页类型管理（数据页、索引页、元数据页）

**关键类**：
- `StorageEngine`：主存储引擎类
- `Page`：页面抽象，包含数据和元信息
- `PageAllocator`：页分配器，管理空闲页
- `FileManager`：文件I/O管理

**学习要点**：
- 页式存储结构设计
- 文件映射和扩展策略
- 页分配算法（位图、空闲链表）
- 异常安全和资源管理（RAII）

**更多内容**：详见 [docs/modules/storage.md](docs/modules/storage.md)

---

### 2. LRU缓冲区池 (Buffer Pool)

**位置**：`src/core/buffer.py`

**功能**：
- 管理固定数量的缓冲区帧
- LRU页面置换算法
- 脏页识别和写回
- 页面钉住机制（Pin/Unpin）
- 线程安全访问
- 性能统计收集

**关键类**：
- `BufferPool`：缓冲区管理器
- `BufferFrame`：单个缓冲区帧

**核心算法**：
```python
def _find_victim_frame(self):
    """LRU：选择最久未使用的空闲帧"""
    for frame_id in self.lru_list:  # 从尾部开始（最旧）
        frame = self.frames[frame_id]
        if not frame.is_pinned():
            return frame
    return None
```

**性能指标**：
- 缓存命中率
- 磁盘读写次数
- 页面置换次数
- 脏页写回次数

**学习要点**：
- LRU链表维护和更新策略
- 脏页写回时机和策略
- Pin/Unpin机制防止页面被意外驱逐
- 并发控制和锁粒度
- 性能分析和调优

**更多内容**：详见 [docs/modules/buffer.md](docs/modules/buffer.md)

---

### 3. SQL解析器 (SQL Parser)

**位置**：`src/parser/parser.py`

**功能**：
- 词法分析（Tokenizer）：将SQL字符串分解为Token流
- 语法分析（递归下降）：构建抽象语法树（AST）
- 支持DDL和DML子集

**支持的SQL语句**：
```sql
-- DDL
CREATE TABLE table_name (col1 type1, col2 type2, ...);
DROP TABLE table_name;

-- DML
SELECT cols FROM table [WHERE condition];
INSERT INTO table [(cols)] VALUES (vals);
UPDATE table SET col=val, ... [WHERE condition];
DELETE FROM table [WHERE condition];

-- 事务
BEGIN;
COMMIT;
ROLLBACK;
```

**WHERE条件支持**：
- 比较运算符：`=, !=, <, <=, >, >=`
- 逻辑运算符：`AND, OR, NOT`
- 列名和常量

**AST节点类型**：
- `CreateTableNode`, `DropTableNode`
- `SelectNode`, `InsertNode`, `UpdateNode`, `DeleteNode`
- `BeginNode`, `CommitNode`, `RollbackNode`
- `BinaryOpNode`, `ColumnNode`, `ValueNode`

**学习要点**：
- 词法分析器设计（正则表达式、状态机）
- 递归下降语法分析
- 错误处理和位置报告
- AST设计模式和遍历
- SQL语法的BNF描述

**更多内容**：详见 [docs/modules/parser.md](docs/modules/parser.md)

---

### 4. WAL日志系统 (WAL)

**位置**：`src/core/wal.cpp`（待实现）, `src/core/wal.py`（参考实现）

**功能**：
- 实现Write-Ahead Logging协议
- 日志记录格式和序列化
- 日志文件管理和检查点
- 崩溃恢复机制（ARIES简化版）

**WAL协议核心**：
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

**日志记录类型**：
- `BEGIN`：事务开始
- `UPDATE`：数据修改（包含前后镜像）
- `COMMIT`：事务提交
- `ROLLBACK`：事务回滚
- `CHECKPOINT`：检查点

**恢复算法**：
1. **分析阶段**：扫描日志，确定已提交和未完成事务
2. **重做阶段**：重做已提交事务的所有修改
3. **撤销阶段**：回滚未提交事务的修改

**学习要点**：
- 预写日志原理和协议
- 日志记录结构设计
- 检查点机制减少恢复时间
- 崩溃恢复的三阶段算法
- 日志文件管理和轮转

**更多内容**：详见 [docs/modules/wal.md](docs/modules/wal.md)

---

### 5. B+树索引 (B+ Tree Index)

**位置**：`src/index/bplus_tree.py`

**功能**：
- B+树数据结构实现
- 键值对存储和高效搜索
- 插入、删除操作（含分裂和合并）
- 范围查询支持
- 与存储引擎集成

**B+树特性**：
- **平衡**：所有叶子节点在同一层，保证O(log n)查询
- **高扇出**：内部节点有大量子节点，树高度低
- **面向磁盘**：节点大小为页（4KB），一次I/O读取一个节点
- **叶子节点链表**：支持高效范围扫描

**节点结构**：
```
内部节点：
  Keys:  [k1, k2, k3, ...]
  Pointers: [p0, p1, p2, ...]  (keys + 1个指针)

叶子节点：
  Keys:  [k1, k2, k3, ...]
  Values: [v1, v2, v3, ...]  (记录位置)
  next_page: 链表指针
```

**关键操作**：
- **搜索**：从根节点 descend，在叶子节点二分查找
- **插入**：找到叶子，如果满则分裂，中间键上推
- **删除**：找到叶子，删除键，如果太少则合并或借键

**学习要点**：
- B+树节点布局和填充因子
- 插入分裂算法（递归处理）
- 删除合并/借键算法
- 与页式存储的集成
- 范围查询实现
- 并发B+树（可选，高级）

**更多内容**：详见 [docs/modules/index.md](docs/modules/index.md)

---

### 6. 查询执行引擎 (Query Executor)

**位置**：`src/executor/executor.py`

**功能**：
- 执行物理查询计划
- 火山模型迭代器（Iterator Model）
- 运算符实现：表扫描、选择、投影、连接等
- 表达式求值
- 与事务和存储层交互

**运算符（Operators）**：
- `SeqScanOperator`：全表扫描
- `IndexScanOperator`：索引扫描
- `FilterOperator`：WHERE条件过滤
- `ProjectOperator`：投影（选择列）
- `JoinOperator`：连接操作（嵌套循环）

**执行流程**：
```
SQL → Parser → AST → Optimizer → 物理计划 → Executor → 结果集
```

**火山模型**：
每个运算符实现`open()`、`next()`、`close()`接口，以迭代方式产生元组。

```python
class Operator:
    def open(self): pass
    def next(self) -> Optional[Tuple]: pass
    def close(self): pass
```

**学习要点**：
- 迭代器模式和流水线执行
- 物理算子设计和实现
- 表达式求值器
- 查询计划和优化
- 内存管理和流水线

**更多内容**：详见 [docs/modules/executor.md](docs/modules/executor.md)

---

### 7. 事务管理器 (Transaction Manager)

**位置**：`src/core/transaction.cpp`

**功能**：
- 事务生命周期管理：BEGIN, COMMIT, ROLLBACK
- 并发控制：两阶段锁（2PL）
- 锁类型：共享锁（S）和排他锁（X）
- 死锁检测和预防
- 隔离级别：Read Committed, Repeatable Read

**锁协议**：严格两阶段锁（Strict 2PL）
-  growing phase：可以获取锁，不能释放
- shrinking phase：可以释放锁，不能获取
- 所有锁在COMMIT/ROLLBACK时一次性释放

**事务状态机**：
```
     ┌──────────┐
     │  ACTIVE  │───COMMIT──▶ COMMITTED
     └──────────┘            │
         │                  ▼
         │              (持久化)
         │                  │
         │             ┌────┴───┐
         │             │ RECOVERY│
         │             └────┬───┘
         │                  │
         ▼                  ▼
     ABORTED ◀──ROLLBACK──┘
```

**学习要点**：
- ACID特性实现
- 锁管理器和锁表
- 两阶段锁协议（2PL）
- 死锁检测（等待图）和死锁预防（时间戳）
- 隔离级别与锁的对应关系
- WAL与事务的协同

**更多内容**：详见 [docs/modules/transaction.md](docs/modules/transaction.md)

---

## 🔧 实验指南

我们提供了一系列逐步实验，帮助你从零开始构建和深入理解ProjoDB。每个实验都有明确的目标、步骤和验证方法。

### 实验列表

1. **[实验1：缓冲区池性能分析](docs/tutorials/exp1_buffer.md)**
   - 理解LRU算法工作原理
   - 测量不同工作负载下的缓存命中率
   - 分析帧数、不同置换算法的影响

2. **[实验2：页位图分配器](docs/tutorials/exp2_allocator.md)**
   - 从零实现页分配器
   - 学习位图数据结构
   - 测量分配和释放性能

3. **[实验3：B+树索引实现](docs/tutorials/exp3_bptree.md)**
   - 实现B+树的插入、搜索、删除
   - 理解平衡树结构和分裂/合并算法
   - 测试范围查询和性能

4. **[实验4：WAL预写日志](docs/tutorials/exp4_wal.md)**
   - 实现Write-Ahead Logging
   - 学习崩溃恢复算法
   - 测试原子性和持久性保证

5. **[实验5：事务管理](docs/tutorials/exp5_transaction.md)**
   - 实现ACID特性
   - 构建锁管理器
   - 处理死锁和并发冲突

**开始实验**：从 [实验指南总览](docs/tutorials/README.md) 开始

---

## 📖 使用示例

### 示例1：使用存储引擎

```python
from src.core.storage_interface import SimpleFileStorage

# 创建/打开数据库文件
storage = SimpleFileStorage("mydb.dat", page_size=4096)

# 分配数据页
page_id = storage.allocate_page()

# 读取页面
data = storage.page_read(page_id)
print(f"Page {page_id} size: {len(data)} bytes")

# 写入页面
new_data = b"x" * 4096
storage.page_write(page_id, new_data)

storage.close()
```

### 示例2：使用LRU缓冲区池

```python
from src.core.buffer import BufferPool
from src.core.storage_interface import SimpleFileStorage

# 初始化存储引擎和缓冲区
storage = SimpleFileStorage("test.db", 4096)
buffer = BufferPool(num_frames=100, storage_engine=storage)

# 读取页面（自动缓存管理）
frame = buffer.read_page(page_id=0)
# 修改数据
frame.data[0:5] = b"Hello"
# 标记脏页
buffer.mark_dirty(page_id=0)

# 强制写回
buffer.flush_page(page_id=0)

# 查看统计信息
stats = buffer.get_buffer_stats()
print(f"命中率: {stats['hit_rate']:.2%}")

# 优雅关闭
buffer.shutdown()
```

### 示例3：SQL解析

```python
from src.parser import parse

# 解析SQL
sql = "SELECT name, age FROM users WHERE age > 18 AND status = 'active'"
ast = parse(sql)

# 查看AST
print(f"语句类型: {type(ast).__name__}")
print(f"表名: {ast.table_name}")
print(f"查询列: {ast.columns}")
print(f"WHERE条件: {ast.where_clause}")

# 遍历表达式树
def print_expr(node, indent=0):
    prefix = "  " * indent
    if isinstance(node, BinaryOpNode):
        print(f"{prefix}BinaryOp: {node.op}")
        print_expr(node.left, indent+1)
        print_expr(node.right, indent+1)
    elif isinstance(node, ColumnNode):
        print(f"{prefix}Column: {node.column_name}")
    elif isinstance(node, ValueNode):
        print(f"{prefix}Value: {node.value} ({node.value_type})")

if ast.where_clause:
    print_expr(ast.where_clause)
```

### 示例4：B+树索引使用

```python
from src.index.bplus_tree import BPlusTree
from src.core.storage_interface import InMemoryStorage

# 创建存储和B+树
storage = InMemoryStorage(page_size=4096)
bptree = BPlusTree(storage, order=32)  # 32阶

# 插入键值对
bptree.insert(100, "record_id_100")
bptree.insert(200, "record_id_200")
bptree.insert(150, "record_id_150")

# 点查询
result = bptree.search(150)
print(f"150 -> {result}")

# 范围查询
print("范围 [100, 200):")
for key, value in bptree.range_scan(100, 200):
    print(f"  {key}: {value}")

# 删除
bptree.delete(150)
```

---

## 🧪 测试

### 运行所有测试

```bash
# 使用pytest
pytest tests/ -v

# 或直接运行
python -m pytest tests/test_buffer.py
python -m pytest tests/test_wal.py
python -m pytest tests/parser/test_sql_parser.py
```

### 运行特定模块测试

```bash
# 测试缓冲区
pytest tests/test_buffer.py -v

# 测试B+树
pytest tests/test_bplus_tree.py -v

# 测试解析器
pytest tests/parser/ -v
```

### 性能基准测试

```bash
# 缓冲区性能
python experiments/benchmark_buffer.py --frames 100 --workload random

# B+树性能
python experiments/benchmark_bptree.py --keys 10000
```

---

## 📊 当前开发状态

| 模块 | 状态 | 说明 |
|------|------|------|
| 存储引擎（C++） | ✅ 完成 | `storage_engine.cpp`, `file_manager.cpp`, `page_allocator.cpp` |
| 页面抽象（C++） | ✅ 完成 | `page.cpp`, `page.h` |
| 缓冲区池（Python） | ✅ 完成 | `buffer.py` 完整实现 |
| SQL解析器 | ✅ 完成 | `tokenizer.py`, `parser.py`, `ast.py` |
| WAL日志 | ✅ 完成 | `wal.cpp` (C++), `wal.py` (Python参考) |
| 事务管理 | ✅ 完成 | `transaction.cpp` 核心功能 |
| B+树索引 | ⚠️ 部分 | `bplus_tree.py` 基础实现，需完善持久化 |
| 查询执行器 | ⚠️ 部分 | `executor/` 目录结构存在，需完整实现 |
| 主程序集成 | ❌ 未开始 | 需要CLI接口和系统集成 |

**可运行状态**：可以使用Python API完成存储、缓冲、解析等核心功能。B+树和查询执行器需要进一步完善才能支持完整的SQL执行。

---

## 🤝 贡献指南

欢迎贡献代码、文档或提出问题！

### 如何贡献

1. **报告Bug**：在GitHub Issues中描述问题，提供复现步骤
2. **提出新功能**：在Discussions或Issues中讨论
3. **提交Pull Request**：
   - Fork项目
   - 创建功能分支
   - 提交代码（遵循现有风格）
   - 添加测试
   - 创建PR并描述改动

### 代码规范

- Python：遵循PEP 8，使用type hints
- C++：使用C++17，`clang-format`格式化
- 提交信息：清晰描述改动原因和内容
- 文档：更新相关文档

---

## 📚 参考资料

### 教材
- **《数据库系统实现》**（Garcia-Molina, Ullman, Widom）- 经典教材
- **《数据库系统内幕》**（SQLite作者）- 实战导向
- **《数据库系统概念》**（Silberschatz）- 全面系统

### 开源DBMS参考
- **SQLite**：https://github.com/sqlite/sqlite
- **PostgreSQL**：https://github.com/postgres/postgres
- **TinyDB**：https://github.com/jamiehannaford/tiny-db

### 学术资源
- CMU 15-445/645 Database Systems课程：https://15445.courses.cs.cmu.edu/
- MIT 6.824 Distributed Systems：https://pdos.csail.mit.edu/6.824/

---

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

---

## 📞 联系方式

- **Issues**：https://github.com/your-repo/issues
- ** Discussions**：https://github.com/your-repo/discussions
- **邮件**：your-email@example.com

---

**开始学习**：请阅读 [实验指南](docs/tutorials/README.md) 或 [模块文档](docs/modules/README.md)

**祝你探索愉快！数据库系统的奥秘等待你去发现。** ✨
