"""
WAL恢复测试

专门测试WAL日志的持久化、检查和恢复能力。
"""

import pytest
import os
import json
from pathlib import Path


class TestWALBasic:
    """WAL基本功能测试"""
    
    def test_wal_file_creation(self, temp_db):
        """测试WAL文件创建"""
        db = temp_db
        if not db.wal:
            pytest.skip("WAL未启用")
        
        wal_path = db.wal.wal_file_path
        assert os.path.exists(wal_path), "WAL文件应该被创建"
    
    def test_log_append_and_flush(self, temp_db):
        """测试日志追加和刷新"""
        db = temp_db
        if not db.wal:
            pytest.skip("WAL未启用")
        
        initial_count = db.wal.stats['logs_written']
        
        # 执行一个写操作
        db.execute("CREATE TABLE log_test (id INTEGER PRIMARY KEY);")
        db.execute("INSERT INTO log_test VALUES (1);")
        
        # 检查日志计数增加
        assert db.wal.stats['logs_written'] > initial_count
    
    def test_checkpoint_creation(self, temp_db):
        """测试检查点创建"""
        db = temp_db
        if not db.wal:
            pytest.skip("WAL未启用")
        
        # 执行一些操作后创建检查点
        db.execute("CREATE TABLE cp_test (id INTEGER PRIMARY KEY);")
        db.execute("INSERT INTO cp_test VALUES (1);")
        db.execute("INSERT INTO cp_test VALUES (2);")
        
        cp_lsn = db.wal.create_checkpoint()
        assert cp_lsn > 0, "检查点LSN应该大于0"
        assert db.wal.last_checkpoint_lsn == cp_lsn
    
    def test_wal_analyze_recovery(self, temp_db):
        """测试WAL恢复分析"""
        db = temp_db
        if not db.wal:
            pytest.skip("WAL未启用")
        
        # 生成一些日志
        db.execute("CREATE TABLE analyze_test (id INTEGER PRIMARY KEY);")
        db.execute("INSERT INTO analyze_test VALUES (1);")
        db.begin_transaction()
        db.execute("INSERT INTO analyze_test VALUES (2);")
        db.commit()
        
        db.wal.force()
        
        # 运行分析
        analysis = db.wal.analyze_recovery()
        
        assert 'logs' in analysis
        assert 'dirty_page_table' in analysis
        assert isinstance(analysis['logs'], list)
        assert isinstance(analysis['dirty_page_table'], dict)


