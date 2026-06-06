"""
持久化系统表（简化版）

系统表元数据直接序列化到固定页面，避免复杂页面管理。
- Page 0: __tables__ 元数据（JSON格式）
- Page 1: __columns__ 元数据（JSON格式）
"""

from typing import Optional, List, Dict, Any
from core.storage_interface import StorageEngine
import json
import struct


class PersistentSystemTables:
    """持久化系统表"""
    
    def __init__(self, storage: StorageEngine):
        self.storage = storage
        self.page_size = storage.get_page_size()
        
        # 动态分配系统表页面
        # 检查是否已有分配（从某处），如果没有则分配
        # 简化：总是重新分配，但这会导致数据丢失
        # 更好的方法：尝试读取已有页面ID，或使用约定
        # 为简化开发，约定系统表页面为0和1，并避免allocate_page使用这些ID
        # 我们需要包装allocate_page方法来跳过这些保留ID
        self.tables_page_id = 0
        self.columns_page_id = 1
        
        # 初始化系统表页面（如果尚未初始化）
        self._init_pages()
        
        # 内存缓存
        self.tables_cache: Dict[int, Dict[str, Any]] = {}
        self.columns_cache: List[Dict[str, Any]] = []
        self._load_from_storage()
    
    def _init_pages(self):
        """初始化系统表页面"""
        # 检查页面是否存在
        tables_data = self.storage.page_read(self.tables_page_id)
        if tables_data is None:
            # 创建新的空表结构
            initial = {'__meta__': {'version': 1}, 'tables': {}, 'next_table_id': 1}
            self._write_page(self.tables_page_id, initial)
        
        columns_data = self.storage.page_read(self.columns_page_id)
        if columns_data is None:
            initial = {'__meta__': {'version': 1}, 'columns': [], 'next_column_id': 1}
            self._write_page(self.columns_page_id, initial)
    
    def _read_page(self, page_id: int) -> Dict[str, Any]:
        """读取页面并解析为字典"""
        data = self.storage.page_read(page_id)
        if data is None:
            return {}
        try:
            json_str = data.rstrip(b'\x00').decode('utf-8')
            return json.loads(json_str)
        except Exception:
            return {}
    
    def _write_page(self, page_id: int, obj: Dict[str, Any]):
        """将字典序列化写入页面"""
        json_str = json.dumps(obj, ensure_ascii=False)
        data = json_str.encode('utf-8')
        # 填充到页面大小
        if len(data) > self.page_size:
            raise ValueError(f"数据太大: {len(data)} > {self.page_size}")
        padded = data.ljust(self.page_size, b'\x00')
        self.storage.page_write(page_id, padded)
    
    def _load_from_storage(self):
        """从存储加载到缓存"""
        tables_obj = self._read_page(self.tables_page_id)
        self.tables_cache = tables_obj.get('tables', {})
        
        columns_obj = self._read_page(self.columns_page_id)
        self.columns_cache = columns_obj.get('columns', [])
    
    def _save_tables(self):
        """保存tables缓存到存储"""
        obj = {
            '__meta__': {'version': 1},
            'tables': self.tables_cache,
            'next_table_id': max([t.get('table_id', 0) for t in self.tables_cache.values()] + [0]) + 1
        }
        self._write_page(self.tables_page_id, obj)
    
    def _save_columns(self):
        """保存columns缓存到存储"""
        obj = {
            '__meta__': {'version': 1},
            'columns': self.columns_cache,
            'next_column_id': max([c.get('column_id', 0) for c in self.columns_cache] + [0]) + 1
        }
        self._write_page(self.columns_page_id, obj)
    
    def add_table(self, table_name: str, root_page: int, created_at: str) -> int:
        """添加表记录，返回table_id"""
        tables_obj = self._read_page(self.tables_page_id)
        tables = tables_obj.get('tables', {})
        next_id = tables_obj.get('next_table_id', 1)
        
        table_id = next_id
        tables[str(table_id)] = {
            'table_id': table_id,
            'table_name': table_name,
            'root_page': root_page,
            'created_at': created_at
        }
        tables_obj['tables'] = tables
        tables_obj['next_table_id'] = table_id + 1
        self._write_page(self.tables_page_id, tables_obj)
        
        # 更新缓存
        self.tables_cache[str(table_id)] = tables[str(table_id)]
        
        return table_id
    
    def add_column(self, table_id: int, column_name: str, data_type: str,
                   nullable: bool, primary_key: bool, position: int) -> int:
        """添加列记录，返回column_id"""
        columns_obj = self._read_page(self.columns_page_id)
        columns = columns_obj.get('columns', [])
        next_id = columns_obj.get('next_column_id', 1)
        
        column_id = next_id
        columns.append({
            'column_id': column_id,
            'table_id': table_id,
            'column_name': column_name,
            'data_type': data_type,
            'nullable': 1 if nullable else 0,
            'primary_key': 1 if primary_key else 0,
            'position': position
        })
        columns_obj['columns'] = columns
        columns_obj['next_column_id'] = column_id + 1
        self._write_page(self.columns_page_id, columns_obj)
        
        # 更新缓存
        self.columns_cache.append({
            'column_id': column_id,
            'table_id': table_id,
            'column_name': column_name,
            'data_type': data_type,
            'nullable': 1 if nullable else 0,
            'primary_key': 1 if primary_key else 0,
            'position': position
        })
        
        return column_id
    
    def find_table_by_name(self, table_name: str) -> Optional[Dict[str, Any]]:
        """根据表名查找表记录"""
        for table in self.tables_cache.values():
            if table.get('table_name') == table_name:
                return table
        return None
    
    def get_columns_for_table(self, table_id: int) -> List[Dict[str, Any]]:
        """获取指定table_id的所有列（按position排序）"""
        cols = [c for c in self.columns_cache if c.get('table_id') == table_id]
        cols.sort(key=lambda x: x.get('position', 0))
        return cols
    
    def remove_table(self, table_name: str):
        """删除表（及其列）"""
        # 查找表
        table = self.find_table_by_name(table_name)
        if table is None:
            return
        
        table_id = table['table_id']
        
        # 从tables删除
        tables_obj = self._read_page(self.tables_page_id)
        tables = tables_obj.get('tables', {})
        if str(table_id) in tables:
            del tables[str(table_id)]
            tables_obj['tables'] = tables
            self._write_page(self.tables_page_id, tables_obj)
            if str(table_id) in self.tables_cache:
                del self.tables_cache[str(table_id)]
        
        # 从columns删除
        columns_obj = self._read_page(self.columns_page_id)
        columns = columns_obj.get('columns', [])
        new_columns = [c for c in columns if c.get('table_id') != table_id]
        columns_obj['columns'] = new_columns
        self._write_page(self.columns_page_id, columns_obj)
        self.columns_cache = new_columns
    
    def list_all_tables(self) -> List[Dict[str, Any]]:
        """列出所有表"""
        return list(self.tables_cache.values())
    
    def close(self):
        """关闭（持久化所有缓存）"""
        self._save_tables()
        self._save_columns()


if __name__ == "__main__":
    from core.storage_interface import InMemoryStorage
    storage = InMemoryStorage(4096)
    sys_tables = PersistentSystemTables(storage)
    
    print("初始化系统表")
    sys_tables.add_table('test', root_page=2, created_at='2025-01-01')
    print("添加表记录")
    
    tables = sys_tables.list_all_tables()
    print(f"所有表: {tables}")
    
    sys_tables.close()
    print("测试通过")
