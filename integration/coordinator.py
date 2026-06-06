"""
模块协调器（ModuleCoordinator）

负责按依赖顺序初始化和组装所有数据库模块。
管理模块的生命周期，提供统一的关闭和清理。
"""

import os
import logging
from typing import Optional, Dict, Any, Tuple
from core.storage_interface import StorageEngine, SimpleFileStorage, InMemoryStorage
from core.buffer import BufferPool
from core.wal import WALManager
from parser.parser import Parser
from executor.executor import Executor
from .config import DatabaseConfig
from .system_schema import SystemSchema
from .database_storage import DatabaseStorage


class ModuleCoordinator:
    """模块协调器：管理所有模块的初始化和生命周期"""
    
    # 模块初始化顺序（必须满足依赖关系）
    INITIALIZATION_ORDER = [
        'storage',      # 1. 存储引擎（最底层）
        'buffer',       # 2. 缓冲区池（依赖存储）
        'wal',          # 3. WAL管理器（依赖存储）
        'db_storage',   # 4. 数据库存储层（整合系统表，包装storage）
        'parser',       # 5. SQL解析器（独立）
        'executor',     # 6. 执行引擎（依赖 db_storage, buffer, wal）
    ]
    
    def __init__(self, config: DatabaseConfig):
        """
        初始化协调器
        
        Args:
            config: 数据库配置
        """
        self.config = config
        self.logger = self._setup_logger()
        
        # 存储已初始化的模块实例
        self.modules: Dict[str, Any] = {}
        
        # 确保数据目录存在
        os.makedirs(config.data_dir, exist_ok=True)
        
        self.logger.info(f"ModuleCoordinator initialized with config: {config.to_dict()}")
    
    def _setup_logger(self) -> logging.Logger:
        """设置日志器"""
        logger = logging.getLogger('projo.integration')
        level = getattr(logging, self.config.log_level.upper(), logging.INFO)
        logger.setLevel(level)
        
        # 避免重复添加handler
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def initialize_all(self) -> Tuple[
        StorageEngine, 
        Optional[BufferPool], 
        Optional[WALManager], 
        DatabaseStorage,
        Executor
    ]:
        """
        按依赖顺序初始化所有模块
        
        Returns:
            (storage, buffer, wal, db_storage, executor) 元组
        """
        self.logger.info("Starting module initialization...")
        
        try:
            for module_name in self.INITIALIZATION_ORDER:
                self.logger.info(f"Initializing module: {module_name}")
                getattr(self, f'_init_{module_name}')()
            
            self.logger.info("All modules initialized successfully")
            
            return (
                self.modules['storage'],
                self.modules.get('buffer'),
                self.modules.get('wal'),
                self.modules['db_storage'],
                self.modules['executor']
            )
            
        except Exception as e:
            self.logger.error(f"Module initialization failed: {e}")
            self.shutdown_all()  # 清理已初始化的模块
            raise
    
    def _init_storage(self):
        """初始化存储引擎"""
        if self.config.storage_type == 'file':
            db_path = os.path.join(self.config.data_dir, 'projo_data.db')
            storage = SimpleFileStorage(db_path, self.config.page_size)
        elif self.config.storage_type == 'memory':
            storage = InMemoryStorage(self.config.page_size)
        else:
            raise ValueError(f"Unknown storage type: {self.config.storage_type}")
        
        self.modules['storage'] = storage
        self.logger.info(f"Storage engine initialized: {type(storage).__name__}")
    
    def _init_buffer(self):
        """初始化缓冲区池"""
        storage = self.modules['storage']
        buffer = BufferPool(
            num_frames=self.config.buffer_pool_size,
            storage_engine=storage,
            logger=self.logger
        )
        self.modules['buffer'] = buffer
        self.logger.info(f"Buffer pool initialized: {self.config.buffer_pool_size} frames")
    
    def _init_wal(self):
        """初始化WAL管理器（如果启用）"""
        if not self.config.wal_enabled:
            self.modules['wal'] = None
            self.logger.info("WAL disabled by config")
            return
        
        storage = self.modules['storage']
        wal_path = os.path.join(self.config.data_dir, self.config.wal_file)
        wal = WALManager(wal_path, self.config.page_size)
        
        if not wal.open():
            raise RuntimeError(f"Failed to open WAL file: {wal_path}")
        
        self.modules['wal'] = wal
        self.logger.info(f"WAL manager initialized: {wal_path}")
    
    def _init_db_storage(self):
        """初始化数据库存储层（DatabaseStorage）"""
        storage = self.modules['storage']
        data_dir = self.config.data_dir
        
        # 创建DatabaseStorage（整合系统表和表管理）
        db_storage = DatabaseStorage(storage, data_dir)
        
        self.modules['db_storage'] = db_storage
        self.logger.info("Database storage (with system tables) initialized")
    
    def _init_transaction_manager(self):
        """初始化事务管理器"""
        # 当前事务管理由Executor内部处理
        # 这里可以预留未来独立事务管理器的接口
        self.logger.info("Transaction manager (managed by executor)")
    
    def _init_parser(self):
        """初始化SQL解析器"""
        parser = Parser
        self.modules['parser'] = parser
        self.logger.info("SQL parser initialized")
    
    def _init_executor(self):
        """初始化执行引擎"""
        # 使用db_storage作为存储引擎（包装了系统表）
        db_storage = self.modules.get('db_storage')
        if db_storage is None:
            raise RuntimeError("DatabaseStorage (db_storage) must be initialized before executor")
        
        buffer = self.modules.get('buffer')
        wal = self.modules.get('wal')
        
        executor = Executor(
            storage_engine=db_storage,
            buffer_pool=buffer,
            wal=wal
        )
        
        self.modules['executor'] = executor
        self.logger.info("Executor initialized")
    
    def get_module(self, name: str) -> Any:
        """获取指定模块实例"""
        return self.modules.get(name)
    
    def shutdown_all(self):
        """关闭所有模块（优雅关闭）"""
        self.logger.info("Shutting down all modules...")
        
        # 关闭顺序：反向进行，确保数据安全
        
        # 1. 关闭executor（预留）
        if 'executor' in self.modules:
            try:
                # executor无统一关闭方法，但可以清理缓存
                del self.modules['executor']
                self.logger.info("Executor unloaded")
            except Exception as e:
                self.logger.error(f"Error unloading executor: {e}")
        
        # 2. 关闭db_storage（包含系统表和表管理器）
        if 'db_storage' in self.modules:
            try:
                db_storage = self.modules['db_storage']
                if hasattr(db_storage, 'close'):
                    db_storage.close()
                del self.modules['db_storage']
                self.logger.info("Database storage closed")
            except Exception as e:
                self.logger.error(f"Error closing database storage: {e}")
        
        # 3. 关闭WAL
        if 'wal' in self.modules and self.modules['wal']:
            try:
                wal = self.modules['wal']
                wal.close()
                del self.modules['wal']
                self.logger.info("WAL closed")
            except Exception as e:
                self.logger.error(f"Error closing WAL: {e}")
        
        # 4. 关闭缓冲区池（写回所有脏页）
        if 'buffer' in self.modules:
            try:
                buffer = self.modules['buffer']
                buffer.shutdown()
                del self.modules['buffer']
                self.logger.info("Buffer pool shutdown")
            except Exception as e:
                self.logger.error(f"Error shutting down buffer pool: {e}")
        
        # 5. 关闭存储引擎
        if 'storage' in self.modules:
            try:
                storage = self.modules['storage']
                if hasattr(storage, 'close'):
                    storage.close()
                del self.modules['storage']
                self.logger.info("Storage engine closed")
            except Exception as e:
                self.logger.error(f"Error closing storage: {e}")
        
        self.logger.info("All modules shutdown complete")


