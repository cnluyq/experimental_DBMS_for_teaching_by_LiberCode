"""
LRU缓冲区管理器测试

测试缓冲区池的各种功能
"""

import unittest
import tempfile
import os
from src.core.buffer import BufferPool, BufferFrame, FrameState, PageReplaceResult
from src.core.storage_interface import InMemoryStorage, SimpleFileStorage


class TestBufferFrame(unittest.TestCase):
    """测试BufferFrame类"""
    
    def test_frame_initialization(self):
        """测试帧初始化"""
        frame = BufferFrame(0)
        self.assertEqual(frame.frame_id, 0)
        self.assertIsNone(frame.page_id)
        self.assertEqual(frame.state, FrameState.FREE)
        self.assertFalse(frame.dirty)
        self.assertEqual(frame.pin_count, 0)
    
    def test_pin_unpin(self):
        """测试钉住和解钉"""
        frame = BufferFrame(0)
        frame.pin()
        self.assertEqual(frame.pin_count, 1)
        self.assertTrue(frame.is_pinned())
        
        frame.pin()
        self.assertEqual(frame.pin_count, 2)
        
        frame.unpin()
        self.assertEqual(frame.pin_count, 1)
        self.assertTrue(frame.is_pinned())
        
        frame.unpin()
        self.assertEqual(frame.pin_count, 0)
        self.assertFalse(frame.is_pinned())
    
    def test_set_page(self):
        """测试设置页面"""
        frame = BufferFrame(0)
        data = b"test data".ljust(4096, b'\x00')
        frame.set_page(1, data, dirty=False)
        
        self.assertEqual(frame.page_id, 1)
        self.assertEqual(frame.data[:9], b"test data")
        self.assertFalse(frame.dirty)
        self.assertEqual(frame.state, FrameState.CLEAN)
        
        frame.set_page(2, data, dirty=True)
        self.assertEqual(frame.page_id, 2)
        self.assertTrue(frame.dirty)
        self.assertEqual(frame.state, FrameState.DIRTY)


