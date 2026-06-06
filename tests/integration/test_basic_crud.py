"""
基础CRUD集成测试

测试完整的创建、读取、更新、删除流程。
"""

import pytest
from typing import Any, Dict


class TestBasicCRUD:
    """基础CRUD测试套件"""
    
    def test_create_table(self, empty_db):
        """测试CREATE TABLE语句"""
        sql = """
        CREATE TABLE test_table (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            value FLOAT
        );
        """
        result = empty_db.execute(sql)
        
        # 验证表创建成功
        assert result is not None
        
        # 验证表是否在元数据中
        executor = empty_db.executor
        assert 'test_table' in executor.table_metadata
        
        # 检查列定义
        table_meta = executor.table_metadata['test_table']
        column_names = [col['name'] for col in table_meta.columns]
        assert 'id' in column_names
        assert 'name' in column_names
        assert 'value' in column_names
    
    def test_insert_single_row(self, empty_db):
        """测试插入单行数据"""
        # 先创建表
        empty_db.execute("CREATE TABLE t1 (id INTEGER PRIMARY KEY, name TEXT);")
        
        # 插入数据
        result = empty_db.execute("INSERT INTO t1 VALUES (1, 'Alice');")
        
        assert result is not None
        if hasattr(result, 'rows_affected'):
            assert result.rows_affected == 1
        
        # 验证插入后的数据
        select_result = empty_db.execute("SELECT * FROM t1 WHERE id = 1;")
        assert hasattr(select_result, 'rows')
        assert len(select_result.rows) == 1
        assert select_result.rows[0]['name'] == 'Alice'
    
    def test_insert_multiple_rows(self, empty_db):
        """测试插入多行数据"""
        empty_db.execute("CREATE TABLE t2 (id INTEGER PRIMARY KEY, val INTEGER);")
        
        # 插入多行
        for i in range(1, 6):
            empty_db.execute(f"INSERT INTO t2 VALUES ({i}, {i * 10});")
        
        # 验证所有行都已插入
        result = empty_db.execute("SELECT * FROM t2 ORDER BY id;")
        assert len(result.rows) == 5
        
        expected_vals = [10, 20, 30, 40, 50]
        actual_vals = [row['val'] for row in result.rows]
        assert actual_vals == expected_vals
    
    def test_select_all(self, db_with_sample_data):
        """测试SELECT * 查询"""
        result = db_with_sample_data.execute("SELECT * FROM users;")
        
        assert len(result.rows) == 5
        columns = result.columns
        assert 'id' in columns
        assert 'name' in columns
        assert 'age' in columns
        assert 'email' in columns
    
    def test_select_with_where(self, db_with_sample_data):
        """测试带WHERE条件的SELECT"""
        result = db_with_sample_data.execute("SELECT * FROM users WHERE age > 30;")
        
        # 应该返回年龄大于30的用户（Charlie 35, Eve 32）
        assert len(result.rows) == 2
        names = [row['name'] for row in result.rows]
        assert 'Charlie' in names
        assert 'Eve' in names
        assert 'Alice' not in names
    
    def test_select_specific_columns(self, db_with_sample_data):
        """测试选择特定列"""
        result = db_with_sample_data.execute("SELECT name, email FROM users WHERE id = 1;")
        
        assert len(result.rows) == 1
        row = result.rows[0]
        assert 'name' in row
        assert 'email' in row
        assert 'age' not in row  # 未选择的列不应该出现
        assert row['name'] == 'Alice'
    
    def test_update_row(self, db_with_sample_data):
        """测试更新数据"""
        # 更新Alice的年龄和邮箱
        sql = "UPDATE users SET age = 31, email = 'alice.new@example.com' WHERE id = 1;"
        result = db_with_sample_data.execute(sql)
        
        if hasattr(result, 'rows_affected'):
            assert result.rows_affected == 1
        
        # 验证更新
        select_result = db_with_sample_data.execute("SELECT * FROM users WHERE id = 1;")
        row = select_result.rows[0]
        assert row['age'] == 31
        assert row['email'] == 'alice.new@example.com'
    
    def test_update_multiple_rows(self, db_with_sample_data):
        """测试更新多行"""
        result = db_with_sample_data.execute("UPDATE users SET age = age + 1;")
        
        if hasattr(result, 'rows_affected'):
            assert result.rows_affected == 5
        
        # 验证所有行都增加了年龄
        all_users = db_with_sample_data.execute("SELECT * FROM users ORDER BY id;")
        expected_ages = [31, 26, 36, 29, 33]  # 原始年龄+1
        actual_ages = [row['age'] for row in all_users.rows]
        assert actual_ages == expected_ages
    
    def test_delete_row(self, db_with_sample_data):
        """测试删除单行"""
        result = db_with_sample_data.execute("DELETE FROM users WHERE id = 5;")
        
        if hasattr(result, 'rows_affected'):
            assert result.rows_affected == 1
        
        # 验证删除
        all_users = db_with_sample_data.execute("SELECT * FROM users;")
        assert len(all_users.rows) == 4
        ids = [row['id'] for row in all_users.rows]
        assert 5 not in ids
    
    def test_delete_multiple_rows(self, db_with_sample_data):
        """测试删除多行（带条件）"""
        result = db_with_sample_data.execute("DELETE FROM users WHERE age < 30;")
        
        # 年龄小于30的有Bob(25)和David(28)，应该删除2行
        if hasattr(result, 'rows_affected'):
            assert result.rows_affected == 2
        
        # 验证剩余3行（Alice, Charlie, Eve）
        remaining = db_with_sample_data.execute("SELECT * FROM users;")
        assert len(remaining.rows) == 3
    
    def test_delete_all(self, db_with_sample_data):
        """测试删除所有行（无WHERE条件）"""
        result = db_with_sample_data.execute("DELETE FROM users;")
        
        if hasattr(result, 'rows_affected'):
            assert result.rows_affected == 5
        
        # 表应该为空
        empty_result = db_with_sample_data.execute("SELECT * FROM users;")
        assert len(empty_result.rows) == 0
    
    def test_autocommit_behavior(self, empty_db):
        """测试自动提交模式"""
        # 设置自动提交（如果支持）
        # 每个语句应该独立提交
        
        empty_db.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, val INTEGER);")
        empty_db.execute("INSERT INTO test VALUES (1, 100);")
        
        # 立即查询应该看到数据
        result = empty_db.execute("SELECT * FROM test;")
        assert len(result.rows) == 1
        
        # 另一个事务也应该能看到
        empty_db.execute("INSERT INTO test VALUES (2, 200);")
        result2 = empty_db.execute("SELECT * FROM test;")
        assert len(result2.rows) == 2
    
    def test_null_values(self, empty_db):
        """测试NULL值处理"""
        empty_db.execute("CREATE TABLE nullable_test (id INTEGER PRIMARY KEY, val TEXT);")
        
        # 插入NULL值
        result = empty_db.execute("INSERT INTO nullable_test VALUES (1, NULL);")
        assert result is not None
        
        # 查询NULL
        select_result = empty_db.execute("SELECT * FROM nullable_test;")
        row = select_result.rows[0]
        assert row['val'] is None or row['val'] == '' or 'null' in str(row['val']).lower()
    
    def test_complex_operations_chain(self, empty_db):
        """测试复杂操作链"""
        # 创建表
        empty_db.execute("""
            CREATE TABLE orders (
                order_id INTEGER PRIMARY KEY,
                customer TEXT,
                amount FLOAT,
                status TEXT
            );
        """)
        
        # 插入多条
        empty_db.execute("INSERT INTO orders VALUES (1, 'Alice', 99.99, 'pending');")
        empty_db.execute("INSERT INTO orders VALUES (2, 'Bob', 149.99, 'shipped');")
        empty_db.execute("INSERT INTO orders VALUES (3, 'Alice', 199.99, 'pending');")
        
        # 更新Alice的订单状态
        empty_db.execute("UPDATE orders SET status = 'processing' WHERE customer = 'Alice';")
        
        # 删除已发货的订单
        empty_db.execute("DELETE FROM orders WHERE status = 'shipped';")
        
        # 验证最终状态
        final = empty_db.execute("SELECT * FROM orders ORDER BY order_id;")
        assert len(final.rows) == 2
        statuses = [row['status'] for row in final.rows]
        assert all(s == 'processing' for s in statuses)