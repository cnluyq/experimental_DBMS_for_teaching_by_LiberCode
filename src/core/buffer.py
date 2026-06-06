"""
LRU缓冲区池管理器

功能：
1. 管理固定数量的缓冲区帧
2. 实现LRU页面置换算法
3. 处理页面的读取请求
4. 管理脏页的写回
5. 与存储引擎协作
"""

import threading
from enum import Enum
from typing import Optional, Dict, Any


class PageReplaceResult(Enum):
    """页面置换结果"""
    SUCCESS = "success"           # 成功
    PAGE_NOT_FOUND = "not_found" # 页面不在缓冲区
    BUFFER_FULL = "buffer_full"  # 缓冲区已满且未找到可用页


class FrameState(Enum):
    """缓冲区帧状态"""
    FREE = "free"         # 空闲
    CLEAN = "clean"       # 干净页（与磁盘一致）
    DIRTY = "dirty"       # 脏页（需要写回磁盘）


class BufferFrame:
    """缓冲区帧类"""
    
    def __init__(self, frame_id: int):
        self.frame_id = frame_id
        self.page_id: Optional[int] = None  # 页面ID，None表示空闲
        self.data: Optional[bytearray] = None  # 页面数据
        self.state = FrameState.FREE
        self.dirty = False  # 是否脏页
        self.pin_count = 0  # 钉住计数（防止被置换）
        self.access_time = 0  # 访问时间（用于LRU）
    
    def is_free(self) -> bool:
        """是否空闲"""
        return self.page_id is None
    
    def is_pinned(self) -> bool:
        """是否被钉住"""
        return self.pin_count > 0
    
    def pin(self):
        """钉住页面"""
        self.pin_count += 1
    
    def unpin(self):
        """解除钉住"""
        if self.pin_count > 0:
            self.pin_count -= 1
    
    def set_page(self, page_id: int, data: bytes, dirty: bool = False):
        """设置页面内容"""
        self.page_id = page_id
        self.data = bytearray(data)
        self.dirty = dirty
        self.state = FrameState.DIRTY if dirty else FrameState.CLEAN


