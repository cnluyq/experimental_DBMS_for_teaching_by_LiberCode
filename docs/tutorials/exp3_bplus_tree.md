# 实验3：B+树索引实现

## 一、实验目标

通过本实验，你将：

1. ✅ **理解B+树结构**：掌握B+树的节点布局、键的排列
2. ✅ **实现核心操作**：完成搜索、插入、删除算法
3. ✅ **处理边界情况**：学会处理根节点分裂、节点合并等复杂情况
4. ✅ **持久化存储**：将B+树节点存储到数据页，实现持久化
5. ✅ **性能测试**：验证B+树的O(log n)查询性能

## 二、实验环境

- **语言**：Python（教学友好，快速迭代）或 C++（性能）
- **前置知识**：树结构、递归算法
- **前置实验**：[实验1](exp1_buffer_analysis.md)、[实验2](exp2_page_allocator.md)（推荐）

## 三、背景知识

### 3.1 B+树 vs B树 vs 二叉搜索树

| 特性 | 二叉搜索树 | B树 | **B+树** |
|------|----------|-----|----------|
| 度（分支因子） | 2 | m（可变） | m（可变） |
| 数据存储位置 | 所有节点 | 所有节点 | **仅叶子节点** |
| 叶子节点 | 无特殊结构 | 可能含数据 | **链表连接** |
| 范围查询 | 慢（中序遍历） | 慢 | **快（顺序遍历）** |
| 磁盘友好性 | 差（节点小） | 好 | **最好（填充整个页）** |

**为什么数据库用B+树？**
- 叶子节点链表支持高效范围扫描（如 `WHERE age BETWEEN 18 AND 25`）
- 内部节点只存键，分支因子更大，树高更低（一次I/O读更多键）
- 数据都在叶子，查询性能稳定（总是O(log n)）

### 3.2 B+树节点结构

假设阶数 `m = 4`（最小），每页可存 `m-1 = 3` 个键。

#### 内部节点（Internal Node）

```
┌─────────────────────────────┐
│ Header:                     │
│   - node_type = INTERNAL    │
│   - num_keys (n)            │
├─────────────────────────────┤
│ Keys:   k0    k1    k2      │  (n个键，排序)
├─────────────────────────────┤
│ Child:  p0    p1    p2    p3 │  (n+1个子节点指针/页ID)
└─────────────────────────────┘

性质：
- p0的所有键 < k0
- k0 ≤ p1的所有键 < k1
- k1 ≤ p2的所有键 < k2
- k2 ≤ p3的所有键
```

#### 叶子节点（Leaf Node）

```
┌─────────────────────────────┐
│ Header:                     │
│   - node_type = LEAF        │
│   - num_keys (n)            │
│   - next_leaf_page_id       │  (指向下一个叶子页)
├─────────────────────────────┤
│ Keys:   k0    k1    k2      │  (n个键，排序)
├─────────────────────────────┤
│ Values: v0   v1   v2        │  (n个值，通常是record_id或数据)
└─────────────────────────────┘

搜索：二分查找找到键k，返回v
```

### 3.3 B+树操作

#### 搜索（Search）

```python
def search(root_page_id, key):
    node = read_page(root_page_id)
    while node.type != LEAF:
        # 在内部节点找到合适的子节点
        i = binary_search(node.keys, key)  # 找到第一个 >= key 的键
        child_id = node.pointers[i]
        node = read_page(child_id)
    # 现在node是叶子，二分查找
    i = binary_search(node.keys, key)
    if i < len(node.keys) and node.keys[i] == key:
        return node.values[i]
    else:
        return None
```

#### 插入（Insert）

```python
def insert(root, key, value):
    # 1. 找到叶子节点L
    path = []  # 记录路径 [(parent, child_idx)]
    node = root
    while node.type != LEAF:
        parent = node
        i = binary_search(node.keys, key)
        path.append((parent, i))
        node = read_page(node.pointers[i])

    L = node

    # 2. 如果L未满，直接插入
    if L.num_keys < ORDER - 1:
        insert_into_leaf(L, key, value)
        write_page(L)
        return

    # 3. L已满，需要分裂
    L_prime = create_leaf()  # 新叶子页
    # 将L的一半键值对移到L_prime（包括新插入的）
    split_leaf(L, L_prime, key, value)

    # 4. L的最小键上推到父节点
    k_prime = L_prime.keys[0]  # L_prime的最小键
    parent, idx = path[-1]
    insert_into_internal(parent, k_prime, L_prime.page_id)

    # 5. 如果父节点也满，递归分裂父节点
    if parent.num_keys >= ORDER:
        split_internal_recursive(parent, path)
```

