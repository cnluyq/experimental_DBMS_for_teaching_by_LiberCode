#!/usr/bin/env python3
"""Debug storage path"""
import sys
sys.path.insert(0, '/home/claude/git/github/tmp/projo/src')

from integration.coordinator import create_database
from integration.config import DatabaseConfig
import tempfile
import shutil
import os

temp_dir = tempfile.mkdtemp(prefix='projo_test_')
config = DatabaseConfig(data_dir=temp_dir, log_level='INFO')
db = create_database(config)

# Create table
db.execute('CREATE TABLE users (id INT PRIMARY KEY, name TEXT, age INT);')
db.execute("INSERT INTO users VALUES (1, 'Alice', 30);")
db.execute("INSERT INTO users VALUES (2, 'Bob', 25);")

# Check storage
print("\n=== Checking Storage ===")
print(f"Storage type: {type(db.storage)}")
print(f"DB Storage type: {type(db.db_storage)}")
print(f"DB Storage engine type: {type(db.db_storage.engine)}")

# Check file directly
db_file = os.path.join(temp_dir, 'projo_data.db')
with open(db_file, 'rb') as f:
    data = f.read()
    print(f"\nFile size: {len(data)}")
    # Show first 200 bytes
    print(f"First 200 bytes: {data[:200]}")

# Check what pages have data
for i in range(10):
    page_data = db.storage.page_read(i)
    if page_data:
        # Check if page has non-zero data
        non_zero = sum(1 for b in page_data if b != 0)
        print(f"Page {i}: {non_zero} non-zero bytes")
        if non_zero > 0 and i >= 2:  # Skip system tables
            print(f"  Content preview: {page_data[:100]}")

db.shutdown()
shutil.rmtree(temp_dir)