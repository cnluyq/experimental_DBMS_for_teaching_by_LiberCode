#!/usr/bin/env python3
"""Debug where data goes"""
import sys
sys.path.insert(0, '/home/claude/git/github/tmp/projo/src')

from integration.coordinator import create_database
from integration.config import DatabaseConfig
import tempfile
import shutil
import os

# Monkey-patch to trace storage writes
original_page_write = None

def traced_page_write(page_id, data):
    non_zero = sum(1 for b in data if b != 0)
    print(f"  [TRACE] page_write({page_id}): {non_zero} non-zero bytes, data[:50]={data[:50]}")
    return original_page_write(page_id, data)

temp_dir = tempfile.mkdtemp(prefix='projo_test_')
config = DatabaseConfig(data_dir=temp_dir, log_level='INFO')
db = create_database(config)

# Install trace
db_storage = db.db_storage
original_page_write = db_storage.engine.page_write
db_storage.engine.page_write = traced_page_write

print("\n=== CREATE TABLE ===")
db.execute('CREATE TABLE users (id INT PRIMARY KEY, name TEXT, age INT);')

print("\n=== INSERT ===")
db.execute("INSERT INTO users VALUES (1, 'Alice', 30);")

# Check manager
print(f"\nTable managers: {db_storage.table_managers}")
manager = db_storage.get_table_manager('users')
if manager:
    print(f"Manager storage: {type(manager.storage)}")
    # Check if manager uses db_storage
    print(f"Manager uses db_storage.engine? {manager.storage is db_storage.engine}")

db.shutdown()
shutil.rmtree(temp_dir)