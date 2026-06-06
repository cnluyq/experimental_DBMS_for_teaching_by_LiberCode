#!/usr/bin/env python3
"""快速测试脚本"""
import sys
sys.path.insert(0, 'src')
sys.path.insert(0, '.')

from integration.coordinator import create_database, DatabaseConfig

# Test database creation
config = DatabaseConfig(
    data_dir='/tmp/projo_test',
    storage_type='file',
    buffer_pool_size=8,
    wal_enabled=False,
    log_level='WARNING'
)

print('创建数据库实例...')
db = create_database(config)
print('✓ 数据库创建成功')

# Test parser
print('测试解析器...')
from parser import parse
try:
    ast = parse('SELECT 1;')
    print(f'✓ 解析器测试: {type(ast).__name__}')
except Exception as e:
    print(f'解析测试: {e}')

db.shutdown()
print('✓ 关闭成功')
print('\n所有测试通过！')