class TestBufferPool(unittest.TestCase):
    """测试BufferPool类"""
    
    def setUp(self):
        """测试前的设置"""
        self.storage = InMemoryStorage(page_size=4096)
        self.buffer = BufferPool(3, self.storage)  # 3个帧的小缓冲区
    
    def test_buffer_initialization(self):
        """测试缓冲区初始化"""
        stats = self.buffer.get_buffer_stats()
        self.assertEqual(stats['total_frames'], 3)
        self.assertEqual(stats['free_frames'], 3)
        self.assertEqual(stats['used_frames'], 0)
    
    def test_read_new_page(self):
        """测试读取新页面（缓存未命中）"""
        # 创建测试页面
        page_id = self.storage.allocate_page()
        data = f"Page {page_id}".encode().ljust(4096, b'\x00')
        self.storage.page_write(page_id, data)
        
        # 读取页面
        frame = self.buffer.read_page(page_id, pin=False)
        self.assertIsNotNone(frame)
        self.assertEqual(frame.page_id, page_id)
        self.assertFalse(frame.dirty)
        
        # 检查统计信息
        stats = self.buffer.get_buffer_stats()
        self.assertEqual(stats['misses'], 1)
        self.assertEqual(stats['hits'], 0)
        self.assertEqual(stats['used_frames'], 1)
    
    def test_read_existing_page_hit(self):
        """测试读取已存在页面（缓存命中）"""
        page_id = self.storage.allocate_page()
        data = f"Page {page_id}".encode().ljust(4096, b'\x00')
        self.storage.page_write(page_id, data)
        
        # 第一次读取
        frame1 = self.buffer.read_page(page_id, pin=False)
        self.assertIsNotNone(frame1)
        
        # 第二次读取（应该命中）
        frame2 = self.buffer.read_page(page_id, pin=False)
        self.assertIsNotNone(frame2)
        self.assertEqual(frame1.frame_id, frame2.frame_id)
        
        # 检查统计信息
        stats = self.buffer.get_buffer_stats()
        self.assertEqual(stats['hits'], 1)
        self.assertEqual(stats['misses'], 1)
    
    def test_lru_eviction(self):
        """测试LRU置换"""
        # 创建3个测试页面（正好填满缓冲区）
        pages = []
        for i in range(3):
            page_id = self.storage.allocate_page()
            data = f"Page {page_id}".encode().ljust(4096, b'\x00')
            self.storage.page_write(page_id, data)
            pages.append(page_id)
            self.buffer.read_page(page_id, pin=False)  # 不钉住，允许置换
        
        # 此时缓冲区已满
        stats = self.buffer.get_buffer_stats()
        self.assertEqual(stats['used_frames'], 3)
        
        # 读取第4个页面（应该触发置换）
        page4_id = self.storage.allocate_page()
        data4 = f"Page {page4_id}".encode().ljust(4096, b'\x00')
        self.storage.page_write(page4_id, data4)
        
        frame4 = self.buffer.read_page(page4_id)
        self.assertIsNotNone(frame4)
        
        # 检查发生了置换
        stats = self.buffer.get_buffer_stats()
        self.assertEqual(stats['evictions'], 1)
        self.assertEqual(stats['used_frames'], 3)  # 仍然使用3个帧
    
    def test_mark_dirty(self):
        """测试标记脏页"""
        page_id = self.storage.allocate_page()
        data = f"Page {page_id}".encode().ljust(4096, b'\x00')
        self.storage.page_write(page_id, data)
        
        frame = self.buffer.read_page(page_id, pin=False)
        self.assertFalse(frame.dirty)
        
        self.buffer.mark_dirty(page_id)
        self.assertTrue(frame.dirty)
    
    def test_flush_page(self):
        """测试写回页面"""
        page_id = self.storage.allocate_page()
        data = f"Page {page_id}".encode().ljust(4096, b'\x00')
        self.storage.page_write(page_id, data)
        
        frame = self.buffer.read_page(page_id)
        self.buffer.mark_dirty(page_id)
        self.assertTrue(frame.dirty)
        
        success = self.buffer.flush_page(page_id)
        self.assertTrue(success)
        self.assertFalse(frame.dirty)
        
        # 检查磁盘上的数据
        disk_data = self.storage.page_read(page_id)
        self.assertEqual(disk_data, bytes(frame.data))
    
    def test_flush_all(self):
        """测试写回所有脏页"""
        pages = []
        for i in range(3):
            page_id = self.storage.allocate_page()
            data = f"Page {page_id}".encode().ljust(4096, b'\x00')
            self.storage.page_write(page_id, data)
            frame = self.buffer.read_page(page_id)
            self.buffer.mark_dirty(page_id)
            pages.append((page_id, frame))
        
        success = self.buffer.flush_all()
        self.assertTrue(success)
        
        # 检查所有页面都已写回
        for page_id, frame in pages:
            self.assertFalse(frame.dirty)
    
    def test_pin_unpin_page(self):
        """测试页面钉住"""
        page_id = self.storage.allocate_page()
        data = f"Page {page_id}".encode().ljust(4096, b'\x00')
        self.storage.page_write(page_id, data)
        
        frame = self.buffer.read_page(page_id, pin=True)
        self.assertTrue(frame.is_pinned())
        
        self.buffer.unpin_page(page_id)
        self.assertFalse(frame.is_pinned())
    
    def test_create_page(self):
        """测试创建新页面"""
        page_id = self.storage.allocate_page()
        initial_data = b"New page".ljust(4096, b'\x00')
        
        frame = self.buffer.create_page(page_id, initial_data, pin=False)
        self.assertIsNotNone(frame)
        self.assertEqual(frame.page_id, page_id)
        self.assertTrue(frame.dirty)
        # frame.data is bytearray, compare the exact content
        self.assertEqual(frame.data[:len(b"New page")], b"New page")
    
    def test_get_frame_info(self):
        """测试获取帧信息"""
        page_id = self.storage.allocate_page()
        data = f"Page {page_id}".encode().ljust(4096, b'\x00')
        self.storage.page_write(page_id, data)
        
        self.buffer.read_page(page_id, pin=False)
        info = self.buffer.get_frame_info(page_id)
        
        self.assertIsNotNone(info)
        self.assertEqual(info['page_id'], page_id)
        self.assertIn('frame_id', info)
        self.assertIn('dirty', info)
        self.assertIn('pinned', info)
    
    def test_shutdown(self):
        """测试关闭缓冲区"""
        page_id = self.storage.allocate_page()
        data = f"Page {page_id}".encode().ljust(4096, b'\x00')
        self.storage.page_write(page_id, data)
        
        frame = self.buffer.read_page(page_id)
        self.buffer.mark_dirty(page_id)
        
        # 关闭应该自动写回
        self.buffer.shutdown()
        self.assertFalse(frame.dirty)


class TestBufferPoolWithFileStorage(unittest.TestCase):
    """测试使用文件存储的缓冲区"""
    
    def setUp(self):
        """创建临时文件"""
        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        self.temp_file.close()
        self.storage = SimpleFileStorage(self.temp_file.name, page_size=4096)
        self.buffer = BufferPool(2, self.storage)
    
    def tearDown(self):
        """清理临时文件"""
        os.unlink(self.temp_file.name)
    
    def test_file_storage(self):
        """测试文件存储后端"""
        page_id = 0
        data = b"File storage test".ljust(4096, b'\x00')
        self.storage.page_write(page_id, data)
        
        frame = self.buffer.read_page(page_id)
        self.assertIsNotNone(frame)
        self.assertEqual(frame.data[:len(b"File storage test")], b"File storage test")


if __name__ == '__main__':
    unittest.main(verbosity=2)