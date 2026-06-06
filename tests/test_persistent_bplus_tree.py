"""
持久化B+树测试
"""

import unittest
import tempfile
import os
from src.index.serializer import PersistentBPlusTree
from src.core.buffer import BufferPool
from src.core.storage_interface import InMemoryStorage


class TestPersistentBPlusTreeBasic(unittest.TestCase):
    """持久化B+树基本功能测试"""
    
    def setUp(self):
        """每个测试前的设置"""
        # 使用内存存储，便于测试
        self.storage = InMemoryStorage(page_size=4096)
        self.buffer = BufferPool(num_frames=50, storage_engine=self.storage)
        self.tree = PersistentBPlusTree(buffer_pool=self.buffer, order=4)
    
    def test_single_insert(self):
        """测试单个插入"""
        result = self.tree.insert(10, (100, 0))  # record_id: page_id=100, slot_id=0
        self.assertTrue(result)
        self.assertEqual(self.tree.size, 1)
        
        # 验证读取
        value = self.tree.search(10)
        self.assertEqual(value, (100, 0))
    
    def test_multiple_insert(self):
        """测试多个插入"""
        for i in range(10):
            self.tree.insert(i, (i, 0))  # page_id=i, slot_id=0
        
        self.assertEqual(self.tree.size, 10)
        
        # 验证所有键
        for i in range(10):
            self.assertEqual(self.tree.search(i), (i, 0))
    
    def test_insert_duplicate(self):
        """测试重复插入（更新）"""
        self.tree.insert(10, (100, 1))
        self.assertEqual(self.tree.search(10), (100, 1))
        
        # 再次插入相同键
        result = self.tree.insert(10, (100, 2))
        self.assertTrue(result)
        self.assertEqual(self.tree.size, 1)  # 大小不变
        self.assertEqual(self.tree.search(10), (100, 2))
    
    def test_insert_sorted_keys(self):
        """测试顺序插入（触发分裂）"""
        keys = list(range(20))
        for k in keys:
            self.tree.insert(k, (k, 0))
        
        self.assertEqual(self.tree.size, 20)
        
        # 验证所有键
        for k in keys:
            self.assertEqual(self.tree.search(k), (k, 0))
    
    def test_insert_random_keys(self):
        """测试随机插入"""
        import random
        random.seed(42)
        keys = random.sample(range(1000), 100)
        for k in keys:
            self.tree.insert(k, (k, 0))
        
        self.assertEqual(self.tree.size, 100)
        
        # 验证
        for k in keys:
            self.assertEqual(self.tree.search(k), (k, 0))
    
    def test_range_search(self):
        """测试范围查询"""
        for i in range(0, 100, 10):
            self.tree.insert(i, (i, 0))
        
        results = self.tree.range_search(20, 50)
        # results应该是元组列表 (key, value)
        keys_found = [k for k, v in results]
        expected_keys = [20, 30, 40, 50]
        self.assertEqual(keys_found, expected_keys)
        
        for k, v in results:
            self.assertEqual(v, (k, 0))
    
    def test_shutdown(self):
        """测试关闭"""
        self.tree.insert(1, "v1")
        self.tree.insert(2, "v2")
        
        # 应该不抛出异常
        self.tree.shutdown()


class TestPersistentBPlusTreeDeletion(unittest.TestCase):
    """持久化B+树删除测试（待实现）"""
    
    def setUp(self):
        self.storage = InMemoryStorage(page_size=4096)
        self.buffer = BufferPool(num_frames=50, storage_engine=self.storage)
        self.tree = PersistentBPlusTree(buffer_pool=self.buffer, order=4)
    
    def test_delete_single(self):
        """测试删除单个键"""
        self.tree.insert(10, "v10")
        result = self.tree.delete(10)
        self.assertTrue(result)
        self.assertEqual(self.tree.size, 0)
        self.assertIsNone(self.tree.search(10))
    
    def test_delete_multiple(self):
        """测试删除多个"""
        for i in range(10):
            self.tree.insert(i, (i, 0))
        
        for i in [2, 5, 7]:
            self.tree.delete(i)
        
        self.assertEqual(self.tree.size, 7)
        self.assertIsNone(self.tree.search(2))
        self.assertIsNone(self.tree.search(5))
        self.assertIsNone(self.tree.search(7))
        
        # 检查其他键
        for i in [0, 1, 3, 4, 6, 8, 9]:
            self.assertEqual(self.tree.search(i), (i, 0))
    
    def test_delete_all(self):
        """测试删除所有"""
        for i in range(10):
            self.tree.insert(i, (i, 0))
        
        for i in range(10):
            self.tree.delete(i)
        
        self.assertEqual(self.tree.size, 0)
    
    def test_delete_then_insert(self):
        """测试删除后再插入"""
        self.tree.insert(10, "v10")
        self.tree.insert(20, "v20")
        self.tree.delete(10)
        
        self.tree.insert(15, "v15")
        self.assertEqual(self.tree.size, 2)
        self.assertEqual(self.tree.search(20), "v20")
        self.assertEqual(self.tree.search(15), "v15")


if __name__ == "__main__":
    unittest.main()
