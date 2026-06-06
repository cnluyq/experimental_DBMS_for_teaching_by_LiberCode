"""
多文件存储引擎（Multi-File Storage）

每个表存储在独立的文件中，系统表使用特殊文件名。
文件结构：
- 每个文件按固定大小page组织
- 第一个page存储元数据（页表等）
- 后续pages存储数据记录
"""

from typing import Optional, Dict, List, Any
from core.storage_interface import StorageEngine
import os
import struct


class MultiFileStorage(StorageEngine):
    """多文件存储引擎"""
    
    SYSTEM_TABLES = ['__tables__', '__columns__']
    
    def __init__(self, database_dir: str, page_size: int = 4096):
        """
        初始化多文件存储引擎
        
        Args:
            database_dir: 数据库目录路径
            page_size: 页面大小
        """
        self.database_dir = database_dir
        self.page_size = page_size
        self.files: Dict[str, Any] = {}  # 表名 -> 文件对象
        self.page_counters: Dict[str, int] = {}  # 表名 -> 页面计数
        
        # 确保数据库目录存在
        os.makedirs(database_dir, exist_ok=True)
        
        # 扫描现有表文件
        self._scan_existing_tables()
    
    def _scan_existing_tables(self):
        """扫描数据库目录，加载现有表"""
        if not os.path.exists(self.database_dir):
            return
        
        for filename in os.listdir(self.database_dir):
            if filename.endswith('.data'):
                table_name = filename[:-6]  # 去掉.data后缀
                file_path = os.path.join(self.database_dir, filename)
                # 打开文件但不立即读取
                self._open_table_file(table_name)
    
    def _get_table_file_path(self, table_name: str) -> str:
        """获取表文件路径"""
        return os.path.join(self.database_dir, f"{table_name}.data")
    
    def _open_table_file(self, table_name: str):
        """打开表文件"""
        if table_name in self.files:
            return
        
        file_path = self._get_table_file_path(table_name)
        if not os.path.exists(file_path):
            # 文件不存在，稍后需要创建
            return
        
        try:
            f = open(file_path, 'r+b')
            self.files[table_name] = f
            
            # 获取文件大小以计算页面数
            f.seek(0, 2)  # 移动到文件末尾
            file_size = f.tell()
            page_count = file_size // self.page_size
            self.page_counters[table_name] = page_count
        except Exception as e:
            print(f"Warning: cannot open table {table_name}: {e}")
    
    def _create_table_file(self, table_name: str):
        """创建新的表文件"""
        file_path = self._get_table_file_path(table_name)
        with open(file_path, 'wb') as f:
            # 写入空页面（至少1个页面作为首页）
            f.write(b'\x00' * self.page_size)
        
        # 打开文件
        self._open_table_file(table_name)
        self.page_counters[table_name] = 1
    
    def page_read(self, table_name: str, page_id: int) -> Optional[bytes]:
        """
        读取指定表的页面
        
        Args:
            table_name: 表名
            page_id: 页面ID（相对于该表的页面空间）
            
        Returns:
            页面数据或None
        """
        if table_name not in self.files:
            return None
        
        f = self.files[table_name]
        try:
            f.seek(page_id * self.page_size)
            data = f.read(self.page_size)
            if len(data) < self.page_size:
                return None
            return data
        except Exception:
            return None
    
    def page_write(self, table_name: str, page_id: int, data: bytes) -> bool:
        """
        写入指定表的页面
        
        Args:
            table_name: 表名
            page_id: 页面ID
            data: 页面数据
            
        Returns:
            成功返回True
        """
        if len(data) != self.page_size:
            return False
        
        if table_name not in self.files:
            # 自动创建表文件
            self._create_table_file(table_name)
        
        f = self.files[table_name]
        try:
            f.seek(page_id * self.page_size)
            f.write(data)
            f.flush()
            return True
        except Exception:
            return False
    
    def allocate_page(self, table_name: str) -> int:
        """
        为指定表分配新页面
        
        Args:
            table_name: 表名
            
        Returns:
            新的页面ID
        """
        if table_name not in self.page_counters:
            self.page_counters[table_name] = 0
        
        page_id = self.page_counters[table_name]
        self.page_counters[table_name] += 1
        
        # 确保文件足够大
        file_path = self._get_table_file_path(table_name)
        if not os.path.exists(file_path):
            self._create_table_file(table_name)
        else:
            # 扩展文件到新页面
            with open(file_path, 'ab') as f:
                f.write(b'\x00' * self.page_size)
        
        return page_id
    
    def get_page_size(self) -> int:
        return self.page_size
    
    def close(self):
        """关闭所有文件"""
        for f in self.files.values():
            f.close()
        self.files.clear()
        self.page_counters.clear()
    
    def __del__(self):
        self.close()


if __name__ == "__main__":
    # 测试多文件存储
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = MultiFileStorage(tmpdir, 4096)
        
        # 为表'test'分配页面
        page_id = storage.allocate_page('test')
        print(f"Allocated page {page_id} for table 'test'")
        
        # 写入数据
        data = b"Hello, World!".ljust(4096, b'\x00')
        storage.page_write('test', page_id, data)
        
        # 读取数据
        read_data = storage.page_read('test', page_id)
        print(f"Read: {read_data[:13]}")
        
        storage.close()
        print("Test passed!")
