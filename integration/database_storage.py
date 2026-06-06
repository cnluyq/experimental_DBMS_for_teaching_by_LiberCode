"""
数据库存储层（DatabaseStorage）

整合底层存储引擎、系统表持久化和表记录管理。
对外提供统一的接口供Executor使用。
"""

from typing import Optional, Dict, List, Any, Iterator
from core.storage_interface import StorageEngine
from .system_schema import SystemSchema
from executor.table_manager import TableMetadata, TableRecordManager


class DatabaseStorage:
    """
    数据库存储统一接口
    
    将其设计为StorageEngine的装饰器，同时提供系统表和表管理功能。
    为兼容ExecutionContext，暴露table_storage属性指向自身。
    """
    
    def __init__(self, storage_engine: StorageEngine, data_dir: str):
        """
        初始化
        
        Args:
            storage_engine: 底层存储引擎（文件或内存）
            data_dir: 数据目录路径（用于系统表文件）
        """
        self.engine = storage_engine
        self.system = SystemSchema(data_dir)
        
        # 表缓存 (表名 -> TableMetadata)
        self.tables: Dict[str, TableMetadata] = {}
        self.table_managers: Dict[str, TableRecordManager] = {}
        
        # 从系统表加载已有表定义
        self._load_tables()
        
        # 兼容ExecutionContext: 提供table_storage属性
        self.table_storage = self
    
    def _load_tables(self):
        """从系统表加载所有表定义"""
        all_meta = self.system.get_all_metadata()
        for table_name, table_meta_dict in all_meta.items():
            # 转换为TableMetadata对象
            columns = table_meta_dict['columns']
            table_meta = TableMetadata(table_name, columns)
            # 附加额外字段
            table_meta.table_id = table_meta_dict.get('table_id')
            table_meta.created_at = table_meta_dict.get('created_at')
            # root_page
            root_page = table_meta_dict.get('root_page')
            table_meta.root_page = root_page
            
            self.tables[table_name] = table_meta
            
            # 如果有root_page，创建表管理器
            if root_page is not None:
                manager = TableRecordManager(self.engine, table_meta, root_page)
                self.table_managers[table_name] = manager
    
    def create_table(self, table_name: str, columns: List[Dict[str, Any]]) -> TableMetadata:
        """
        创建新表
        
        步骤:
        1. 分配数据页面
        2. 在系统表注册表定义（包含root_page）
        3. 创建表记录管理器
        """
        if table_name in self.tables:
            raise ValueError(f"表 '{table_name}' 已存在")
        
        # 分配数据页面
        initial_page = self.engine.allocate_page()
        page_size = self.engine.get_page_size()
        # 初始化页面（清零）
        self.engine.page_write(initial_page, b'\x00' * page_size)
        
        # 在系统表中创建表定义（传入root_page）
        table_meta_dict = self.system.create_table(table_name, columns, root_page=initial_page)
        
        # 创建TableMetadata对象
        table_meta = TableMetadata(table_name, columns)
        table_meta.table_id = table_meta_dict['table_id']
        table_meta.created_at = table_meta_dict['created_at']
        # 附加root_page到table_meta（可选）
        table_meta.root_page = initial_page
        
        # 创建表记录管理器
        manager = TableRecordManager(self.engine, table_meta, initial_page)
        
        # 缓存
        self.tables[table_name] = table_meta
        self.table_managers[table_name] = manager
        
        return table_meta
    
    def drop_table(self, table_name: str):
        """删除表"""
        if table_name not in self.tables:
            raise ValueError(f"表 '{table_name}' 不存在")
        
        # 关闭表管理器
        if table_name in self.table_managers:
            self.table_managers[table_name].close()
            del self.table_managers[table_name]
        
        # 从系统表删除
        self.system.drop_table(table_name)
        
        # 清理缓存
        del self.tables[table_name]
    
    def get_table_metadata(self, table_name: str) -> Optional[TableMetadata]:
        """获取表元数据"""
        return self.tables.get(table_name)
    
    def get_table_manager(self, table_name: str) -> Optional[TableRecordManager]:
        """获取表记录管理器（如果不存在则创建）"""
        if table_name not in self.tables:
            return None
        
        if table_name not in self.table_managers:
            # 惰性创建管理器：从系统表获取root_page
            # 但我们的系统表目前没有root_page字段
            # 我们可以尝试从table_metadata的附加字段或搜索数据页
            # 暂时不支持惰性创建，要求创建表时立即分配
            return None
        
        return self.table_managers[table_name]
    
    def scan_table(self, table_name: str) -> Iterator:
        """扫描表所有记录"""
        manager = self.get_table_manager(table_name)
        if manager is None:
            return iter([])
        return manager.scan_all()
    
    def close(self):
        """关闭存储
        
        关闭顺序：先关闭内部资源（表管理器、系统表），再关闭底层引擎
        这与 coordinator.py 的 shutdown_all() 反向关闭逻辑保持一致：
        - shutdown_all() 顺序：executor → db_storage → wal → buffer → storage
        - close() 顺序：_close_resources()（表管理器、系统表）→ 底层engine
        """
        # 先关闭系统表和表管理器
        self._close_resources()
        # 再关闭底层引擎
        if hasattr(self.engine, 'close'):
            self.engine.close()
    
    def _close_resources(self):
        """关闭内部资源（表管理器、系统表）"""
        for manager in self.table_managers.values():
            manager.close()
        self.table_managers.clear()
        self.tables.clear()
        self.system.close()
    
    # ============ StorageEngine 接口委托 ============
    # 使DatabaseStorage可以作为StorageEngine使用
    
    def page_read(self, page_id: int) -> Optional[bytes]:
        """读取页面"""
        return self.engine.page_read(page_id)
    
    def page_write(self, page_id: int, data: bytes) -> bool:
        """写入页面"""
        return self.engine.page_write(page_id, data)
    
    def allocate_page(self) -> int:
        """分配新页面"""
        return self.engine.allocate_page()
    
    def get_page_size(self) -> int:
        """获取页面大小"""
        return self.engine.get_page_size()
    
    def mark_dirty(self, page_id: int):
        """标记页面为脏（如果使用缓冲区池）"""
        if hasattr(self.engine, 'mark_dirty'):
            self.engine.mark_dirty(page_id)
    
    def flush_page(self, page_id: int):
        """刷新页面到磁盘"""
        if hasattr(self.engine, 'flush_page'):
            self.engine.flush_page(page_id)
    
    def flush_all(self):
        """刷新所有脏页"""
        if hasattr(self.engine, 'flush_all'):
            self.engine.flush_all()


if __name__ == "__main__":
    from core.storage_interface import InMemoryStorage
    
    engine = InMemoryStorage(4096)
    db_storage = DatabaseStorage(engine, "./test_data")
    
    # 创建表
    cols = [
        {'name': 'id', 'type': 'INTEGER', 'nullable': False},
        {'name': 'name', 'type': 'TEXT', 'nullable': False},
    ]
    table = db_storage.create_table('test', cols)
    print(f"创建表: {table.table_name}, table_id={table.table_id}")
    
    # 插入记录
    manager = db_storage.get_table_manager('test')
    rid = manager.insert_record({'id': 1, 'name': 'Alice'})
    print(f"插入记录ID: {rid}")
    
    # 查询
    for rec in manager.scan_all():
        print(f"记录: {rec.values}")
    
    db_storage.close()
    print("测试通过")