class TestWALRecoveryScenarios:
    """WAL恢复场景测试"""
    
    def test_recovery_after_checkpoint(self, temp_data_dir):
        """测试检查点后的恢复"""
        config = DatabaseConfig(
            data_dir=temp_data_dir,
            storage_type="file",
            wal_enabled=True,
            wal_file="cp_recovery.log",
            autocommit=False
        )
        
        from integration.coordinator import create_database
        db1 = create_database(config)
        
        # 创建表并插入数据
        db1.execute("CREATE TABLE cp_recovery (id INTEGER PRIMARY KEY, name TEXT);")
        db1.begin_transaction()
        db1.execute("INSERT INTO cp_recovery VALUES (1, 'Alice');")
        db1.commit()
        
        # 创建检查点
        db1.wal.create_checkpoint()
        
        # 再插入一些数据（新事务）
        db1.begin_transaction()
        db1.execute("INSERT INTO cp_recovery VALUES (2, 'Bob');")
        db1.commit()
        
        # 强制刷WAL
        db1.wal.force()
        db1.shutdown()
        
        # 重启并验证恢复
        db2 = create_database(config)
        result = db2.execute("SELECT * FROM cp_recovery ORDER BY id;")
        rows = result.rows
        
        assert len(rows) == 2
        assert rows[0]['name'] == 'Alice'
        assert rows[1]['name'] == 'Bob'
        
        db2.shutdown()
    
    def test_recovery_partial_committed_transactions(self, temp_data_dir):
        """测试恢复时部分提交事务的处理"""
        config = DatabaseConfig(
            data_dir=temp_data_dir,
            storage_type="file",
            wal_enabled=True,
            wal_file="partial_commit.log",
            autocommit=False
        )
        
        from integration.coordinator import create_database
        db1 = create_database(config)
        
        db1.execute("CREATE TABLE partial (id INTEGER PRIMARY KEY, val INTEGER);")
        
        # 事务1：完全提交
        db1.begin_transaction()
        db1.execute("INSERT INTO partial VALUES (1, 100);")
        db1.commit()
        
        # 事务2：部分操作后崩溃（不提交）
        db1.begin_transaction()
        db1.execute("INSERT INTO partial VALUES (2, 200);")
        db1.execute("INSERT INTO partial VALUES (3, 300);")
        # 不提交，模拟崩溃
        db1.wal.force()
        del db1
        
        # 恢复
        db2 = create_database(config)
        result = db2.execute("SELECT * FROM partial ORDER BY id;")
        ids = [row['id'] for row in result.rows]
        
        # 事务1应该存在，事务2不应该（因为未提交）
        assert 1 in ids
        assert 2 not in ids
        assert 3 not in ids
        
        db2.shutdown()
    
    def test_recovery_after_checkpoint_with_multiple_transactions(self, temp_data_dir):
        """测试多个事务后创建检查点的恢复"""
        config = DatabaseConfig(
            data_dir=temp_data_dir,
            storage_type="file",
            wal_enabled=True,
            wal_file="multi_txn.log",
            autocommit=False
        )
        
        from integration.coordinator import create_database
        db1 = create_database(config)
        
        db1.execute("CREATE TABLE multi (id INTEGER PRIMARY KEY, tag TEXT);")
        
        # 多个提交事务
        for i in range(5):
            db1.begin_transaction()
            db1.execute(f"INSERT INTO multi VALUES ({i}, 'tag_{i}');")
            db1.commit()
        
        # 创建检查点
        db1.wal.create_checkpoint()
        
        # 未完成的事务
        db1.begin_transaction()
        db1.execute("INSERT INTO multi VALUES (99, 'uncommitted');")
        # 不提交
        
        db1.wal.force()
        del db1
        
        # 恢复
        db2 = create_database(config)
        result = db2.execute("SELECT * FROM multi ORDER BY id;")
        ids = [row['id'] for row in result.rows]
        
        # 检查点前的5条应该存在，99不应该
        assert len(ids) == 5
        assert all(i in ids for i in range(5))
        assert 99 not in ids
        
        db2.shutdown()
    
    def test_recovery_idempotence(self, temp_data_dir):
        """测试恢复的幂等性：多次恢复结果一致"""
        config = DatabaseConfig(
            data_dir=temp_data_dir,
            storage_type="file",
            wal_enabled=True,
            wal_file="idempotent.log",
            autocommit=False
        )
        
        from integration.coordinator import create_database
        
        # 第一次运行：创建数据
        db1 = create_database(config)
        db1.execute("CREATE TABLE idem (id INTEGER PRIMARY KEY);")
        db1.begin_transaction()
        db1.execute("INSERT INTO idem VALUES (1);")
        db1.commit()
        db1.shutdown()
        
        # 第二次恢复
        db2 = create_database(config)
        result1 = db2.execute("SELECT * FROM idem;")
        count1 = len(result1.rows)
        db2.shutdown()
        
        # 第三次恢复
        db3 = create_database(config)
        result2 = db3.execute("SELECT * FROM idem;")
        count2 = len(result2.rows)
        db3.shutdown()
        
        assert count1 == count2 == 1
    
    def test_restart_does_not_replay_committed_logs_multiple_times(self, temp_data_dir):
        """测试已提交日志不会重复重放（幂等性）"""
        config = DatabaseConfig(
            data_dir=temp_data_dir,
            storage_type="file",
            wal_enabled=True,
            wal_file="no_double_replay.log",
            autocommit=False
        )
        
        from integration.coordinator import create_database
        
        db1 = create_database(config)
        db1.execute("CREATE TABLE replay (id INTEGER PRIMARY KEY, val INTEGER);")
        
        # 插入数据并提交
        db1.begin_transaction()
        db1.execute("INSERT INTO replay VALUES (1, 100);")
        db1.commit()
        
        db1.shutdown()
        
        # 第一次启动
        db2 = create_database(config)
        result1 = db2.execute("SELECT * FROM replay;")
        val1 = result1.rows[0]['val']
        db2.shutdown()
        
        # 第二次启动（不应该再次应用日志）
        db3 = create_database(config)
        result2 = db3.execute("SELECT * FROM replay;")
        val2 = result2.rows[0]['val']
        db3.shutdown()
        
        assert val1 == val2 == 100
    
    def test_large_transaction_recovery(self, temp_data_dir):
        """测试大事务（多日志）的恢复"""
        config = DatabaseConfig(
            data_dir=temp_data_dir,
            storage_type="file",
            wal_enabled=True,
            wal_file="large_txn.log",
            autocommit=False,
            buffer_pool_size=32
        )
        
        from integration.coordinator import create_database
        db1 = create_database(config)
        
        db1.execute("CREATE TABLE large (id INTEGER PRIMARY KEY, data TEXT);")
        
        db1.begin_transaction()
        # 插入较多记录
        for i in range(100):
            db1.execute(f"INSERT INTO large VALUES ({i}, 'data_{i}');")
        db1.commit()
        
        db1.wal.force()
        del db1
        
        # 恢复
        db2 = create_database(config)
        result = db2.execute("SELECT COUNT(*) as cnt FROM large;")
        count = result.rows[0]['cnt']
        assert count == 100
        db2.shutdown()