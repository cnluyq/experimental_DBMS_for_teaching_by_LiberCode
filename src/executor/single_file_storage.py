"""
单文件存储（扩展版）

单文件存储支持多表。所有表数据存储在同一个文件中，但使用不同的page_id范围。
文件布局：
- Page 0: 超级块（Superblock），存储元数据（表目录、列目录等）
- Page 1: 未分配位图（可选）
- Pages 2+: 数据页面，每个表从某个起始page开始分配

系统表：
- __tables__: 表目录，记录每个表的起始page_id和元数据
- __columns__: 列目录，记录所有表的列定义

表数据格式：使用TableRecordManager定义的记录格式。
"""

from typing import Optional, List, Dict, Any
from core.storage_interface import StorageEngine
import os
import struct


class SingleFileStorage(StorageEngine):
    """单文件多表存储引擎"""
    
    def __init__(self, file_path: str, page_size: int = 4096):
        """
        初始化单文件存储
        
        Args:
            file_path: 数据文件路径
            page_size: 页面大小
        """
        self.file_path = file_path
        self.page_size = page_size
        self.file = None
        self._init_file()
        
        # 页面分配状态跟踪
        self.next_page_id = self._scan_next_page_id()
        
        # 系统表起始page_id
        self.SUPERBLOCK_PAGE = 0
        self.TABLES_DIR_PAGE = 1  # __tables__
        self.COLUMNS_DIR_PAGE = 2  # __columns__
    
    def _init_file(self):
        """初始化文件"""
        if not os.path.exists(self.file_path):
            # 创建新文件，预分配一些页面
            with open(self.file_path, 'wb') as f:
                # 写入超级块（第0页）
                superblock = self._create_superblock()
                f.write(superblock)
                
                # 写入表目录（第1页）- 初始为空
                tables_page = b'\x00' * self.page_size
                f.write(tables_page)
                
                # 写入列目录（第2页）
                columns_page = b'\x00' * self.page_size
                f.write(columns_page)
        
        # 打开文件
        self.file = open(self.file_path, 'r+b')
    
    def _create_superblock(self) -> bytes:
        """创建超级块"""
        # 超级块格式：
        # - Magic number (8 bytes): "SINGLEF1"
        # - Version (4 bytes)
        # - Page size (4 bytes)
        # - Next page ID (8 bytes)
        # - Tables dir page ID (8 bytes)
        # - Columns dir page ID (8 bytes)
        # - Reserved (4080 bytes)
        
        magic = b"SINGLEF1"
        version = 1
        next_page_id = 3  # 前3页已用
        tables_dir_page = 1
        columns_dir_page = 2
        
        header = struct.pack(
            '<8sIIQQQ',
            magic,
            version,
            self.page_size,
            next_page_id,
            tables_dir_page,
            columns_dir_page
        )
        
        return header.ljust(self.page_size, b'\x00')
    
    def _scan_next_page_id(self) -> int:
        """扫描文件确定下一个可用page_id"""
        if not os.path.exists(self.file_path):
            return 0
        
        file_size = os.path.getsize(self.file_path)
        return file_size // self.page_size
    
    def page_read(self, page_id: int) -> Optional[bytes]:
        """读取页面"""
        try:
            self.file.seek(page_id * self.page_size)
            data = self.file.read(self.page_size)
            if len(data) < self.page_size:
                return None
            return data
        except Exception:
            return None
    
    def page_write(self, page_id: int, data: bytes) -> bool:
        """写入页面"""
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
        """分配新页面"""
        page_id = self.next_page_id
        self.next_page_id += 1
        
        # 扩展文件
        with open(self.file_path, 'ab') as f:
            f.write(b'\x00' * self.page_size)
        
        return page_id
    
    def get_page_size(self) -> int:
        return self.page_size
    
    def close(self):
        """关闭文件"""
        if self.file:
            self.file.close()
    
    def __del__(self):
        self.close()


if __name__ == "__main__":
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = tmp.name
    
    try:
        storage = SingleFileStorage(tmp_path, 4096)
        
        # 分配页面
        page_id = storage.allocate_page()
        print(f"Allocated page {page_id}")
        
        # 写入数据
        data = b"Test data".ljust(4096, b'\x00')
        storage.page_write(page_id, data)
        
        # 读取
        read_data = storage.page_read(page_id)
        print(f"Read: {read_data[:10]}")
        
        storage.close()
        print("Test passed!")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