def create_database(config: Optional[DatabaseConfig] = None) -> 'Database':
    """
    快速创建数据库实例（工厂函数）
    
    Args:
        config: 数据库配置，None则使用默认配置
        
    Returns:
        Database实例
    """
    if config is None:
        config = DatabaseConfig()
    
    coordinator = ModuleCoordinator(config)
    storage, buffer, wal, db_storage, executor = coordinator.initialize_all()
    
    return Database(coordinator, storage, buffer, wal, db_storage, executor)


class Database:
    """数据库主类（对外统一接口）"""
    
    def __init__(self, 
                 coordinator: ModuleCoordinator,
                 storage: StorageEngine,
                 buffer: Optional[BufferPool],
                 wal: Optional[WALManager],
                 db_storage: 'DatabaseStorage',
                 executor: Executor):
        """
        初始化数据库实例
        
        参数由ModuleCoordinator初始化完成后传入
        """
        self.coordinator = coordinator
        self.storage = storage
        self.buffer = buffer
        self.wal = wal
        self.db_storage = db_storage
        self.executor = executor
        self.logger = coordinator.logger
        
        # 事务状态
        self.in_transaction = False
        self.transaction_depth = 0
        
        self.logger.info("Database instance created")
    
    def execute(self, sql: str) -> Any:
        """
        执行SQL语句
        
        Args:
            sql: SQL语句字符串
            
        Returns:
            ResultSet或执行结果
        """
        try:
            # 解析SQL
            from parser.tokenizer import Tokenizer
            tokens = Tokenizer(sql).tokenize()
            ast = Parser(tokens).parse()
            
            # 如果处于自动提交模式且不在事务中，每个语句都是独立事务
            autocommit = self.coordinator.config.autocommit
            if autocommit and not self.in_transaction:
                # 注意：Executor内部的事务管理需要这样的包裹
                # 可能需要调整Executor的execute支持显式事务边界
                result = self._execute_with_autocommit(ast)
            else:
                result = self.executor.execute(ast)
            
            return result
            
        except Exception as e:
            self.logger.error(f"Execute failed: {e}")
            raise
    
    def _execute_with_autocommit(self, ast) -> Any:
        """自动提交模式下执行（包装事务）"""
        # 在autocommit模式下，每个SQL语句都应独立提交
        # 由于Executor当前设计可能内置了事务跟踪，我们需要包裹BEGIN/COMMIT
        # 暂时直接调用executor.execute，假设executor会处理
        
        # 更严谨的做法：先begin，再execute，然后commit
        # 但当前Executor的execute内部可能已处理
        return self.executor.execute(ast)
    
    def begin_transaction(self):
        """开始事务"""
        if self.transaction_depth == 0:
            # 调用executor的事务开始方法
            if hasattr(self.executor, 'start_transaction'):
                self.executor.start_transaction()
            else:
                # executor可能没有这个方法，做兼容处理
                self.logger.warning("Executor does not have start_transaction method")
            self.in_transaction = True
        self.transaction_depth += 1
        self.logger.debug(f"Transaction started, depth={self.transaction_depth}")
    
    def commit(self):
        """提交当前事务"""
        if self.transaction_depth > 0:
            self.transaction_depth -= 1
            if self.transaction_depth == 0:
                if hasattr(self.executor, 'commit_transaction'):
                    self.executor.commit_transaction()
                else:
                    self.logger.warning("Executor does not have commit_transaction method")
                self.in_transaction = False
            self.logger.debug(f"Transaction committed, depth={self.transaction_depth}")
    
    def rollback(self):
        """回滚当前事务"""
        if self.transaction_depth > 0:
            self.transaction_depth -= 1
            if self.transaction_depth == 0:
                if hasattr(self.executor, 'rollback_transaction'):
                    self.executor.rollback_transaction()
                else:
                    self.logger.warning("Executor does not have rollback_transaction method")
                self.in_transaction = False
            self.logger.debug(f"Transaction rolled back, depth={self.transaction_depth}")
    
    def shutdown(self):
        """优雅关闭数据库"""
        self.logger.info("Shutting down database...")
        
        # 如果有未提交的事务，先提交或回滚？当前选择回滚
        if self.in_transaction:
            self.logger.warning("Uncommitted transaction will be rolled back")
            self.rollback()
        
        # 刷新所有脏页
        if self.buffer:
            self.logger.info("Flushing buffer pool...")
            self.buffer.flush_all()
        
        # 强制WAL持久化（确保日志写磁盘）
        if self.wal:
            self.logger.info("Flushing WAL...")
            self.wal.force()
        
        # 关闭协调器（关闭所有模块）
        self.coordinator.shutdown_all()
        
        self.logger.info("Database shutdown complete")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取数据库统计信息"""
        stats = {
            'storage': None,
            'buffer': None,
            'wal': None,
            'executor': None
        }
        
        if hasattr(self.storage, 'get_stats'):
            stats['storage'] = self.storage.get_stats()
        if self.buffer:
            stats['buffer'] = self.buffer.get_buffer_stats()
        if self.wal:
            stats['wal'] = self.wal.get_stats()
        
        return stats