"""
数据库配置管理

管理运行时的配置参数，支持从文件和环境变量读取。
"""

import os
import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DatabaseConfig:
    """数据库配置"""
    # 数据目录
    data_dir: str = "./data"
    
    # 存储引擎
    storage_type: str = "file"  # "file" 或 "memory"
    page_size: int = 4096
    
    # 缓冲区池
    buffer_pool_size: int = 64  # 帧数
    
    # WAL日志
    wal_enabled: bool = True
    wal_file: str = "wal.log"
    wal_sync: bool = True  # 是否每个日志都fsync
    
    # 事务
    autocommit: bool = True
    
    # 系统表
    system_schema_file: str = "system_schema.json"
    
    # 日志级别
    log_level: str = "INFO"
    
    @classmethod
    def from_file(cls, filepath: str) -> 'DatabaseConfig':
        """从JSON文件加载配置"""
        with open(filepath, 'r') as f:
            data = json.load(f)
        return cls(**data)
    
    @classmethod
    def from_env(cls) -> 'DatabaseConfig':
        """从环境变量加载配置（简单实现）"""
        config = cls()
        
        # 环境变量优先级高于默认值
        if os.getenv('PROJO_DATA_DIR'):
            config.data_dir = os.getenv('PROJO_DATA_DIR')
        if os.getenv('PROJO_BUFFER_POOL_SIZE'):
            config.buffer_pool_size = int(os.getenv('PROJO_BUFFER_POOL_SIZE'))
        if os.getenv('PROJO_PAGE_SIZE'):
            config.page_size = int(os.getenv('PROJO_PAGE_SIZE'))
        
        return config
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'data_dir': self.data_dir,
            'storage_type': self.storage_type,
            'page_size': self.page_size,
            'buffer_pool_size': self.buffer_pool_size,
            'wal_enabled': self.wal_enabled,
            'wal_file': self.wal_file,
            'wal_sync': self.wal_sync,
            'autocommit': self.autocommit,
            'system_schema_file': self.system_schema_file,
            'log_level': self.log_level
        }