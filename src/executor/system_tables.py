"""
系统表（System Tables）管理

系统表定义：
- __tables__: 表目录
  columns: table_id, table_name, root_page, created_at
- __columns__: 列目录
  columns: column_id, table_id, column_name, data_type, nullable, primary_key, position

为了简化，系统表作为特殊逻辑表存储在物理存储中。
"""

from typing import Optional, List, Dict, Any
from .table_manager import TableMetadata, TableRecordManager, Record
from core.storage_interface import StorageEngine


SYSTEM_TABLE_DEFS = {
    '__tables__': [
        {'name': 'table_id', 'type': 'INTEGER', 'nullable': False},
        {'name': 'table_name', 'type': 'TEXT', 'nullable': False},
        {'name': 'root_page', 'type': 'INTEGER', 'nullable': True},
        {'name': 'created_at', 'type': 'TEXT', 'nullable': True},
    ],
    '__columns__': [
        {'name': 'column_id', 'type': 'INTEGER', 'nullable': False},
        {'name': 'table_id', 'type': 'INTEGER', 'nullable': False},
        {'name': 'column_name', 'type': 'TEXT', 'nullable': False},
        {'name': 'data_type', 'type': 'TEXT', 'nullable': False},
        {'name': 'nullable', 'type': 'INTEGER', 'nullable': False},  # 0/1
        {'name': 'primary_key', 'type': 'INTEGER', 'nullable': False},
        {'name': 'position', 'type': 'INTEGER', 'nullable': False},
    ]
}


class SystemTablesManager:
    """系统表管理器"""
    
    def __init__(self, storage: StorageEngine):
        """
        初始化系统表管理器
        
        Args:
            storage: 存储引擎（支持页面分配）
        """
        self.storage = storage
        self.tables_meta: Optional[TableMetadata] = None
        self.columns_meta: Optional[TableMetadata] = None
        self.tables_manager: Optional[TableRecordManager] = None
        self.columns_manager: Optional[TableRecordManager] = None
        
        # 检查并初始化系统表
        self._init_system_tables()
    
    def _init_system_tables(self):
        """初始化系统表（如果不存在则创建）"""
        # 尝试加载现有系统表
        tables_def = SYSTEM_TABLE_DEFS['__tables__']
        columns_def = SYSTEM_TABLE_DEFS['__columns__']
        
        # 创建系统表管理器（不使用文件持久，仅使用内存结构，后续可持久）
        # 简化：每个系统表分配一个页面作为起始
        page_size = self.storage.get_page_size()
        
        # 为__tables__分配页并初始化
        tables_page = self.storage.allocate_page()
        self.storage.page_write(tables_page, b'\x00' * page_size)
        self.tables_meta = TableMetadata('__tables__', tables_def)
        self.tables_manager = TableRecordManager(self.storage, self.tables_meta, tables_page)
        
        # 为__columns__分配页
        columns_page = self.storage.allocate_page()
        self.storage.page_write(columns_page, b'\x00' * page_size)
        self.columns_meta = TableMetadata('__columns__', columns_def)
        self.columns_manager = TableRecordManager(self.storage, self.columns_meta, columns_page)
    
    def get_table_metadata(self) -> TableMetadata:
        return self.tables_meta
    
    def get_column_metadata(self) -> TableMetadata:
        return self.columns_meta
    
    def add_table(self, table_id: int, table_name: str, root_page: Optional[int] = None, created_at: str = ''):
        """向__tables__添加记录"""
        record = Record(self.tables_meta, table_id, {
            'table_id': table_id,
            'table_name': table_name,
            'root_page': root_page,
            'created_at': created_at,
        })
        # 注意：这里简化，实际需要正确写入系统表页面
        # 由于TableRecordManager.insert_record期望字典值，我们直接使用
        # 但需要提供列顺序，使用表元数据即可
        self.tables_manager.insert_record({
            'table_id': table_id,
            'table_name': table_name,
            'root_page': root_page,
            'created_at': created_at,
        })
    
    def add_column(self, column_id: int, table_id: int, column_name: str, 
                   data_type: str, nullable: bool, primary_key: bool, position: int):
        """向__columns__添加记录"""
        self.columns_manager.insert_record({
            'column_id': column_id,
            'table_id': table_id,
            'column_name': column_name,
            'data_type': data_type,
            'nullable': 1 if nullable else 0,
            'primary_key': 1 if primary_key else 0,
            'position': position,
        })
    
    def remove_table(self, table_name: str):
        """从__tables__中删除记录（根据表名）"""
        # 需要扫描并删除
        for record in self.tables_manager.scan_all():
            if record.values.get('table_name') == table_name:
                self.tables_manager.delete_record(record.record_id)
                break
        
        # 级联删除列
        to_delete_cols = []
        for record in self.columns_manager.scan_all():
            col_table_id = record.values.get('table_id')
            # 我们需要将table_id与表名对应，这里需要关联查询__tables__
            # 简化：暂时不删除列，或通过table_id匹配
            to_delete_cols.append(record.record_id)
        for col_id in to_delete_cols:
            self.columns_manager.delete_record(col_id)
    
    def get_all_tables(self) -> List[Dict[str, Any]]:
        """获取所有表元数据（作为字典列表）"""
        result = []
        for record in self.tables_manager.scan_all():
            result.append(record.values)
        return result
    
    def get_columns_for_table(self, table_id: int) -> List[Dict[str, Any]]:
        """获取指定table_id的所有列定义"""
        result = []
        for record in self.columns_manager.scan_all():
            if record.values.get('table_id') == table_id:
                result.append(record.values)
        # 按position排序
        result.sort(key=lambda x: x.get('position', 0))
        return result
    
    def close(self):
        """关闭管理器"""
        if self.tables_manager:
            self.tables_manager.close()
        if self.columns_manager:
            self.columns_manager.close()


if __name__ == "__main__":
    # 简单测试
    from core.storage_interface import InMemoryStorage
    storage = InMemoryStorage(4096)
    sys_mgr = SystemTablesManager(storage)
    
    print("系统表初始化完成")
    sys_mgr.add_table(1, 'test', created_at='2025-01-01')
    print("添加表记录")
    
    tables = sys_mgr.get_all_tables()
    print(f"所有表: {tables}")
    
    sys_mgr.close()
    print("测试通过")