**分裂叶子**（阶数m=4，每页最多3个键）：

```
原叶子L: [k0, k1, k2] + [v0, v1, v2]
插入(k=1.5, v='new')

插入后排序：
L:   [k0, k1,  k2]      + [v0, v1, v2]
      (保留前2个)         (保留前2个)

L':  [k2, k_new]        + [v2, v_new]
      (移动后2个+新)      (移动后2个+新)

上推键到父节点：k2（原L_keys[2]）

结果：
L.keys = [k0, k1]       (保留前⌈m/2⌉ - 1 = 1个？不对，通常保留一半)
L.values = [v0, v1]

L'.keys = [k2, k_new]
L'.values = [v2, v_new]

父节点插入k2（即L_prime.keys[0]）
```

**注意**：不同教材分裂策略略有差异，常见是：
- 左节点保留 `ceil(m/2) - 1` 个键
- 右节点获得 `floor(m/2)` 个键
- 中间键上推（原来是 `floor(m/2)` 位置的键）

#### 删除（Delete）

```python
def delete(root, key):
    # 1. 找到叶子L
    path = [(None, -1)]  # (parent, child_idx)
    node = root
    while node.type != LEAF:
        i = 0
        while i < node.num_keys and key >= node.keys[i]:
            i += 1
        path.append((node, i))
        node = read_page(node.pointers[i])

    L = node

    # 2. 删除键
    i = binary_search(L.keys, key)
    if i >= len(L.keys) or L.keys[i] != key:
        return  # 键不存在
    remove_from_leaf(L, i)

    # 3. 如果L至少有 ceil(m/2)-1 个键，完成
    if L.num_keys >= ceil(ORDER/2) - 1:
        write_page(L)
        return

    # 4. 尝试从兄弟借键
    parent, idx = path[-1]
    if idx > 0:  # 有左兄弟
        left_sibling = read_page(parent.pointers[idx-1])
        if left_sibling.num_keys > ceil(ORDER/2) - 1:
            borrow_from_left(L, left_sibling, parent, idx)
            return
    if idx < parent.num_keys:  # 有右兄弟
        right_sibling = read_page(parent.pointers[idx+1])
        if right_sibling.num_keys > ceil(ORDER/2) - 1:
            borrow_from_right(L, right_sibling, parent, idx)
            return

    # 5. 合并兄弟
    if idx > 0:
        # 合并到左兄弟
        merge(L, left_sibling, parent, idx)
    else:
        # 合并到右兄弟（右兄弟合并到L）
        merge(L, right_sibling, parent, idx+1)

    # 6. 如果父节点变空且是根，降低树高
    if parent.num_keys == 0 and parent == root:
        adjust_root_after_delete()
    elif parent.num_keys == 0:
        # 递归删除父节点
        delete_recursive(parent, path[:-1])
```

**合并叶子**（假设向右兄弟合并）：

```
原叶子L:  [k0]   (只剩1个键，min=1)
父节点删除指向L的指针和键k

L' (右兄弟): [k1, k2, k3] (3个键，满)

合并后L'（新叶子）:
L'.keys = [k0] + [k1, k2, k3] = [k0, k1, k2, k3]
L'.values = [v0] + [v1, v2, v3]

父节点删除键k0（原第0个键）和指针L

如果父节点是根且变空，根节点改为L'（树高-1）
```

### 3.4 持久化

每个B+树节点存储在**一个数据页**中：

```cpp
// 页布局（重载Page的body部分）
struct BPlusNode {
    PageHeader header;      // 页头（page_id, type, LSN等）
    NodeType node_type;     // INTERNAL 或 LEAF
    uint16_t num_keys;
    uint32_t parent_id;     // 父节点页ID (可选)
    union {
        // 内部节点
        struct {
            uint32_t child_ptrs[ORDER];  // 子节点页ID
            KeyType keys[ORDER-1];       // 排序的键
        } internal;
        // 叶子节点
        struct {
            uint32_t next_leaf_id;       // 下一个叶子页ID
            ValueType values[ORDER-1];   // 值（record_id或数据偏移）
            KeyType keys[ORDER-1];       // 键
        } leaf;
    };
};
```

