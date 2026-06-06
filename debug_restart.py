#!/usr/bin/env python3
"""Debug restart data"""
import sys
sys.path.insert(0, '/home/claude/git/github/tmp/projo/src')

from integration.coordinator import create_database
from integration.config import DatabaseConfig
import tempfile
import shutil
import os

temp_dir = tempfile.mkdtemp(prefix='projo_test_')
config = DatabaseConfig(data_dir=temp_dir, log_level='WARNING')

# First instance
print("=== First instance ===")
db1 = create_database(config)
db1.execute('CREATE TABLE users (id INT PRIMARY KEY, name TEXT, age INT);')
db1.execute("INSERT INTO users VALUES (1, 'Alice', 30);")
db1.execute("INSERT INTO users VALUES (2, 'Bob', 25);")

# Check pages before shutdown
print("\nBefore shutdown:")
for i in range(98, 103):
    page_data = db1.db_storage.engine.page_read(i)
    if page_data:
        non_zero = sum(1 for b in page_data if b != 0)
        if non_zero > 0:
            print(f"  Page {i}: {non_zero} non-zero bytes")
            # Show slot info (offset 64, first 11 bytes per slot)
            for slot in range(5):
                offset = slot * 11
                record_id = int.from_bytes(page_data[offset:offset+4], 'little')
                slot_offset = int.from_bytes(page_data[offset+4:offset+6], 'little')
                slot_len = int.from_bytes(page_data[offset+6:offset+8], 'little')
                status = page_data[offset+8]
                print(f"    Slot {slot}: record_id={record_id}, offset={slot_offset}, len={slot_len}, status={status}")

db1.shutdown()

# Check file size
db_file = os.path.join(temp_dir, 'projo_data.db')
print(f"\nFile size after shutdown: {os.path.getsize(db_file)} bytes")

# Read page 100 directly from file
with open(db_file, 'rb') as f:
    f.seek(100 * 4096)
    page_data = f.read(4096)
    non_zero = sum(1 for b in page_data if b != 0)
    print(f"Page 100 in file: {non_zero} non-zero bytes")

# Second instance
print("\n=== Second instance ===")
db2 = create_database(config)
print(f"Tables loaded: {list(db2.db_storage.tables.keys())}")
print(f"Table managers: {list(db2.db_storage.table_managers.keys())}")

# Check pages after restart
for i in range(98, 103):
    page_data = db2.db_storage.engine.page_read(i)
    if page_data:
        non_zero = sum(1 for b in page_data if b != 0)
        if non_zero > 0:
            print(f"  Page {i}: {non_zero} non-zero bytes")

# Check manager
manager = db2.db_storage.get_table_manager('users')
if manager:
    print(f"Manager found, next_record_id={manager.next_record_id}")
    for rec in manager.scan_all():
        print(f"  Record: {rec.values}")

db2.shutdown()
shutil.rmtree(temp_dir)