"""
简单的表存储包装器（带系统表持久化）

基于StorageEngine构建表级别的记录存储，并通过系统表(__tables__, __columns__)
持久化维护表元数据。

系统表存储策略：
- Page 0: __tables__ (JSON格式)
- Page 1: __columns__ (JSON格式)
"""

from typing import Optional, List, Dict, Any, Iterator
from core.storage_interface import StorageEngine
from .table_manager import TableMetadata, TableRecordManager, Record
from .persistent_system_tables import PersistentSystemTables


class SimpleTableStorage:
    """表存储管理器（集成持久化系统表）"""
    
    def __init__(self, storage_engine: StorageEngine):
        """
        初始化表存储
        
        Args:
            storage_engine: 底层存储引擎（页面级别）
        """
        self.storage = storage_engine
        self.sys_mgr = PersistentSystemTables(storage_engine)
        
        # 普通表缓存 (表名 -> TableMetadata)
        self.tables: Dict[str, TableMetadata] = {}
        self.table_managers: Dict[str, TableRecordManager] = {}
        
        # 启动时从系统表加载已有表的元数据
        self._load_tables_from_sys()
    
    def recover_from_wal(self, wal_manager):
        """
        从WAL恢复数据库状态（逻辑日志重放）
        
        根据WAL日志重做已提交事务，撤销未提交事务
        
        Args:
            wal_manager: WALManager实例（必须是已打开的）
        """
        if not wal_manager:
            return
        
        print("\n" + "="*60)
        print("SimpleStorage: 执行WAL恢复...")
        print("="*60)
        
        # 分析WAL文件
        analysis = wal_manager.analyze_recovery()
        
        if analysis['status'] == 'fresh':
            print("ℹ️  无WAL文件，跳过恢复")
            return
        
        logs = analysis['logs']
        active_tids = set(analysis['active_transactions'])
        
        print(f"📋 恢复分析: total_logs={len(logs)}, active_txns={len(active_tids)}")
        
        # 阶段1: 重做(Redo) - 重放所有数据修改日志（幂等）
        redo_count = 0
        for log in logs:
            if log.type.name in ('INSERT', 'UPDATE', 'DELETE'):
                if self._replay_log(log):
                    redo_count += 1
        
        print(f"✅ Redo阶段: 应用了 {redo_count} 条日志")
        
        # 阶段2: 撤销(Undo) - 回滚未提交事务
        undo_count = 0
        logs_to_undo = [log for log in logs if log.tid in active_tids and log.type.name in ('INSERT', 'UPDATE', 'DELETE')]
        logs_to_undo.sort(key=lambda x: x.lsn, reverse=True)
        
        for log in logs_to_undo:
            if self._undo_replay_log(log):
                undo_count += 1
        
        print(f"✅ Undo阶段: 回滚了 {undo_count} 条日志")
        
        # 刷新缓存
        # 检查存储引擎是否有集成的缓冲区池
        if hasattr(self.storage, 'buffer_pool') and self.storage.buffer_pool:
            self.storage.buffer_pool.flush_all()
        elif hasattr(self.storage, 'flush_all'):
            self.storage.flush_all()
        
        print("="*60)
        print("🎯 SimpleStorage恢复完成")
        print("="*60)
    
    def _replay_log(self, log):
        """重放单个逻辑日志记录（使用表管理器接口）"""
        try:
            import struct
            import json
            from core.wal import LogType
            
            # 解析表名和JSON数据
            offset = 0
            table_len = struct.unpack('<H', log.payload[offset:offset+2])[0]
            offset += 2
            table_name = log.payload[offset:offset+table_len].decode('utf-8')
            offset += table_len
            data_len = struct.unpack('<I', log.payload[offset:offset+4])[0]
            offset += 4
            data_json = log.payload[offset:offset+data_len].decode('utf-8')
            record_data = json.loads(data_json)
            
            # 获取表管理器
            if table_name not in self.table_managers:
                print(f"⚠️  表 '{table_name}' 不存在，跳过日志LSN={log.lsn}")
                return False
            
            manager = self.table_managers[table_name]
            if manager is None:
                return False
            
            # 根据日志类型执行相应操作
            if log.type == LogType.INSERT:
                manager.insert_record(record_data)
                return True
            
            elif log.type == LogType.UPDATE:
                # UPDATE逻辑: 根据主键更新记录
                if 'id' in record_data:
                    # 使用完整记录数据更新
                    manager.update_record(record_data['id'], record_data)
                    return True
                return False
            
            elif log.type == LogType.DELETE:
                # DELETE逻辑: 根据主键删除
                if 'id' in record_data:
                    manager.delete_record(record_data['id'])
                    return True
                return False
            
            return False
        except Exception as e:
            print(f"⚠️  重放日志LSN={log.lsn}失败: {e}")
            return False
    
    def _undo_replay_log(self, log):
        """撤销日志重放（逆向操作）"""
        try:
            import struct
            import json
            from core.wal import LogType
            
            # 解析表名和JSON数据
            offset = 0
            table_len = struct.unpack('<H', log.payload[offset:offset+2])[0]
            offset += 2
            table_name = log.payload[offset:offset+table_len].decode('utf-8')
            offset += table_len
            data_len = struct.unpack('<I', log.payload[offset:offset+4])[0]
            offset += 4
            data_json = log.payload[offset:offset+data_len].decode('utf-8')
            record_data = json.loads(data_json)
            
            # 获取表管理器
            if table_name not in self.table_managers:
                return False
            
            manager = self.table_managers[table_name]
            if manager is None:
                return False
            
            # 逆向操作
            if log.type == LogType.INSERT:
                # INSERT的UNDO: 删除插入的记录
                if 'id' in record_data:
                    manager.delete_record(record_data['id'])
                    return True
                return False
            
            elif log.type == LogType.UPDATE:
                # UPDATE的UNDO: 需要旧值！当前记录数据是新值，无法撤销
                # 这是逻辑日志格式的局限性：需要记录前镜像
                print(f"⚠️  UPDATE撤销需要旧值（前镜像）- LSN={log.lsn}")
                return False
            
            elif log.type == LogType.DELETE:
                # DELETE的UNDO: 重新插入删除的记录
                manager.insert_record(record_data)
                return True
            
            return False
        except Exception as e:
            print(f"⚠️  撤销日志LSN={log.lsn}失败: {e}")
            return False
    
    def _load_tables_from_sys(self):
        """从系统表加载所有表的定义"""
        tables = self.sys_mgr.list_all_tables()
        for table_rec in tables:
            table_id = table_rec.get('table_id')
            table_name = table_rec.get('table_name')
            root_page = table_rec.get('root_page')
            
            # 获取该表的列定义
            cols_records = self.sys_mgr.get_columns_for_table(table_id)
            columns = []
            for col_rec in cols_records:
                columns.append({
                    'name': col_rec.get('column_name'),
                    'type': col_rec.get('data_type'),
                    'nullable': bool(col_rec.get('nullable')),
                    'primary_key': bool(col_rec.get('primary_key')),
                })
            
            # 创建TableMetadata对象
            table_meta = TableMetadata(table_name, columns)
            table_meta.table_id = table_id  # 附加系统表ID
            
            self.tables[table_name] = table_meta
            
            # 创建表管理器（使用系统表中存储的root_page）
            if root_page is not None:
                manager = TableRecordManager(self.storage, table_meta, root_page)
                self.table_managers[table_name] = manager
            else:
                self.table_managers[table_name] = None
    
    def create_table(self, table_name: str, columns: List[Dict[str, Any]]) -> TableMetadata:
        """
        创建新表
        
        1. 分配数据页面
        2. 在__tables__中插入一条记录
        3. 在__columns__中为每列插入记录
        4. 创建TableRecordManager
        """
        if table_name in self.tables:
            raise ValueError(f"表 '{table_name}' 已存在")
        
        # 分配数据页面
        initial_page = self.storage.allocate_page()
        page_size = self.storage.get_page_size()
        self.storage.page_write(initial_page, b'\x00' * page_size)
        
        # 创建表记录管理器
        table_meta = TableMetadata(table_name, columns)
        manager = TableRecordManager(self.storage, table_meta, initial_page)
        
        # 写入系统表
        import datetime
        created_at = datetime.datetime.now().isoformat()
        table_id = self.sys_mgr.add_table(table_name, initial_page, created_at)
        
        # 写入列定义
        for position, col_def in enumerate(columns):
            column_id = self.sys_mgr.add_column(
                table_id=table_id,
                column_name=col_def['name'],
                data_type=col_def['type'],
                nullable=col_def.get('nullable', True),
                primary_key=col_def.get('primary_key', False),
                position=position
            )
        
        # 缓存
        table_meta.table_id = table_id
        self.tables[table_name] = table_meta
        self.table_managers[table_name] = manager
        
        return table_meta
    
    def drop_table(self, table_name: str):
        """删除表"""
        if table_name not in self.tables:
            raise ValueError(f"表 '{table_name}' 不存在")
        
        table_meta = self.tables[table_name]
        table_id = getattr(table_meta, 'table_id', None)
        
        # 关闭管理器
        if table_name in self.table_managers:
            self.table_managers[table_name].close()
            del self.table_managers[table_name]
        
        # 从系统表删除
        if table_id is not None:
            self.sys_mgr.remove_table(table_name)
        
        # 清理缓存
        del self.tables[table_name]
    
    def get_table_metadata(self, table_name: str) -> Optional[TableMetadata]:
        """获取表元数据"""
        return self.tables.get(table_name)
    
    def get_table_manager(self, table_name: str) -> Optional[TableRecordManager]:
        """获取表记录管理器"""
        manager = self.table_managers.get(table_name)
        if manager is None and table_name in self.tables:
            # 惰性初始化：创建管理器
            table_meta = self.tables[table_name]
            table_rec = self.sys_mgr.find_table_by_name(table_name)
            if table_rec:
                root_page = table_rec.get('root_page')
                if root_page is not None:
                    manager = TableRecordManager(self.storage, table_meta, root_page)
                    self.table_managers[table_name] = manager
        return manager
    
    def scan_table(self, table_name: str) -> Iterator[Any]:
        """扫描表记录"""
        manager = self.get_table_manager(table_name)
        if manager is None:
            return iter([])
        return manager.scan_all()
    
    def close(self):
        """关闭所有表管理器"""
        # 先持久化系统表
        self.sys_mgr.close()
        
        # 关闭表管理器
        for manager in self.table_managers.values():
            if manager:
                manager.close()
        self.tables.clear()
        self.table_managers.clear()


