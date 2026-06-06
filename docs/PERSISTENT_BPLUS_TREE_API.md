# 持久化B+树索引 API 文档

## 概述

PersistentBPlusTree 提供基于磁盘的B+树索引实现，集成LRU缓冲区管理器，支持大数据集的持久化存储。

## 核心类

### `PersistentBPlusTree`

持久化B+树主类，提供CRUD和范围查询操作。

#### 构造函数

```python
PersistentBPlusTree(buffer_pool, order: int = 4, root_page_id: int = 0)
```

**参数：**
- `buffer_pool`: BufferPool实例，提供页面缓存和I/O
- `order`: B+树阶数（默认4），决定节点最大键数
- `root_page_id`: 根节点页面ID，0表示新建树，非0表示打开现有索引

#### 主要方法

##### `insert(key, value) -> bool`

插入键值对。

**参数：**
- `key`: 索引键（支持int、短字符串≤4字节）
- `value`: 值，格式为 `(page_id, slot_id)` 元组，指向数据记录

**返回：** True成功，False失败（如重复键则更新值并返回True）

**特性：**
- 自动处理节点分裂
- 支持重复键更新
- 持久化写回

##### `search(key) -> Optional[Any]`

点查询：查找键对应的值。

**返回：** 值或None（键不存在）

##### `range_search(start_key, end_key) -> List[Tuple]`

范围查询：返回[start_key, end_key]范围内的所有键值对。

**返回：** `[(key1, value1), (key2, value2), ...]` 列表

**特性：**
- 包含起始和结束键
- 利用叶子节点链表高效遍历
- 键按升序排列

##### `delete(key) -> bool`

删除键（当前暂停开发，MVP不包含此功能）。

##### `shutdown()`

优雅关闭：写回所有缓存节点，释放资源。**必须在使用后调用。**

#### 其他方法（内部使用）

- `_load_node(page_id)`: 加载节点
- `_flush_node(node)`: 写回节点
- `_allocate_page_for_node()`: 分配新页面
- `_free_page(page_id)`: 释放页面（简化实现）

## 使用示例

### 基本使用（新建索引）

```python
from src.core.buffer import BufferPool
from src.core.storage_interface import InMemoryStorage
from src.index.serializer import PersistentBPlusTree

# 1. 初始化存储和缓冲区
storage = InMemoryStorage(page_size=4096)
buffer = BufferPool(num_frames=50, storage_engine=storage)

# 2. 创建持久化B+树
tree = PersistentBPlusTree(buffer_pool=buffer, order=4)

# 3. 插入数据
tree.insert(10, (100, 0))   # 键10 → 记录位于page 100, slot 0
tree.insert(20, (101, 0))
tree.insert(15, (102, 0))

# 4. 查询
value = tree.search(10)     # 返回 (100, 0)
results = tree.range_search(10, 20)  # 返回 [(10,(100,0)), (15,(102,0)), (20,(101,0))]

# 5. 关闭（重要！）
tree.shutdown()
```

### 打开现有索引

```python
# 使用相同配置打开已持久化的索引
tree2 = PersistentBPlusTree(buffer_pool=buffer, order=4, root_page_id=tree.root_page_id)

# 查询刚插入的数据
assert tree2.search(10) == (100, 0)
tree2.shutdown()
```

### 与文件存储结合

```python
from src.core.storage_interface import SimpleFileStorage

# 使用文件持久化存储
storage = SimpleFileStorage("mydb.idx", page_size=4096)
buffer = BufferPool(num_frames=100, storage_engine=storage)
tree = PersistentBPlusTree(buffer_pool=buffer, order=4)

# ... 操作 ...

tree.shutdown()
storage.close()
```

## 序列化格式

每个B+树节点存储在单个4096字节页面中，布局如下：

```
┌─────────────────────────────────────────────┐
│  Header (固定15字节)                        │
│  - magic: 0xBADF00D (4 bytes)              │
│  - node_type: 1=INTERNAL, 2=LEAF (1 byte) │
│  - key_count (2 bytes)                      │
│  - parent_id (4 bytes)                      │
│  - reserved (4 bytes)                       │
├─────────────────────────────────────────────┤
│  Keys (固定8字节/键)                        │
│  支持 int64 或 短字符串(≤4字符)             │
├─────────────────────────────────────────────┤
│  Values 或 Children                         │
│  • LEAF: 值(record_id, 8字节/条) +         │
│          next_leaf_page_id (4字节)         │
│  • INTERNAL: 子节点page_id (4字节/个)      │
└─────────────────────────────────────────────┘
```

## 设计约束

1. **键类型**: 仅支持 `int` 和长度≤4的 `str`（简化教学）
2. **值格式**: 推荐 `(page_id, slot_id)` 元组，编码为8字节
3. **页面大小**: 固定4096字节，与BufferPool同步
4. **节点缓存**: 加载的节点缓存在 `tree.node_cache` 中，`shutdown()` 前需写回

## 与内存B+树的对比

| 特性 | BPlusTree (内存) | PersistentBPlusTree |
|------|------------------|---------------------|
| 存储 | 纯内存 | 持久化文件 |
| 数据丢失 | 程序退出丢失 | 程序退出保留 |
| 适合场景 | 小型数据集 | 大型数据集 |
| 性能 | 极快 | 受I/O影响 |
| API | 几乎相同 | 类似 |

**关键差异：**
1. `PersistentBPlusTree` 需要传入 `buffer_pool`
2. 根节点通过 `root_page_id` 标识而非对象引用
3. 值应为可持久化的格式（如 `(page_id, slot_id)`）

## 测试

运行测试：

```bash
pytest tests/test_persistent_bplus_tree.py -v
```

**当前状态（2025-06-05）：**
- ✅ 基本功能测试：7/7 通过
  - 单插入
  - 多插入
  - 重复键更新
  - 顺序插入（触发分裂）
  - 随机插入
  - 范围查询
  - 优雅关闭
- ⏸ 删除功能暂停开发（MVP不包含）

## 接口对齐说明

本实现与 `index_manager` 的接口对齐情况：

| 方法 | 参数 | 返回值 | 状态 |
|------|------|--------|------|
| `search(key)` | key: Any | Optional[Any] | ✅ 对齐 |
| `range_search(start_key, end_key)` | start, end: Any | List[Tuple] | ✅ 对齐（返回元组列表而非IndexEntry对象，但语义相同） |

## 注意事项

1. **线程安全**: 当前实现**非线程安全**，多线程需外部同步
2. **关闭必须**: 使用后必须调用 `shutdown()` 确保数据持久化
3. **页面回收**: `_free_page()` 为简化实现，真实场景需维护空闲列表
4. **父指针重建**: 节点加载时 `parent` 指针可能为None，通过 `_reconnect_children()` 重建

## 后续扩展（非MVP）

- 删除操作（节点合并、页面回收）
- 与WAL集成支持事务
- 变长键/值支持
- 并发控制
- 检查点机制