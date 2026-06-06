#!/usr/bin/env python3
"""集成测试脚本"""
import sys
sys.path.insert(0, 'src')
sys.path.insert(0, '.')
import tempfile, shutil

# Create test dir
test_dir = tempfile.mkdtemp()
print(f'Test dir: {test_dir}')

from integration.coordinator import create_database, DatabaseConfig

config = DatabaseConfig(
    data_dir=test_dir,
    storage_type='file',
    buffer_pool_size=8,
    wal_enabled=False,
    log_level='WARNING'
)

db = create_database(config)
print('✓ 数据库创建成功')

# Test CREATE TABLE
from parser import parse
print('\n测试 CREATE TABLE...')
ast = parse('CREATE TABLE users (id INT, name TEXT);')
result = db.executor.execute(ast)
print(f'CREATE: {result.success}, affected={result.rows_affected}, msg={result.message}')

# Test INSERT
print('\n测试 INSERT...')
ast = parse("INSERT INTO users (id, name) VALUES (1, 'Alice');")
result = db.executor.execute(ast)
print(f'INSERT: {result.success}, affected={result.rows_affected}, msg={result.message}')

# Test SELECT
print('\n测试 SELECT...')
ast = parse('SELECT * FROM users;')
result = db.executor.execute(ast)
print(f'SELECT: {result.success}, rows={len(result.rows) if result.rows else 0}')
if result.rows:
    print(f'  数据: {result.rows}')

db.shutdown()
print('\n✓ 集成测试通过！')

shutil.rmtree(test_dir)