class SimpleStorageEngine(StorageEngine):
    """包装的存储引擎，集成SimpleTableStorage和系统表"""
    
    # 预留前2个页面给系统表
    RESERVED_PAGES = 2
    
    def __init__(self, storage_engine: StorageEngine):
        """
        初始化
        
        Args:
            storage_engine: 实际存储引擎实例
        """
        self.engine = storage_engine
        self.table_storage = SimpleTableStorage(storage_engine)
        
        # 初始化时预留系统表页面（如果尚未分配）
        self._reserve_system_pages()
    
    def _reserve_system_pages(self):
        """确保前RESERVED_PAGES个页面已分配，避免allocate_page使用"""
        for page_id in range(self.RESERVED_PAGES):
            existing = self.engine.page_read(page_id)
            if existing is None:
                # 分配空页面
                page_size = self.engine.get_page_size()
                self.engine.page_write(page_id, b'\x00' * page_size)
    
    # 委托所有StorageEngine方法给self.engine
    def page_read(self, page_id: int) -> Optional[bytes]:
        return self.engine.page_read(page_id)
    
    def page_write(self, page_id: int, data: bytes) -> bool:
        return self.engine.page_write(page_id, data)
    
    def allocate_page(self) -> int:
        """分配页面，跳过预留的系统表页面"""
        page_id = self.engine.allocate_page()
        # 如果分配的页面在预留范围内，跳过它
        while page_id < self.RESERVED_PAGES:
            # 再次调用allocate_page获取下一个
            page_id = self.engine.allocate_page()
        return page_id
    
    def get_page_size(self) -> int:
        return self.engine.get_page_size()
    
    def close(self):
        self.table_storage.close()
        if hasattr(self.engine, 'close'):
            self.engine.close()


if __name__ == "__main__":
    from core.storage_interface import InMemoryStorage
    
    storage_engine = InMemoryStorage(4096)
    simple_storage = SimpleStorageEngine(storage_engine)
    
    # 创建表
    columns = [
        {'name': 'id', 'type': 'INTEGER', 'nullable': False},
        {'name': 'name', 'type': 'TEXT', 'nullable': False},
    ]
    
    simple_storage.table_storage.create_table('test', columns)
    print("表创建成功")
    
    # 插入记录
    manager = simple_storage.table_storage.get_table_manager('test')
    record_id = manager.insert_record({'id': 1, 'name': 'Alice'})
    print(f"插入记录ID: {record_id}")
    
    # 扫描
    for rec in manager.scan_all():
        print(f"记录: {rec.values}")
    
    simple_storage.close()
    print("测试通过")
