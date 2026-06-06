#!/usr/bin/env python3
"""Debug persistence"""
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

# Create and insert
db.execute('CREATE TABLE users (id INT PRIMARY KEY, name TEXT, age INT);')
db.execute("INSERT INTO users VALUES (1, 'Alice', 30);")
db.execute("INSERT INTO users VALUES (2, 'Bob', 25);")

# Check before shutdown
result = db.execute('SELECT * FROM users;')
print(f"Before shutdown: {len(result.rows)} rows")

# Force flush
print("\nForcing flush...")
if db.buffer:
    db.buffer.flush_all()
    print("Buffer flushed")
if db.wal:
    db.wal.force()
    print("WAL forced")

# Check storage files
print(f"\nData dir contents: {os.listdir(temp_dir)}")

db.shutdown()
print("\nShutdown complete")

# Check if file exists
db_file = os.path.join(temp_dir, 'projo_data.db')
if os.path.exists(db_file):
    print(f"DB file size: {os.path.getsize(db_file)} bytes")

# Restart
print("\n--- Restarting ---")
db2 = create_database(config)
result = db2.execute('SELECT * FROM users;')
print(f"After restart: {len(result.rows)} rows")
for r in result.rows:
    print(f"  {r}")

db2.shutdown()
shutil.rmtree(temp_dir)