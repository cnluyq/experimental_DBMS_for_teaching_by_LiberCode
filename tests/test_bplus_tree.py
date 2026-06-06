"""
B+树索引测试

测试B+树的所有核心功能：插入、删除、查找、范围查询、边界情况
"""

import unittest
import random
from src.index.bplus_tree import BPlusTree, IndexEntry
from src.index.bplus_node import LeafNode, InternalNode, NodeType


class TestBPlusTreeBasic(unittest.TestCase):
    """B+树基本功能测试"""
    
    def setUp(self):
        """每个测试前的设置"""
        self.tree = BPlusTree(order=4)
    
    def test_empty_tree(self):
        """测试空树"""
        self.assertIsNone(self.tree.root)
        self.assertEqual(self.tree.size, 0)
        self.assertEqual(self.tree.get_height(), 0)
    
    def test_single_insert(self):
        """测试单个插入"""
        result = self.tree.insert(10, "value10")
        self.assertTrue(result)
        self.assertEqual(self.tree.size, 1)
        self.assertIsNotNone(self.tree.root)
        self.assertTrue(self.tree.root.is_leaf())
        self.assertEqual(self.tree.search(10), "value10")
    
    def test_multiple_insert_same_key(self):
        """测试重复插入同一键（更新）"""
        self.tree.insert(10, "value10_v1")
        self.assertEqual(self.tree.search(10), "value10_v1")
        
        # 再次插入相同键（更新值）
        result = self.tree.insert(10, "value10_v2")
        self.assertTrue(result)
        self.assertEqual(self.tree.size, 1)  # 大小不变
        self.assertEqual(self.tree.search(10), "value10_v2")
    
    def test_insert_sorted_keys(self):
        """测试顺序插入（会导致多次分裂）"""
        keys = list(range(20))
        values = [f"v{i}" for i in keys]
        
        for k, v in zip(keys, values):
            self.tree.insert(k, v)
        
        self.assertEqual(self.tree.size, 20)
        
        # 验证所有键都能找到
        for k, v in zip(keys, values):
            self.assertEqual(self.tree.search(k), v)
    
    def test_insert_random_keys(self):
        """测试随机插入"""
        random.seed(42)
        keys = random.sample(range(1000), 100)
        values = [f"value_{k}" for k in keys]
        
        for k, v in zip(keys, values):
            self.tree.insert(k, v)
        
        self.assertEqual(self.tree.size, 100)
        
        # 验证所有键都存在
        for k, v in zip(keys, values):
            self.assertEqual(self.tree.search(k), v)
    
    def test_insert_reverse_sorted(self):
        """测试逆序插入"""
        keys = list(range(50, 0, -1))
        values = [f"v{i}" for i in keys]
        
        for k, v in zip(keys, values):
            self.tree.insert(k, v)
        
        self.assertEqual(self.tree.size, 50)
        
        # 验证
        for k, v in zip(keys, values):
            self.assertEqual(self.tree.search(k), v)
    
    def test_search_nonexistent(self):
        """测试查找不存在的键"""
        self.tree.insert(10, "v10")
        self.tree.insert(20, "v20")
        self.tree.insert(30, "v30")
        
        self.assertIsNone(self.tree.search(15))
        self.assertIsNone(self.tree.search(0))
        self.assertIsNone(self.tree.search(100))
    
    def test_delete_single_key(self):
        """测试删除单个键"""
        self.tree.insert(10, "v10")
        self.assertTrue(self.tree.delete(10))
        self.assertEqual(self.tree.size, 0)
        self.assertIsNone(self.tree.search(10))
    
    def test_delete_nonexistent(self):
        """测试删除不存在的键"""
        self.tree.insert(10, "v10")
        self.assertFalse(self.tree.delete(20))
        self.assertEqual(self.tree.size, 1)
    
    def test_delete_multiple(self):
        """测试批量删除"""
        for i in range(10):
            self.tree.insert(i, f"v{i}")
        
        self.assertEqual(self.tree.size, 10)
        
        # 删除部分键
        for i in [2, 5, 7]:
            self.tree.delete(i)
        
        self.assertEqual(self.tree.size, 7)
        self.assertIsNone(self.tree.search(2))
        self.assertIsNone(self.tree.search(5))
        self.assertIsNone(self.tree.search(7))
        
        # 验证其他键还在
        for i in [0, 1, 3, 4, 6, 8, 9]:
            self.assertEqual(self.tree.search(i), f"v{i}")


