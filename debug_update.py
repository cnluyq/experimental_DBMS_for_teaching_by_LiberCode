#!/usr/bin/env python3
"""Debug UPDATE and DELETE"""
import sys
sys.path.insert(0, '/home/claude/git/github/tmp/projo/src')

from integration.coordinator import create_database
from integration.config import DatabaseConfig
import tempfile
import shutil

temp_dir = tempfile.mkdtemp(prefix='projo_test_')
config = DatabaseConfig(data_dir=temp_dir, log_level='WARNING')
db = create_database(config)

# Create table and insert
db.execute('CREATE TABLE users (id INT PRIMARY KEY, name TEXT, age INT);')
db.execute("INSERT INTO users VALUES (1, 'Alice', 30);")
db.execute("INSERT INTO users VALUES (2, 'Bob', 25);")
print(f"Initial data:")
result = db.execute('SELECT * FROM users;')
for r in result.rows:
    print(f"  {r}")

# Check WHERE clause parsing
print("\nChecking WHERE clause:")
result = db.execute('SELECT * FROM users WHERE id = 1;')
print(f"  SELECT WHERE id=1: {len(result.rows)} rows")

# Try UPDATE without WHERE (should update all)
print("\nUPDATE without WHERE:")
result = db.execute('UPDATE users SET age = 31;')
print(f"  rows_affected={getattr(result, 'rows_affected', 'N/A')}")

result = db.execute('SELECT * FROM users;')
for r in result.rows:
    print(f"  {r}")

# Try UPDATE with WHERE
print("\nUPDATE with WHERE:")
result = db.execute("UPDATE users SET age = 32 WHERE id = 1;")
print(f"  rows_affected={getattr(result, 'rows_affected', 'N/A')}")

result = db.execute('SELECT * FROM users;')
for r in result.rows:
    print(f"  {r}")

db.shutdown()
shutil.rmtree(temp_dir)