**读写流程**：
```python
def read_node(page_id):
    page = storage_engine.read_page(page_id)
    data = page.get_data()
    node = deserialize(data)  # 反序列化
    return node

def write_node(node):
    data = serialize(node)  # 序列化
    page = storage_engine.read_page(node.page_id)  # 或allocate新的
    page.set_data(data)
    storage_engine.write_page(page)
```

## 四、实验内容

### 任务1：实现B+树核心类

创建 `src/index/bplus_tree.py`（Python）或C++版本。

#### 4.1 定义节点类

```python
from enum import Enum
from typing import List, Optional, Tuple

class NodeType(Enum):
    INTERNAL = "internal"
    LEAF = "leaf"

class BPlusNode:
    def __init__(self, page_id: int, node_type: NodeType, order: int = 4):
        self.page_id = page_id
        self.node_type = node_type
        self.order = order  # 阶数
        self.num_keys = 0

        # 根据类型分配数组
        if node_type == NodeType.INTERNAL:
            self.keys = [None] * (order - 1)
            self.children = [None] * order  # 子节点page_id
        else:  # LEAF
            self.keys = [None] * (order - 1)
            self.values = [None] * (order - 1)
            self.next_leaf = None  # 下一个叶子页ID

    def is_leaf(self) -> bool:
        return self.node_type == NodeType.LEAF

    def is_full(self) -> bool:
        return self.num_keys >= self.order - 1

    def is_underflow(self) -> bool:
        # 删除后检查：至少需要 ceil(order/2)-1 个键
        min_keys = (self.order // 2) - 1 if self.order % 2 == 0 else (self.order // 2)
        return self.num_keys < min_keys
```

#### 4.2 定义B+树类（完整实现见实验代码）

核心方法：
- `search(key)`：二分查找
- `insert(key, value)`：插入键值对，处理分裂
- `delete(key)`：删除键，处理合并
- `range_scan(low, high)`：范围查询

### 任务2：单元测试

创建 `tests/test_bplus_tree.py`，包含：
- 基本插入和搜索
- 重复键处理
- 大量插入测试分裂
- 删除测试（简单和合并）
- 范围查询测试

### 任务3：性能基准测试

创建 `experiments/exp3_bplus_benchmark.py`：

- 测试不同阶数对性能的影响
- 与哈希表、线性搜索对比
- 测量树高和查询延迟

### 任务4：与存储引擎集成

修改 `StorageEngine` 添加索引支持，测试通过索引查询记录。

## 五、实验要求

### 必做（60分）

- [ ] 实现B+树基本操作（insert/search）（30分）
- [ ] 实现叶子节点分裂（10分）
- [ ] 实现至少一种删除场景（叶子合并）（10分）
- [ ] 单元测试通过（10分）

### 选做（40分）

- [ ] 完整的删除支持（内部节点合并、根收缩）（15分）
- [ ] 范围查询（range_scan）（5分）
- [ ] 与存储引擎集成（10分）
- [ ] 性能基准测试和对比（10分）

## 六、实验报告

### 必须包含

1. **B+树设计**：阶数选择、节点结构
2. **关键代码**：`insert`、`_split_leaf`、`_merge_leaves`等
3. **测试结果**：单元测试截图
4. **性能数据**：阶数vs树高、查询时间对比图表
5. **问题记录**：遇到的bug（如索引错误、合并 bug）和修复

### 可选

- 删除操作的完整实现
- 范围查询性能
- 与SQLite/BerkeleyDB对比（研究性质）

## 七、思考题

1. 为什么B+树内部节点不存储数据？有什么好处？
2. 阶数m对树高和I/O次数有何影响？如何选择最优m？
3. B+树删除时，什么情况下需要合并，什么情况下可以借键？
4. 如何实现B+树的并发访问（多线程）？

## 八、参考资料

- 《数据库系统实现》：第9章 B+树
- SQLite `btree.h`、`btree.c`
- CMU 15-445/645 Project #2

---

**祝你实现顺利！** 实现B+树是理解数据库索引的关键一步。