class TestBPlusTreeRangeSearch(unittest.TestCase):
    """范围查询测试"""
    
    def setUp(self):
        self.tree = BPlusTree(order=4)
        # 插入一组数据
        for i in range(0, 100, 10):  # 0, 10, 20, ..., 90
            self.tree.insert(i, f"value_{i}")
    
    def test_range_search_exact(self):
        """测试精确范围查询"""
        results = self.tree.range_search(20, 50)
        expected = [(i, f"value_{i}") for i in range(20, 51, 10)]
        self.assertEqual(results, [IndexEntry(k, v) for k, v in expected])
    
    def test_range_search_partial_overlap(self):
        """测试部分重叠范围"""
        results = self.tree.range_search(15, 35)
        expected = [(20, "value_20"), (30, "value_30")]
        self.assertEqual(len(results), 2)
        self.assertEqual([r.key for r in results], [20, 30])
    
    def test_range_search_no_overlap(self):
        """测试无重叠范围"""
        results = self.tree.range_search(200, 300)
        self.assertEqual(results, [])
    
    def test_range_search_single_key(self):
        """测试单键范围（起点等于终点）"""
        results = self.tree.range_search(30, 30)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].key, 30)
        self.assertEqual(results[0].value, "value_30")
    
    def test_range_search_full(self):
        """测试全范围查询"""
        results = self.tree.range_search(0, 100)
        expected_count = 10  # 0,10,...,90
        self.assertEqual(len(results), expected_count)


class TestBPlusTreeDeletionComplex(unittest.TestCase):
    """复杂删除场景测试"""
    
    def test_delete_causing_leaf_merge(self):
        """测试删除导致叶子节点合并的情况"""
        tree = BPlusTree(order=4)
        
        # 插入足够多的数据，填满多个叶子节点
        keys = list(range(0, 20))
        for i, k in enumerate(keys):
            tree.insert(k, f"v{k}")
        
        # 删除约一半的键，可能导致合并
        for k in [1, 3, 5, 7, 9, 11, 13, 15, 17, 19]:
            tree.delete(k)
        
        # 验证剩下一半的键
        for k in [0, 2, 4, 6, 8, 10, 12, 14, 16, 18]:
            self.assertEqual(tree.search(k), f"v{k}")
        
        # 验证大小
        self.assertEqual(tree.size, 10)
    
    def test_delete_causing_internal_merge(self):
        """测试删除导致内部节点合并"""
        tree = BPlusTree(order=4)
        
        # 插入30个键，应有多层结构
        for i in range(30):
            tree.insert(i, f"v{i}")
        
        # 删除内部键，可能引起内部节点合并
        for i in [5, 6, 7, 8, 9, 10, 11]:
            tree.delete(i)
        
        # 验证某些键还在
        for i in [0, 1, 2, 3, 4]:
            self.assertEqual(tree.search(i), f"v{i}")
    
    def test_delete_all_keys(self):
        """测试删除所有键"""
        tree = BPlusTree(order=4)
        
        # 插入一些数据
        for i in range(10):
            tree.insert(i, f"v{i}")
        
        # 逐个删除
        for i in range(10):
            self.assertTrue(tree.delete(i))
        
        self.assertEqual(tree.size, 0)
        self.assertIsNone(tree.root)
    
    def test_delete_alternating(self):
        """测试交替插入删除"""
        tree = BPlusTree(order=4)
        
        for i in range(20):
            tree.insert(i, f"v{i}")
            if i % 2 == 0:
                tree.delete(i)
        
        # 应该剩下奇数键
        for i in range(20):
            if i % 2 == 0:
                self.assertIsNone(tree.search(i))
            else:
                self.assertEqual(tree.search(i), f"v{i}")
    
    def test_delete_then_insert(self):
        """测试删除后再插入"""
        tree = BPlusTree(order=4)
        
        tree.insert(10, "v10")
        tree.insert(20, "v20")
        tree.delete(10)
        
        # 删除后插入新键
        tree.insert(15, "v15")
        tree.insert(25, "v25")
        
        self.assertEqual(tree.size, 3)
        self.assertEqual(tree.search(20), "v20")
        self.assertEqual(tree.search(15), "v15")
        self.assertEqual(tree.search(25), "v25")


