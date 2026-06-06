"""
集成测试fixtures

使用新的Database API提供测试fixture。
"""

import pytest
import sys
import os
import tempfile
import shutil
from pathlib import Path

# 添加项目根目录到Python路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'src'))


@pytest.fixture
def temp_data_dir():
    """创建临时数据目录用于测试"""
    tmpdir = tempfile.mkdtemp(prefix='projo_test_')
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def temp_db(temp_data_dir):
    """
    创建临时的测试数据库实例
    
    返回:
        Database实例，测试结束后自动关闭
    """
    from integration.coordinator import create_database
    from integration.config import DatabaseConfig
    
    config = DatabaseConfig(
        data_dir=temp_data_dir,
        storage_type="file",
        buffer_pool_size=16,
        wal_enabled=True,
        wal_file="test_wal.log",
        autocommit=False,
        log_level="WARNING"
    )
    
    db = create_database(config)
    
    yield db
    
    # 清理
    try:
        db.shutdown()
    except:
        pass


@pytest.fixture
def empty_db(temp_db):
    """空数据库（已初始化但无表）"""
    return temp_db


@pytest.fixture
def db_with_users(temp_db):
    """预创建users表的数据库"""
    temp_db.execute("""
        CREATE TABLE users (
            id INT PRIMARY KEY,
            name TEXT NOT NULL,
            age INT,
            email TEXT
        )
    """)
    return temp_db


@pytest.fixture
def db_with_sample_data(db_with_users):
    """包含示例数据的数据库"""
    db = db_with_users
    
    # 插入测试数据
    test_data = [
        (1, 'Alice', 30, 'alice@example.com'),
        (2, 'Bob', 25, 'bob@example.com'),
        (3, 'Charlie', 35, 'charlie@example.com'),
        (4, 'David', 28, 'david@example.com'),
        (5, 'Eve', 32, 'eve@example.com'),
    ]
    
    for user_id, name, age, email in test_data:
        db.execute(f"INSERT INTO users VALUES ({user_id}, '{name}', {age}, '{email}')")
    
    return db