class BufferPool:
    """LRU缓冲区池管理器"""
    
    def __init__(self, num_frames: int, storage_engine, logger=None):
        """
        初始化缓冲区池
        
        Args:
            num_frames: 缓冲区帧数量
            storage_engine: 存储引擎实例（提供page_read, page_write方法）
            logger: 日志记录器（可选）
        """
        self.num_frames = num_frames
        self.storage = storage_engine
        self.logger = logger
        
        # 缓冲区帧数组
        self.frames: Dict[int, BufferFrame] = {}
        for i in range(num_frames):
            self.frames[i] = BufferFrame(i)
        
        # LRU链表：维护访问顺序（最新访问的在头部）
        self.lru_list = []  # 帧ID列表
        
        # 页面到帧的映射
        self.page_to_frame: Dict[int, int] = {}
        
        # 统计信息
        self.stats = {
            'reads_total': 0,      # 总读取次数
            'reads_disk': 0,       # 从磁盘读取次数
            'writes_disk': 0,      # 写回磁盘次数
            'hits': 0,            # 缓存命中次数
            'misses': 0,          # 缓存未命中次数
            'evictions': 0,       # 置换次数
            'evicted_dirty': 0,   # 置换的脏页数量
        }
        
        self.lock = threading.RLock()
        self.global_access_time = 0
    
    def _update_access_time(self, frame: BufferFrame):
        """更新帧的访问时间"""
        frame.access_time = self.global_access_time
        self.global_access_time += 1
    
    def _move_to_lru_head(self, frame_id: int):
        """将帧移到LRU链表头部"""
        if frame_id in self.lru_list:
            self.lru_list.remove(frame_id)
        self.lru_list.insert(0, frame_id)
    
    def _find_victim_frame(self) -> Optional[BufferFrame]:
        """寻找牺牲帧（LRU算法）"""
        with self.lock:
            # 从尾部开始查找（最久未使用的）
            for frame_id in reversed(self.lru_list):
                frame = self.frames[frame_id]
                if not frame.is_pinned() and frame.page_id is not None:
                    return frame
        return None
    
    def _evict_page(self, frame: BufferFrame) -> bool:
        """驱逐页面"""
        if frame is None or frame.page_id is None or frame.is_pinned():
            return False
        
        # 如果是脏页，写回磁盘
        if frame.dirty:
            success = self._write_page_to_disk(frame)
            if not success:
                if self.logger:
                    self.logger.error(f"Failed to write back page {frame.page_id}")
                return False
            self.stats['evicted_dirty'] += 1
        
        # 从映射中移除
        if frame.page_id in self.page_to_frame:
            del self.page_to_frame[frame.page_id]
        
        # 重置帧状态
        frame.set_page(None, b'', False)
        
        # 从LRU链表中移除
        if frame.frame_id in self.lru_list:
            self.lru_list.remove(frame.frame_id)
        
        self.stats['evictions'] += 1
        return True
    
    def _read_page_from_disk(self, page_id: int, frame: BufferFrame) -> bool:
        """从磁盘读取页面"""
        try:
            data = self.storage.page_read(page_id)
            if data is None:
                return False
            frame.set_page(page_id, data, False)
            self.stats['reads_disk'] += 1
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to read page {page_id} from disk: {e}")
            return False
    
    def _write_page_to_disk(self, frame: BufferFrame) -> bool:
        """将页面写回磁盘"""
        if frame.page_id is None or frame.data is None:
            return False
        
        try:
            self.storage.page_write(frame.page_id, bytes(frame.data))
            frame.dirty = False
            frame.state = FrameState.CLEAN
            self.stats['writes_disk'] += 1
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to write page {frame.page_id} to disk: {e}")
            return False
    
    def _get_free_frame(self) -> Optional[BufferFrame]:
        """获取空闲帧"""
        with self.lock:
            for frame in self.frames.values():
                if frame.is_free():
                    return frame
        return None
    
    def read_page(self, page_id: int, pin: bool = True) -> Optional[BufferFrame]:
        """
        读取页面（Flyweight模式：返回内部BFrame供内部使用）
        
        Args:
            page_id: 页面ID
            Pin: 是否钉住页面（防止被置换）
        
        Returns:
            BufferFrame实例或None（失败时）
        """
        with self.lock:
            self.stats['reads_total'] += 1
            
            # 检查页面是否已在缓冲区中
            if page_id in self.page_to_frame:
                frame_id = self.page_to_frame[page_id]
                frame = self.frames[frame_id]
                
                # 更新访问时间
                self._update_access_time(frame)
                self._move_to_lru_head(frame_id)
                
                self.stats['hits'] += 1
                if self.logger:
                    self.logger.debug(f"Page {page_id} hit in frame {frame_id}")
                
                if pin:
                    frame.pin()
                
                return frame
            
            # 缓存未命中
            self.stats['misses'] += 1
            
            # 尝试获取空闲帧
            frame = self._get_free_frame()
            
            # 如果没有空闲帧，尝试驱逐一个页面
            if frame is None:
                victim = self._find_victim_frame()
                if victim is None:
                    if self.logger:
                        self.logger.warning("No victim frame found for eviction")
                    return None
                
                if not self._evict_page(victim):
                    if self.logger:
                        self.logger.error(f"Failed to evict page {victim.page_id}")
                    return None
                
                frame = victim
            
            # 从磁盘读取页面
            if not self._read_page_from_disk(page_id, frame):
                return None
            
            # 更新映射和LRU
            self.page_to_frame[page_id] = frame.frame_id
            self._update_access_time(frame)
            self._move_to_lru_head(frame.frame_id)
            
            if pin:
                frame.pin()
            
            if self.logger:
                self.logger.debug(f"Page {page_id} loaded into frame {frame.frame_id}")
            
            return frame
    
    def create_page(self, page_id: int, data: bytes = b'', pin: bool = True) -> Optional[BufferFrame]:
        """
        创建新页面（用于扩展数据文件）
        
        Args:
            page_id: 页面ID
            data: 页面初始数据
            pin: 是否钉住
            
        Returns:
            BufferFrame实例或None
        """
        with self.lock:
            if page_id in self.page_to_frame:
                if self.logger:
                    self.logger.warning(f"Page {page_id} already exists")
                return None
            
            frame = self._get_free_frame()
            if frame is None:
                victim = self._find_victim_frame()
                if victim is None:
                    return None
                if not self._evict_page(victim):
                    return None
                frame = victim
            
            frame.set_page(page_id, data, dirty=True)
            self.page_to_frame[page_id] = frame.frame_id
            self._update_access_time(frame)
            self._move_to_lru_head(frame.frame_id)
            
            if pin:
                frame.pin()
            
            if self.logger:
                self.logger.info(f"Created page {page_id} in frame {frame.frame_id}")
            
            return frame
    
    def mark_dirty(self, page_id: int) -> bool:
        """标记页面为脏页"""
        with self.lock:
            if page_id not in self.page_to_frame:
                return False
            
            frame = self.frames[self.page_to_frame[page_id]]
            frame.dirty = True
            frame.state = FrameState.DIRTY
            
            if self.logger:
                self.logger.debug(f"Page {page_id} marked as dirty")
            
            return True
    
    def unpin_page(self, page_id: int) -> bool:
        """解除页面钉住"""
        with self.lock:
            if page_id not in self.page_to_frame:
                return False
            
            frame = self.frames[self.page_to_frame[page_id]]
            frame.unpin()
            
            if self.logger:
                self.logger.debug(f"Page {page_id} unpinned")
            
            return True
    
    def flush_page(self, page_id: int) -> bool:
        """强制写回指定页面"""
        with self.lock:
            if page_id not in self.page_to_frame:
                return False
            
            frame = self.frames[self.page_to_frame[page_id]]
            return self._write_page_to_disk(frame)
    
    def flush_all(self) -> bool:
        """写回所有脏页"""
        with self.lock:
            success = True
            for frame in self.frames.values():
                if frame.dirty and frame.page_id is not None:
                    if not self._write_page_to_disk(frame):
                        success = False
                        if self.logger:
                            self.logger.error(f"Failed to flush page {frame.page_id}")
            return success
    
    def get_frame_info(self, page_id: int) -> Optional[Dict[str, Any]]:
        """获取页面在缓冲区中的信息"""
        with self.lock:
            if page_id not in self.page_to_frame:
                return None
            
            frame_id = self.page_to_frame[page_id]
            frame = self.frames[frame_id]
            
            return {
                'frame_id': frame.frame_id,
                'page_id': frame.page_id,
                'dirty': frame.dirty,
                'pinned': frame.is_pinned(),
                'pin_count': frame.pin_count,
                'access_time': frame.access_time,
            }
    
    def get_buffer_stats(self) -> Dict[str, Any]:
        """获取缓冲区池统计信息"""
        with self.lock:
            stats = self.stats.copy()
            
            # 计算命中率
            total_accesses = stats['reads_total']
            if total_accesses > 0:
                stats['hit_rate'] = stats['hits'] / total_accesses
            else:
                stats['hit_rate'] = 0.0
            
            # 当前使用情况
            used_frames = sum(1 for f in self.frames.values() if not f.is_free())
            dirty_frames = sum(1 for f in self.frames.values() if f.dirty)
            
            stats['total_frames'] = self.num_frames
            stats['used_frames'] = used_frames
            stats['free_frames'] = self.num_frames - used_frames
            stats['dirty_frames'] = dirty_frames
            
            return stats
    
    def shutdown(self):
        """关闭缓冲区池（写回所有脏页）"""
        if self.logger:
            self.logger.info("Shutting down buffer pool...")
        
        self.flush_all()
        
        if self.logger:
            stats = self.get_buffer_stats()
            self.logger.info(f"Buffer pool shutdown complete. Stats: {stats}")


