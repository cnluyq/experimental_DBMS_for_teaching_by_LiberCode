"""
Pytest配置和共享fixtures

设置Python路径以便导入项目模块。
"""

import sys
import os
from pathlib import Path

# 添加项目根目录和src目录到Python路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

# 可以在这里定义全局fixture
import pytest


@pytest.fixture(scope="session")
def project_root():
    """返回项目根目录"""
    return PROJECT_ROOT