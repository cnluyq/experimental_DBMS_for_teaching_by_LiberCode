"""
Pytest配置 - integration tests

设置Python路径和环境。
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

# 可选：设置pytest标记
def pytest_configure(config):
    """配置pytest标记"""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "wal: tests specific to WAL functionality"
    )
    config.addinivalue_line(
        "markers", "transaction: tests for transaction management"
    )
    config.addinivalue_line(
        "markers", "crud: tests for basic CRUD operations"
    )