class TestBPlusTreeSplit(unittest.TestCase):
    """分裂测试"""
    
    def test_leaf_split(self):
        """测试叶子节点分裂"""
        tree = BPlusTree(order=4)  # 最大4个键
        
        # 插入5个键，触发叶子分裂
        for i in range(5):
            tree.insert(i, f"v{i}")
        
        # 检查结构
        self.assertEqual(tree.size, 5)
        root = tree.root
        
        # 根应该是内部节点（如果分裂了）
        if not root.is_leaf():
            self.assertEqual(len(root.keys), 1)  # 中间键上提
            # 应该有两个子节点
            self.assertEqual(len(root.children), 2)
            
            left_child = root.children[0]
            right_child = root.children[1]
            
            self.assertTrue(left_child.is_leaf())
            self.assertTrue(right_child.is_leaf())
            
            # 检查叶子链表连接
            self.assertEqual(left_child.next_leaf, right_child)
            self.assertEqual(right_child.prev_leaf, left_child)
    
    def test_multiple_levels(self):
        """测试多级分裂（高树）"""
        tree = BPlusTree(order=4)
        
        # 插入足够多的键以创建高树
        for i in range(100):
            tree.insert(i, f"v{i}")
        
        height = tree.get_height()
        
        if height > 2:
            # 超过两层，说明有内部节点分裂
            self.assertTrue(any(not node.is_leaf() 
                              for node in self._collect_nodes(tree.root)))
        
        # 验证所有键
        for i in [0, 25, 50, 75, 99]:
            self.assertEqual(tree.search(i), f"v{i}")
    
    def _collect_nodes(self, node):
        """收集所有节点（辅助函数）"""
        nodes = [node]
        if not node.is_leaf():
            internal = node  # type: InternalNode
            for child in internal.children:
                nodes.extend(self._collect_nodes(child))
        return nodes


class TestBPlusTreeProperties(unittest.TestCase):
    """B+树性质验证测试"""
    
    def test_all_leaves_same_depth(self):
        """验证所有叶子节点在同一深度"""
        tree = BPlusTree(order=4)
        
        # 插入50个随机键
        random.seed(123)
        keys = random.sample(range(1000), 50)
        for k in keys:
            tree.insert(k, f"v{k}")
        
        # 收集所有叶子节点
        leaves = self._get_all_leaves(tree.root)
        
        # 验证所有叶子节点深度相同
        depths = [self._get_node_depth(tree.root, leaf) for leaf in leaves]
        self.assertEqual(len(set(depths)), 1)
    
    def test_leaf_linked_list(self):
        """验证叶子节点链表正确连接"""
        tree = BPlusTree(order=4)
        
        # 插入有序键
        for i in range(0, 30, 3):  # 0,3,6,...,27
            tree.insert(i, f"v{i}")
        
        # 遍历叶子链表
        leaf = self._find_leftmost_leaf(tree.root)
        keys_seen = []
        
        while leaf is not None:
            keys_seen.extend(leaf.keys)
            leaf = leaf.next_leaf
        
        # 应该看到所有键按顺序
        expected_keys = list(range(0, 30, 3))
        self.assertEqual(keys_seen, expected_keys)
    
    def test_keys_ordering_internal(self):
        """验证内部节点的键顺序正确"""
        tree = BPlusTree(order=4)
        
        for i in range(20):
            tree.insert(i, f"v{i}")
        
        # 检查所有内部节点
        internals = self._collect_internal_nodes(tree.root)
        for internal in internals:
            # 内部节点的keys应该严格递增
            for i in range(len(internal.keys) - 1):
                self.assertLess(internal.keys[i], internal.keys[i+1])
    
    def test_boundary_keys(self):
        """测试边界键（最小值、最大值）"""
        tree = BPlusTree(order=4)
        
        # 插入一些键
        keys = [10, 20, 30, 40, 50]
        for k in keys:
            tree.insert(k, f"v{k}")
        
        # 查找边界
        self.assertEqual(tree.search(10), "v10")
        self.assertEqual(tree.search(50), "v50")
        self.assertIsNone(tree.search(5))
        self.assertIsNone(tree.search(55))
    
    def _get_all_leaves(self, node):
        """获取所有叶子节点"""
        if node.is_leaf():
            return [node]
        
        internal = node  # type: InternalNode
        leaves = []
        for child in internal.children:
            leaves.extend(self._get_all_leaves(child))
        return leaves
    
    def _find_leftmost_leaf(self, node):
        """找到最左边的叶子节点"""
        while not node.is_leaf():
            internal = node  # type: InternalNode
            node = internal.children[0]
        return node  # type: LeafNode
    
    def _get_node_depth(self, root, target):
        """计算从根到目标节点的深度"""
        if root == target:
            return 1
        
        if root.is_leaf():
            return 0
        
        internal = root  # type: InternalNode
        for child in internal.children:
            depth = self._get_node_depth(child, target)
            if depth > 0:
                return depth + 1
        
        return 0
    
    def _collect_internal_nodes(self, node):
        """收集所有内部节点"""
        nodes = []
        if not node.is_leaf():
            nodes.append(node)
            internal = node  # type: InternalNode
            for child in internal.children:
                nodes.extend(self._collect_internal_nodes(child))
        return nodes


