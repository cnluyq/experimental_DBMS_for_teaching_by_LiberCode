"""
DBMS配置参数
"""

from dataclasses import dataclass


@dataclass
class BufferConfig:
    """缓冲区配置"""
    num_frames: int = 100  # 缓冲区帧数量
    page_size: int = 4096  # 页面大小（字节）
    eviction_policy: str = "lru"  # 置换策略


@dataclass
class StorageConfig:
    """存储配置"""
    data_dir: str = "./data"
    page_file: str = "pages.dat"
    wal_file: str = "wal.log"


@dataclass
class DBConfig:
    """数据库配置"""
    buffer: BufferConfig = BufferConfig()
    storage: StorageConfig = StorageConfig()


# 默认配置
DEFAULT_CONFIG = DBConfig()