# B+树索引模块详解

## 目录
- [概述](#概述)
- [B+树结构](#b树结构)
  - [节点类型](#节点类型)
  - [键存储顺序](#键存储顺序)
- [核心操作](#核心操作)
  - [搜索](#搜索)
  - [插入](#插入)
  - [删除](#删除)
  - [范围查询](#范围查询)
- [与存储引擎集成](#与存储引擎集成)
- [序列化与持久化](#序列化与持久化)
- [并发访问](#并发访问)
- [实验项目](#实验项目)
- [常见问题](#常见问题)

---

## 概述

B+树是数据库中最常用的索引结构，支持高效的点查询（O(log n)）和范围查询。ProjoDB实现了一个可持久化的B+树，数据存储在数据页中。

### 为什么用B+树？

- **平衡**：所有叶子节点在同一层，查询性能稳定
- **高扇出**：内部节点可存储大量键（如256-1000），树高度低（4层可存TB数据）
- **面向磁盘**：节点大小等于页（4KB），一次I/O读一个节点
- **范围查询**：叶子节点链表连接，高效扫描区间

### 关键参数

- **阶数（order）**：每个内部节点的最大子节点数。通常选择使节点填满一页：
  ```
  order = (page_size - header_size) / (key_size + pointer_size)
  ```
  假设4KB页，8字节键+8字节指针 → order ≈ 250

- **填充因子**：插入时节点保持的最小填充比例（如50%），避免过早分裂

---

## B+树结构

### 节点类型

#### 内部节点（Internal Node）

```
┌─────────────────────────────────────────────┐
│ Header: node_type=INTERNAL, num_keys       │
├─────────────────────────────────────────────┤
│ Keys:      [k1,  k2,  k3, ... k(m-1)]     │
│ Pointers:  [p1, p2, p3, ... p(m)]         │  ← keys + 1个指针
│            (page_id或偏移)                 │
└─────────────────────────────────────────────┘
```

**搜索规则**：对于键k，找到第一个`k_i >= k`，取`p_i`。如果所有键都`< k`，取最后一个指针`p_m`。

**示例**：
```
Keys:    [10, 20, 30]
Ptrs:    [p0, p1, p2, p3]
如果k=15: 10 < 15 < 20 → 取p1
如果k=5:   5 < 10 → 取p0
如果k=35: 35 > 30 → 取p3
```

---

#### 叶子节点（Leaf Node）

```
┌─────────────────────────────────────────────┐
│ Header: node_type=LEAF, num_keys, next_page│
├─────────────────────────────────────────────┤
│ Keys:      [k1,  k2,  k3, ... k(m)]       │
│ Values:    [v1,  v2,  v3, ... v(m)]       │  (record_id或数据指针)
└─────────────────────────────────────────────┘
```

**next_page**：指向下一个叶子节点，支持范围扫描。

**示例**：
```
Keys:    [10, 20, 30]
Vals:    [rec1, rec2, rec3]
next_page → 下一个叶子页
```

---

### 键存储顺序

**严格升序**：`k1 < k2 < k3 < ...`

**允许重复键吗？**
- **主键索引**：不允许重复（唯一性约束）
- **辅助索引**：允许重复（多个记录有相同键），处理方式：
  - 叶子节点存储多条值
  - 键+record_id复合键（保证唯一）

**ProjoDB简化**：假设键唯一（主键索引）。

---

## 核心操作

### 搜索

#### 算法（递归）

```python
def search(self, key) -> Optional[Value]:
    """在根page_id开始搜索"""
    return self._search_from(self.root_id, key)

def _search_from(self, page_id: int, key) -> Optional[Value]:
    # 1. 读取节点（从存储引擎）
    node = self._read_node(page_id)

    # 2. 如果是内部节点，找到子节点递归搜索
    if node.node_type == INTERNAL:
        child_idx = self._find_child_index(node, key)
        child_page_id = node.pointers[child_idx]
        return self._search_from(child_page_id, key)

    # 3. 如果是叶子节点，二分查找
    else:
        idx = bisect_left(node.keys, key)
        if idx < len(node.keys) and node.keys[idx] == key:
            return node.values[idx]
        else:
            return None
```

**复杂度**：O(log n) I/O（高度次磁盘访问）

---

### 插入

#### 算法步骤

```
1. 找到目标叶子节点L
2. 如果L未满（num_keys < order - 1）：
     直接插入到keys/values适当位置
     写回L
     完成
3. 如果L已满：
     分裂成L和L_new（各保留约一半数据）
     中间键k_mid上提到父节点
     如果父节点也满，递归分裂
     如果根节点分裂，树高+1
```

#### 分裂详细

**分裂前**（order=4，已满3键）：
```
L.keys = [10, 20, 30]
L.values = [v10, v20, v30]
```

**分裂后**（偶数+1，选择上推第2个）：
```
L保留： [10, 20]    新的： [30]
      [v10, v20]           [v30]

上推的键：20（或30？通常上推右节点的第一个键）
```

**父节点插入**：
```
原父： [k] → [ptr_left]
新： [k_left, k_mid] → [ptr_left, ptr_right]
```

**注意**：上推的键不存储在分裂的叶子节点中（上与不上），而在父节点。

---

### 删除

#### 算法步骤

```
1. 找到包含key的叶子节点L
2. 删除该键值对
3. 如果L仍有至少 ceil(order/2) - 1 个键：
     完成
4. 否则L下溢：
     a) 尝试从左兄弟借键
     b) 尝试从右兄弟借键
     c) 如果兄弟都太满，合并L和其中一个兄弟
        如果合并后父节点也下溢，递归删除父节点
        如果根节点合并后只有一个子节点，树高-1
```

#### 借键（Redistribution）

**从左兄弟借**：

```
左兄弟： [k1, k2, k3]    L: [k4, k5]
操作：
  1. 从左边"借"最后一个键k3到L前面
  2. L变成 [k3, k4, k5]
  3. 左兄弟变为 [k1, k2]
  4. 父节点中指向左兄弟的指针对应的键本应是k4，
     现在要改为k3（因为L的第一个键变了）
```

---

#### 合并（Merge）

**合并L和右兄弟R**：

```
父： ... [k_parent] → [L | R]
合并后：
  new_node.keys = L.keys + [k_parent] + R.keys
  new_node.values = L.values + R.values
  new_node.next_page = R.next_page
  从父节点删除k_parent和有关指针
```

**可能导致父节点下溢**，递归。

---

### 范围查询

#### 算法

```python
def range_scan(self, low_key, high_key) -> Iterator[Tuple[Key, Value]]:
    """
    扫描[low_key, high_key)区间的所有键值对

    Args:
        low_key: 下界（包含），None表示无穷小
        high_key: 上界（不包含），None表示无穷大

    Returns:
        键升序的迭代器
    """
    # 1. 找到起点叶子节点
    leaf = self._find_leaf(low_key if low_key is not None else self._min_key())

    # 2. 沿叶子链表遍历
    while leaf is not None:
        for i, key in enumerate(leaf.keys):
            # 检查是否超出上界
            if high_key is not None and key >= high_key:
                return
            # 检查是否在范围内
            if low_key is None or key >= low_key:
                yield key, leaf.values[i]
        leaf = self._read_leaf(leaf.next_page_id)
```

---

## 与存储引擎集成

### 页分配

B+树节点存储在数据页中，需要分配页：

```python
class BPlusTree:
    def __init__(self, storage_engine, order=32, root_page_id=None):
        self.storage = storage_engine
        self.order = order

        if root_page_id is not None:
            self.root_id = root_page_id
        else:
            # 为新树分配根节点页
            self.root_id = self.storage.allocate_index_page()
```

### 节点读写

节点需要**序列化**到页数据：

```python
def _read_node(self, page_id: int) -> BPlusNode:
    """从存储引擎读取页并反序列化为节点"""
    data = self.storage.page_read(page_id)
    if data is None:
        raise KeyError(f"Page {page_id} not found")
    return BPlusNode.deserialize(data, page_id)

def _write_node(self, node: BPlusNode):
    """序列化节点并写回存储引擎"""
    data = node.serialize()
    self.storage.page_write(node.page_id, data)
```

---

## 序列化与持久化

### 节点序列化格式

**页布局**（剩余空间留给数据）：

```
┌─────────────────────────────────────────────┐
│ B+Tree节点头 (固定32字节)                   │
│  • node_type (1)  INTERNAL=0, LEAF=1       │
│  • num_keys (2)                            │
│  • parent (4)  父节点page_id (可选)         │
│  • next_page (4) 叶子链表                 │
├─────────────────────────────────────────────┤
│ Keys (变长)                                 │
│    [key1_len][key1][key2_len][key2]...    │
├─────────────────────────────────────────────┤
│ Pointers/Values (变长)                      │
│    [ptr1(4)][ptr2(4)]... 或 [val_len+val] │
└─────────────────────────────────────────────┘
```

### Python实现示例

```python
class BPlusNode:
    """B+树节点（内存表示）"""

    def __init__(self, page_id, node_type):
        self.page_id = page_id
        self.node_type = node_type  # INTERNAL or LEAF
        self.keys = []  # List[bytes]
        self.pointers = []  # List[int] (INTERNAL) 或 List[bytes/record_id] (LEAF)
        self.parent = None  # parent page_id
        self.next_leaf = None  # 下一个叶子page_id (LEAF only)

    def is_leaf(self):
        return self.node_type == LEAF

    def serialize(self) -> bytes:
        """序列化为字节"""
        buf = bytearray()
        # 头部
        buf.append(1 if self.is_leaf() else 0)
        buf.extend(len(self.keys).to_bytes(2, 'little'))
        parent_id = self.parent.page_id if self.parent else 0
        buf.extend(parent_id.to_bytes(4, 'little'))
        if self.is_leaf():
            next_id = self.next_leaf.page_id if self.next_leaf else 0
            buf.extend(next_id.to_bytes(4, 'little'))

        # 键列表
        for key in self.keys:
            # 变长编码：len + bytes
            buf.extend(len(key).to_bytes(2, 'little'))
            buf.extend(key)

        # 指针/值列表
        if self.is_leaf():
            for val in self.pointers:  # val是record_id或数据
                if isinstance(val, int):
                    buf.extend(val.to_bytes(4, 'little'))
                else:
                    buf.extend(len(val).to_bytes(2, 'little'))
                    buf.extend(val)
        else:
            for ptr in self.pointers:  # ptr是page_id
                buf.extend(ptr.to_bytes(4, 'little'))

        return bytes(buf)

    @classmethod
    def deserialize(cls, data: bytes, page_id: int) -> 'BPlusNode':
        """从字节反序列化"""
        node = BPlusNode(page_id, LEAF if data[0] == 1 else INTERNAL)
        num_keys = int.from_bytes(data[1:3], 'little')
        node.parent = int.from_bytes(data[3:7], 'little')

        offset = 7
        if node.is_leaf():
            node.next_leaf = int.from_bytes(data[7:11], 'little')
            offset = 11

        # 读取键
        for _ in range(num_keys):
            key_len = int.from_bytes(data[offset:offset+2], 'little')
            offset += 2
            key = data[offset:offset+key_len]
            offset += key_len
            node.keys.append(key)

        # 读取指针/值
        for _ in range(num_keys if node.is_leaf() else num_keys + 1):
            if node.is_leaf():
                # LEAF: record_id (4) 或变长
                # 为了简化，假设固定4字节record_id
                ptr = int.from_bytes(data[offset:offset+4], 'little')
                offset += 4
                node.pointers.append(ptr)
            else:
                ptr = int.from_bytes(data[offset:offset+4], 'little')
                offset += 4
                node.pointers.append(ptr)

        return node
```

---

## 并发访问

### 锁耦合（Lock Coupling）

**问题**：遍历B+树时，如果中途释放当前节点再获取子节点，可能被其他事务修改导致不一致。

**解决方案**：锁耦合
```python
def search_with_locks(self, key):
    # 1. 锁定根节点
    current = self._read_node(self.root_id)
    self.lock_manager.lock_node(current, LockMode.SHARED)

    while not current.is_leaf():
        # 2. 锁定子节点（在释放父节点前）
        child_id = self._choose_child(current, key)
        child = self._read_node(child_id)
        self.lock_manager.lock_node(child, LockMode.SHARED)

        # 3. 释放父节点
        self.lock_manager.unlock_node(current)

        # 4. 移动
        current = child

    # current现在是叶子节点，持有锁
    return current
```

**锁升级**：从S锁升级为X锁需要先释放S锁再获取X锁（危险），或使用** intention locks**。

---

### 乐观并发控制（OCC）

**思路**：不加锁读取，验证期间无冲突再写入。

**步骤**：
1. **读阶段**：无锁读取树
2. **验证阶段**：检查根节点是否变化（或其他事务是否修改）
3. **写阶段**：如果验证通过，加锁并应用修改

适合**读多写少**场景。

---

## 实验项目

### 实验1：实现B+树搜索

**目标**：完成`search()`方法。

**步骤**：
1. 实现`_read_node()`从存储引擎读节点
2. 实现`_find_child_index()`（内部节点）和叶子二分查找
3. 递归搜索直到叶子
4. 测试：插入后能正确查询

**测试**：
```python
tree = BPlusTree(storage, order=4)
tree.insert(10, "value10")
tree.insert(20, "value20")
assert tree.search(10) == "value10"
assert tree.search(30) is None
```

---

### 实验2：实现插入和分裂

**目标**：完成`insert()`方法。

**步骤**：
1. 找到叶子节点L
2. 如果未满，插入并排序
3. 如果满，执行分裂
   - 创建新叶子
   - 搬移一半键值到新叶子
   - 上推中间键到父节点（可能递归）
4. 处理根分裂（树高增长）

**测试**：顺序插入1000个键，验证所有都能搜到。

---

### 实验3：实现删除和合并

**目标**：完成`delete()`方法。

**步骤**：
1. 找到叶子节点L和键的位置
2. 删除键值
3. 检查下溢（`len(keys) < ceil(order/2) - 1`）
4. 尝试借键（左/右兄弟）
5. 否则合并兄弟，并递归删除父节点中的分隔键
6. 检查根节点收缩

**测试**：插入后删除，验证数量匹配。

---

### 实验4：持久化测试

**目标**：验证B+树能正确持久化到磁盘。

**步骤**：
1. 创建B+树并插入数据
2. 关闭并重新打开（从root_page_id恢复）
3. 验证所有数据还在
4. 模拟崩溃（不flush，直接重启）并恢复

```python
tree = BPlusTree(storage, order=32)
for i in range(100):
    tree.insert(i, f"value{i}")
tree.close()  # 或flush

# 重启
tree2 = BPlusTree(storage, order=32, root_page_id=tree.root_id)
for i in range(100):
    assert tree2.search(i) == f"value{i}"
```

---

### 实验5：范围查询性能

**目标**：测试`range_scan()`效率。

**步骤**：
1. 插入有序键：1,2,3,...,10000
2. 扫描区间[5000, 6000)
3. 验证返回1000个结果
4. 测量扫描时间

---

## 常见问题

### Q1: 阶数order如何选择？

**A**：使节点填满一页，最大化扇出，减少树高。
```
order = (page_size - header_size) / (key_size + pointer_size)
```
如果key和pointer都是8字节，header=32B，4KB页 → order ≈ 255。

---

### Q2: 为什么叶子节点备份整个data而不是record_id？

**A**：取决于索引类型：
- **聚集索引（Clustered）**：叶子节点存储完整数据行（如InnoDB主键）
- **非聚集索引（Non-clustered）**：叶子节点存储record_id或行指针（如InnoDB二级索引）

ProjoDB教学实现建议用非聚集索引，叶子存record_id，通过record_id回表查数据。

---

### Q3: 并发插入/删除如何保证一致性？

**A**：
1. **加锁**：插入前对父节点加X锁，防止分裂冲突
2. **原子性**：节点分裂作为原子操作（存储引擎一页写原子？）
3. **LSN或版本号**：节点包含版本，防止ABA问题

简化版：单线程操作，不考虑并发。

---

### Q4: B+树与B树区别？

**A**：
| 特性 | B+树 | B树 |
|------|------|-----|
| 数据存储 | 只在叶子 | 叶子+内部 |
| 叶子链接 | 是（范围扫描） | 否 |
| 扇出 | 更高（内部无数据） | 较低 |
| 查询性能 | 一致（所有路径同长） | 可能更短（数据在内部） |

数据库几乎都用B+树。

---

## 参考代码

- `src/index/bplus_tree.py`：主要实现（约500行）
- `src/index/bplus_node.py`：节点类
- `src/index/serializer.py`：序列化辅助
- `tests/test_bplus_tree.py`：单元测试

---

**下一步**：回到 [主文档](README.md) 或继续 [实验3：B+树索引](docs/tutorials/exp3_bptree.md)