class TestBPlusTreeLargeScale(unittest.TestCase):
    """大规模数据测试"""
    
    def test_large_insert(self):
        """测试大量数据插入"""
        tree = BPlusTree(order=8)
        
        # 插入1000个键
        for i in range(1000):
            tree.insert(i, f"value_{i}")
        
        self.assertEqual(tree.size, 1000)
        
        # 随机抽样检查
        for i in [0, 100, 500, 999]:
            self.assertEqual(tree.search(i), f"value_{i}")
    
    def test_large_delete(self):
        """测试大量删除"""
        tree = BPlusTree(order=8)
        
        # 插入500个键
        for i in range(500):
            tree.insert(i, f"v{i}")
        
        # 删除250个键
        for i in range(0, 500, 2):
            tree.delete(i)
        
        self.assertEqual(tree.size, 250)
        
        # 验证
        for i in range(500):
            if i % 2 == 0:
                self.assertIsNone(tree.search(i))
            else:
                self.assertEqual(tree.search(i), f"v{i}")
    
    def test_large_range_search(self):
        """测试大规模范围查询"""
        tree = BPlusTree(order=8)
        
        # 插入1000个键
        for i in range(1000):
            tree.insert(i, f"v{i}")
        
        # 查询大范围
        results = tree.range_search(200, 800)
        expected_count = 601  # 200-800包含
        self.assertEqual(len(results), expected_count)
        
        # 验证第一个和最后一个
        self.assertEqual(results[0].key, 200)
        self.assertEqual(results[-1].key, 800)
    
    def test_stress_random_operations(self):
        """压力测试：随机插入删除"""
        tree = BPlusTree(order=8)
        keys_remaining = set()
        
        operations = 200
        random.seed(42)
        
        for i in range(operations):
            op_type = random.choice(['insert', 'delete'])
            
            if op_type == 'insert':
                key = random.randint(0, 1000)
                value = f"value_{key}_{i}"
                tree.insert(key, value)
                keys_remaining.add(key)
            elif keys_remaining:
                key = random.choice(list(keys_remaining))
                tree.delete(key)
                keys_remaining.remove(key)
        
        # 验证
        for k in keys_remaining:
            self.assertIsNotNone(tree.search(k))


class TestBPlusTreeEdgeCases(unittest.TestCase):
    """边界情况测试"""
    
    def test_insert_duplicate_keys_update(self):
        """测试插入重复键（值不同）"""
        tree = BPlusTree(order=4)
        
        tree.insert(1, "v1_initial")
        tree.insert(1, "v1_updated")
        tree.insert(1, "v1_final")
        
        self.assertEqual(tree.size, 1)
        self.assertEqual(tree.search(1), "v1_final")
    
    def test_delete_until_empty(self):
        """测试删除到空树"""
        tree = BPlusTree(order=4)
        
        tree.insert(1, "v1")
        tree.insert(2, "v2")
        
        self.assertEqual(tree.size, 2)
        
        tree.delete(1)
        tree.delete(2)
        
        self.assertEqual(tree.size, 0)
        self.assertIsNone(tree.root)
    
    def test_mixed_operations(self):
        """测试混合操作序列"""
        tree = BPlusTree(order=4)
        
        ops = [
            ('insert', 1, 'a'),
            ('insert', 2, 'b'),
            ('insert', 3, 'c'),
            ('delete', 2, None),
            ('insert', 4, 'd'),
            ('insert', 5, 'e'),
            ('delete', 1, None),
            ('insert', 6, 'f'),
        ]
        
        for op, key, value in ops:
            if op == 'insert':
                tree.insert(key, value)
            else:
                tree.delete(key)
        
        # 验证最终状态
        self.assertEqual(tree.search(3), 'c')
        self.assertEqual(tree.search(4), 'd')
        self.assertEqual(tree.search(5), 'e')
        self.assertEqual(tree.search(6), 'f')
        
        self.assertIsNone(tree.search(1))
        self.assertIsNone(tree.search(2))


class TestBPlusTreeOrderVariations(unittest.TestCase):
    """不同阶数的B+树测试"""
    
    def test_order_3(self):
        """测试阶数为3的B+树"""
        tree = BPlusTree(order=3)
        
        for i in range(10):
            tree.insert(i, f"v{i}")
        
        for i in range(10):
            self.assertEqual(tree.search(i), f"v{i}")
    
    def test_order_5(self):
        """测试阶数为5的B+树"""
        tree = BPlusTree(order=5)
        
        for i in range(50):
            tree.insert(i, f"v{i}")
        
        for i in [0, 10, 25, 49]:
            self.assertEqual(tree.search(i), f"v{i}")
    
    def test_order_10(self):
        """测试阶数为10的B+树"""
        tree = BPlusTree(order=10)
        
        for i in range(200):
            tree.insert(i, f"v{i}")
        
        self.assertEqual(tree.size, 200)
