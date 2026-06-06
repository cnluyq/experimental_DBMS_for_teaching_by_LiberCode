"""
执行上下文（ExecutionContext）

管理查询执行过程中的上下文信息：
- 事务状态
- WAL日志
- 缓冲区管理器
- 存储引擎
- 执行统计信息
- 表记录管理器缓存
"""

from typing import Optional, Any, Dict, Iterator, List
from core.buffer import BufferPool
from core.wal import WALManager
from core.storage_interface import StorageEngine
from .simple_storage import SimpleTableStorage, TableMetadata


class ExecutionContext:
    """查询执行上下文"""
    
    def __init__(self, 
                 storage_engine: StorageEngine,
                 buffer_pool: Optional[BufferPool] = None,
                 wal: Optional[WALManager] = None,
                 transaction_id: Optional[int] = None):
        """
        初始化执行上下文
        
        Args:
            storage_engine: 存储引擎实例（可能是SimpleTableStorage包装器）
            buffer_pool: 缓冲区池实例（可选）
            wal: WAL日志实例（可选）
            transaction_id: 事务ID（可选，None表示非事务模式）
        """
        self.storage = storage_engine
        self.buffer_pool = buffer_pool
        self.wal = wal
        self.transaction_id = transaction_id
        
        # 执行统计信息
        self.stats = {
            'rows_read': 0,
            'rows_written': 0,
            'pages_read': 0,
            'pages_written': 0,
            'execution_time_ms': 0,
        }
        
        # 检查存储引擎是否集成了SimpleTableStorage
        if hasattr(storage_engine, 'table_storage'):
            self.table_storage = storage_engine.table_storage
            self.table_metadata = self.table_storage.tables
            self.table_managers = self.table_storage.table_managers
        else:
            self.table_storage = None
            self.table_metadata = {}
            self.table_managers = {}
    
    def get_table_manager(self, table_name: str):
        """
        获取表的记录管理器
        
        Args:
            table_name: 表名
            
        Returns:
            TableRecordManager实例
            
        Raises:
            ValueError: 如果表不存在
        """
        if self.table_storage is None:
            raise RuntimeError("存储引擎未集成的表管理功能")
        
        if table_name not in self.table_metadata:
            raise ValueError(f"表 '{table_name}' 不存在")
        
        return self.table_managers[table_name]
    
    def create_table(self, table_name: str, columns: List[Dict[str, Any]]):
        """
        创建新表
        
        Args:
            table_name: 表名
            columns: 列定义列表
            
        Returns:
            TableMetadata对象
        """
        if self.table_storage is None:
            raise RuntimeError("存储引擎未集成的表管理功能")
        
        table_meta = self.table_storage.create_table(table_name, columns)
        # 更新缓存引用
        self.table_metadata[table_name] = table_meta
        self.table_managers[table_name] = self.table_storage.table_managers[table_name]
        return table_meta
    
    def drop_table(self, table_name: str):
        """
        删除表
        
        Args:
            table_name: 表名
        """
        if self.table_storage is None:
            raise RuntimeError("存储引擎未集成的表管理功能")
        
        self.table_storage.drop_table(table_name)
        # 清理缓存引用
        if table_name in self.table_metadata:
            del self.table_metadata[table_name]
        if table_name in self.table_managers:
            del self.table_managers[table_name]
    
    def scan_table(self, table_name: str) -> Iterator:
        """
        扫描表所有记录
        
        Args:
            table_name: 表名
            
        Returns:
            记录迭代器
        """
        if self.table_storage is None:
            raise RuntimeError("存储引擎未集成的表管理功能")
        
        manager = self.table_managers.get(table_name)
        if manager is None:
            return iter([])
        
        for record in manager.scan_all():
            self.increment_stats(rows_read=1)
            yield record
    
    def flush_all(self):
        """刷新所有脏页"""
        if self.buffer_pool:
            self.buffer_pool.flush_all()
    
    def increment_stats(self, **kwargs):
        """更新统计信息"""
        for key, value in kwargs.items():
            if key in self.stats:
                self.stats[key] += value
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息副本"""
        return self.stats.copy()
    
    def reset_stats(self):
        """重置统计信息"""
        for key in self.stats:
            self.stats[key] = 0
    
    # WAL日志方法

    def log_insert(self, table_name: str, record_data: Dict[str, Any]):
        """
        记录插入操作到WAL（逻辑记录）
        
        Args:
            table_name: 表名
            record_data: 插入的记录数据（字典）
        """
        if self.wal and self.transaction_id:
            import struct
            from core.wal import LogType
            import json
            
            # 序列化record_data为JSON
            data_json = json.dumps(record_data, ensure_ascii=False)
            payload_data = data_json.encode('utf-8')
            
            # payload格式: table_name_len(2), table_name, data_len(4), data
            table_bytes = table_name.encode('utf-8')
            payload = struct.pack('<H', len(table_bytes)) + table_bytes
            payload += struct.pack('<I', len(payload_data)) + payload_data
            
            prev_lsn = self.wal.active_transactions.get(self.transaction_id, 0)
            self.wal.append(self.transaction_id, LogType.INSERT, payload, prev_lsn)
    
    def log_delete(self, table_name: str, record_id: int, old_data: Dict[str, Any]):
        """
        记录删除操作到WAL
        
        Args:
            table_name: 表名
            record_id: 记录ID
            old_data: 删除前的记录数据
        """
        if self.wal and self.transaction_id:
            import struct
            from core.wal import LogType
            import json
            
            table_bytes = table_name.encode('utf-8')
            data_json = json.dumps(old_data, ensure_ascii=False)
            data_bytes = data_json.encode('utf-8')
            
            # payload格式: table_name_len(2), table_name, record_id(4), data_len(4), data
            payload = struct.pack('<H', len(table_bytes)) + table_bytes
            payload += struct.pack('<I', record_id)
            payload += struct.pack('<I', len(data_bytes)) + data_bytes
            
            prev_lsn = self.wal.active_transactions.get(self.transaction_id, 0)
            self.wal.append(self.transaction_id, LogType.DELETE, payload, prev_lsn)
    
    def log_update(self, table_name: str, record_id: int, old_values: Dict[str, Any], new_values: Dict[str, Any]):
        """
        记录更新操作到WAL（逻辑日志）
        
        Args:
            table_name: 表名
            record_id: 记录ID
            old_values: 旧值（字典）
            new_values: 新值（字典）
        """
        if self.wal and self.transaction_id:
            import struct
            from core.wal import LogType
            import json
            
            # 序列化old_values和new_values
            old_json = json.dumps(old_values, ensure_ascii=False)
            new_json = json.dumps(new_values, ensure_ascii=False)
            
            # payload格式: 
            # table_name_len(2), table_name, record_id(4), old_len(4), old_json, new_len(4), new_json
            table_bytes = table_name.encode('utf-8')
            payload = struct.pack('<H', len(table_bytes)) + table_bytes
            payload += struct.pack('<I', record_id)
            payload += struct.pack('<I', len(old_json)) + old_json.encode('utf-8')
            payload += struct.pack('<I', len(new_json)) + new_json.encode('utf-8')
            
            prev_lsn = self.wal.active_transactions.get(self.transaction_id, 0)
            self.wal.append(self.transaction_id, LogType.UPDATE, payload, prev_lsn)
    
    def close(self):
        """关闭执行上下文（刷新所有数据）"""
        self.flush_all()
        # 关闭所有表管理器
        for manager in self.table_managers.values():
            manager.close()
        # 注意：不关闭 wal，因为 executor 可能还需要使用它进行后续的事务操作
        # wal 的生命周期由创建它的组件管理（通常是顶层初始化）
