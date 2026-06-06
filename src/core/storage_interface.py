"""
存储引擎接口定义

定义缓冲区管理器所需的存储引擎接口
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict


class StorageEngine(ABC):
    """存储引擎抽象基类"""
    
    @abstractmethod
    def page_read(self, page_id: int) -> Optional[bytes]:
        """
        从存储读取页面
        
        Args:
            page_id: 页面ID
            
        Returns:
            页面数据（bytes）或None（如果页面不存在）
        """
        pass
    
    @abstractmethod
    def page_write(self, page_id: int, data: bytes) -> bool:
        """
        写入页面到存储
        
        Args:
            page_id: 页面ID
            data: 页面数据
            
        Returns:
            成功返回True，失败返回False
        """
        pass
    
    @abstractmethod
    def allocate_page(self) -> int:
        """
        分配新页面ID
        
        Returns:
            新的页面ID
        """
        pass
    
    def get_page_size(self) -> int:
        """
        获取页面大小
        
        Returns:
            页面大小（字节）
        """
        return 4096  # 默认4KB


class SimpleFileStorage(StorageEngine):
    """基于文件的简单存储引擎"""
    
    def __init__(self, file_path: str, page_size: int = 4096):
        self.file_path = file_path
        self.page_size = page_size
        self.file = None
        self._free_pages = []  # 释放的页面ID栈
        self._init_file()
    
    def _init_file(self):
        """初始化文件"""
        import os
        if not os.path.exists(self.file_path):
            # 创建空文件，预分配100个页面
            with open(self.file_path, 'wb') as f:
                f.write(b'\x00' * 100 * self.page_size)
        
        self.file = open(self.file_path, 'r+b')
    
    def page_read(self, page_id: int) -> Optional[bytes]:
        """读取指定页面"""
        try:
            self.file.seek(page_id * self.page_size)
            data = self.file.read(self.page_size)
            if len(data) < self.page_size:
                return None
            return data
        except Exception:
            return None
    
    def page_write(self, page_id: int, data: bytes) -> bool:
        """写入指定页面"""
        if len(data) != self.page_size:
            return False
        
        try:
            self.file.seek(page_id * self.page_size)
            self.file.write(data)
            self.file.flush()
            return True
        except Exception:
            return False
    
    def allocate_page(self) -> int:
        """分配新页面（优先重用已释放页面）"""
        import os
        # 如果有已释放的页面，优先重用
        if self._free_pages:
            return self._free_pages.pop()
        # 否则追加到文件末尾
        file_size = os.path.getsize(self.file_path)
        num_pages = file_size // self.page_size
        return num_pages
    
    def deallocate_page(self, page_id: int):
        """释放页面（加入空闲列表，可重用）"""
        if page_id not in self._free_pages:
            self._free_pages.append(page_id)
    
    def close(self):
        """关闭文件"""
        if self.file:
            self.file.close()
    
    def __del__(self):
        self.close()


class InMemoryStorage(StorageEngine):
    """内存存储引擎（用于测试）"""
    
    def __init__(self, page_size: int = 4096):
        self.page_size = page_size
        self.pages: Dict[int, bytes] = {}
        self.next_page_id = 0
    
    def page_read(self, page_id: int) -> Optional[bytes]:
        return self.pages.get(page_id)
    
    def page_write(self, page_id: int, data: bytes) -> bool:
        if len(data) != self.page_size:
            return False
        self.pages[page_id] = data
        return True
    
    def allocate_page(self) -> int:
        page_id = self.next_page_id
        self.next_page_id += 1
        return page_id
    
    def get_page_size(self) -> int:
        return self.page_size


if __name__ == "__main__":
    # 测试内存存储
    print("Testing InMemoryStorage...")
    storage = InMemoryStorage(4096)
    
    # 写入页面
    page_id = storage.allocate_page()
    data = b"Hello, World!".ljust(4096, b'\x00')
    storage.page_write(page_id, data)
    
    # 读取页面
    read_data = storage.page_read(page_id)
    print(f"Read page {page_id}: {read_data[:13]}")
    print("Test passed!")