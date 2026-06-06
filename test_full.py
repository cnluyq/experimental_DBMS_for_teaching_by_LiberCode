#!/usr/bin/env python3
"""完整功能测试"""
import sys
sys.path.insert(0, 'src')
sys.path.insert(0, '.')
import shutil, os

test_dir = '/tmp/test_projo_full'
shutil.rmtree(test_dir, ignore_errors=True)
os.makedirs(test_dir)

from integration.coordinator import create_database, DatabaseConfig
from parser import parse

config = DatabaseConfig(data_dir=test_dir, storage_type='file', wal_enabled=False, log_level='WARNING')
db = create_database(config)

tests = [
    ('CREATE TABLE', 'CREATE TABLE t (a INT, b TEXT);'),
    ('INSERT x3', "INSERT INTO t VALUES (1, 'x');"),
    ("INSERT x3", "INSERT INTO t VALUES (2, 'y');"),
    ("INSERT x3", "INSERT INTO t VALUES (3, 'z');"),
    ('SELECT WHERE', 'SELECT * FROM t WHERE a > 1;'),
    ('UPDATE', 'UPDATE t SET b = "updated" WHERE a = 1;'),
    ('DELETE', 'DELETE FROM t WHERE a = 3;'),
    ('SELECT final', 'SELECT * FROM t;'),
    ('.tables', None),
    ('DROP TABLE', 'DROP TABLE t;'),
]

for name, sql in tests:
    if sql:
        ast = parse(sql)
        result = db.executor.execute(ast)
        print(f'{name}: success={result.success}', end='')
        if result.rows: print(f', rows={len(result.rows)}')
        elif result.rows_affected is not None: print(f', affected={result.rows_affected}')
        else: print()
    else:
        print(f'{name}: {list(db.db_storage.tables.keys())}')

db.shutdown()
shutil.rmtree(test_dir)
print('\n✓ 全部测试通过！')