# 示例：简单的存储引擎接口
class SimpleStorageEngine:
    """简单的存储引擎示例（用于演示）"""
    
    def __init__(self, page_size: int = 4096):
        self.page_size = page_size
        self.pages: Dict[int, bytes] = {}
    
    def page_read(self, page_id: int) -> Optional[bytes]:
        """读取页面（从内存字典）"""
        return self.pages.get(page_id)
    
    def page_write(self, page_id: int, data: bytes):
        """写入页面（到内存字典）"""
        if len(data) != self.page_size:
            raise ValueError(f"Page size mismatch: expected {self.page_size}, got {len(data)}")
        self.pages[page_id] = data
    
    def create_page_file(self, page_id: int, initial_data: bytes = None):
        """创建页面文件（模拟磁盘操作）"""
        if initial_data is None:
            initial_data = b'\x00' * self.page_size
        self.page_write(page_id, initial_data)


if __name__ == "__main__":
    # 简单测试
    print("Testing LRU Buffer Pool...")
    
    # 创建存储引擎
    storage = SimpleStorageEngine(page_size=4096)
    
    # 创建一些测试页面
    for i in range(10):
        data = f"Page {i} content".encode().ljust(4096, b'\x00')
        storage.create_page_file(i, data)
    
    # 创建缓冲区池（5个帧）
    buffer = BufferPool(5, storage)
    
    # 测试读取页面
    print("\n1. Reading pages 0, 1, 2, 3, 4 (should fill buffer)")
    for i in range(5):
        frame = buffer.read_page(i)
        if frame:
            print(f"  Page {i} loaded into frame {frame.frame_id}")
    
    print(f"\nBuffer stats: {buffer.get_buffer_stats()}")
    
    # 测试缓存命中
    print("\n2. Reading page 0 again (should be hit)")
    frame = buffer.read_page(0)
    if frame:
        print(f"  Page 0 hit in frame {frame.frame_id}")
    
    # 测试缓存未命中（应该触发LRU置换）
    print("\n3. Reading page 5 (should evict least recently used)")
    frame = buffer.read_page(5)
    if frame:
        print(f"  Page 5 loaded into frame {frame.frame_id}")
    
    print(f"\nBuffer stats: {buffer.get_buffer_stats()}")
    
    # 测试脏页
    print("\n4. Marking page 1 as dirty and flushing")
    buffer.mark_dirty(1)
    buffer.flush_page(1)
    
    # 查看最终状态
    print("\n5. Final buffer state:")
    for frame_id, frame in buffer.frames.items():
        if frame.page_id is not None:
            print(f"  Frame {frame_id}: page={frame.page_id}, dirty={frame.dirty}, pinned={frame.is_pinned()}")
    
    # 关闭缓冲区
    buffer.shutdown()
    print("\nTest completed!")