#!/usr/bin/env python3
"""
WAL日志系统测试套件

测试覆盖：
1. 基础日志写入和读取
2. 事务提交和中止
3. 检查点创建和读取
4. 崩溃恢复（模拟）
5. 并发场景（简单模拟）
"""

import os
import sys
import shutil
import tempfile
from pathlib import Path

# 添加src到路径
sys.path.insert(0, str(Path(__file__).parent.parent / 'src' / 'core'))

from wal import WALManager, LogType, build_update_payload, build_insert_payload, MockDatabase


def cleanup_wal_files():
    """清理测试产生的WAL文件"""
    test_files = [
        'test_wal.log',
        'demo_wal.log',
        'recovery_demo_wal.log',
        'wal_crash.log'
    ]
    for f in test_files:
        if os.path.exists(f):
            os.remove(f)


def test_basic_logging():
    """测试基础日志写入"""
    print("\n" + "="*60)
    print("Test 1: Basic Logging")
    print("="*60)
    
    cleanup_wal_files()
    
    wal = WALManager('test_wal.log')
    assert wal.open(), "Failed to open WAL"
    
    # 开始事务
    tid = 100
    wal.begin_transaction(tid)
    
    # 追加UPDATE日志
    payload = build_update_payload(1, 100, b'old', b'new')
    lsn1 = wal.append(tid, LogType.UPDATE, payload)
    print(f"Added UPDATE log: LSN={lsn1}, tid={tid}")
    
    # 追加INSERT日志
    payload2 = build_insert_payload(2, 200, b'inserted data')
    lsn2 = wal.append(tid, LogType.INSERT, payload2)
    print(f"Added INSERT log: LSN={lsn2}, tid={tid}")
    
    # 提交
    wal.commit(tid)
    
    # 验证统计：2 data logs (UPDATE + INSERT) + COMMIT = 3 logs
    stats = wal.get_stats()
    assert stats['logs_written'] == 3, f"Expected 3 logs (2 data + 1 commit), got {stats['logs_written']}"
    assert stats['active_transactions'] == 0, "No active transactions after commit"
    
    wal.close()
    print("✓ Basic logging test passed")
    return True


def test_checkpoint():
    """测试检查点功能"""
    print("\n" + "="*60)
    print("Test 2: Checkpoint")
    print("="*60)
    
    cleanup_wal_files()
    
    wal = WALManager('test_wal.log')
    wal.open()
    
    # 执行一些操作
    tid = 1
    wal.begin_transaction(tid)
    payload = build_update_payload(1, 100, b'old', b'new')
    wal.append(tid, LogType.UPDATE, payload)
    wal.commit(tid)
    
    # 创建检查点
    cp_lsn = wal.create_checkpoint()
    assert cp_lsn > 0, "Checkpoint LSN should be > 0"
    
    stats = wal.get_stats()
    assert stats['checkpoints'] == 1, f"Expected 1 checkpoint, got {stats['checkpoints']}"
    
    wal.close()
    
    # 验证检查点持久化
    assert os.path.exists('test_wal.log'), "WAL file should exist"
    
    print(f"✓ Checkpoint created at LSN {cp_lsn}")
    print("✓ Checkpoint test passed")
    return True


def test_recovery_after_crash():
    """测试崩溃恢复"""
    print("\n" + "="*60)
    print("Test 3: Crash Recovery")
    print("="*60)
    
    cleanup_wal_files()
    
    # 阶段1: 创建数据库并执行操作
    wal1 = WALManager('test_wal.log')
    wal1.open()
    db1 = MockDatabase(wal1)
    
    # 事务1: 已提交
    tid1 = 1
    wal1.begin_transaction(tid1)
    db1.update(5, 100, b'A', b'B', tid1)
    wal1.commit(tid1)
    
    # 事务2: 未提交（模拟崩溃前未提交）
    tid2 = 2
    wal1.begin_transaction(tid2)
    db1.update(6, 200, b'X', b'Y', tid2)
    # 没有commit
    
    # 事务3: 已提交
    tid3 = 3
    wal1.begin_transaction(tid3)
    db1.update(7, 300, b'P', b'Q', tid3)
    wal1.commit(tid3)
    
    # 创建检查点
    cp_lsn = wal1.create_checkpoint()
    print(f"Checkpoint at LSN {cp_lsn}")
    
    wal1.close()
    
    # 阶段2: 模拟崩溃（清空内存数据库）
    print("\n[Simulating crash...]")
    original_page5 = db1.data_pages[5][100:101]
    original_page6 = db1.data_pages[6][200:201]
    original_page7 = db1.data_pages[7][300:301]
    
    print(f"Before crash - Page5[100]={original_page5}, Page6[200]={original_page6}, Page7[300]={original_page7}")
    
    # 清空内存数据库
    db1.data_pages.clear()
    for i in range(10):
        db1.data_pages[i] = bytearray(b'\x00' * 4096)
    
    print(f"After crash  - Page5[100]={db1.data_pages[5][100:101]}, Page6[200]={db1.data_pages[6][200:201]}")
    
    # 阶段3: 恢复
    wal2 = WALManager('test_wal.log')
    wal2.open()
    db2 = MockDatabase(wal2)
    
    stats = db2.recover()
    
    # 验证恢复结果
    print("\n[After recovery]")
    page5_after = db2.data_pages[5][100:101]
    page6_after = db2.data_pages[6][200:201]
    page7_after = db2.data_pages[7][300:301]
    
    print(f"  Page5[100] (T1 committed)   = {page5_after} (expected b'B')")
    print(f"  Page6[200] (T2 uncommitted) = {page6_after} (expected b'X' - unchanged)")
    print(f"  Page7[300] (T3 committed)   = {page7_after} (expected b'Q')")
    
    assert page5_after == b'B', f"Page5 should be 'B', got {page5_after}"
    assert page6_after == b'X', f"Page6 should be 'X' (unchanged), got {page6_after}"
    assert page7_after == b'Q', f"Page7 should be 'Q', got {page7_after}"
    
    wal2.close()
    print("\n✓ Crash recovery test passed")
    return True


def test_multiple_transactions():
    """测试多事务并发（串行）"""
    print("\n" + "="*60)
    print("Test 4: Multiple Transactions")
    print("="*60)
    
    cleanup_wal_files()
    
    wal = WALManager('test_wal.log')
    wal.open()
    db = MockDatabase(wal)
    
    # 创建5个事务，每个更新不同页面
    for tid in range(1, 6):
        wal.begin_transaction(tid)
        page_id = tid - 1
        db.update(page_id, 0, b'0', chr(ord('A') + tid - 1).encode(), tid)
        wal.commit(tid)
        print(f"Transaction {tid} committed")
    
    stats = wal.get_stats()
    assert stats['active_transactions'] == 0, "No active transactions"
    assert stats['dirty_pages'] == 5, f"Expected 5 dirty pages, got {stats['dirty_pages']}"
    
    wal.close()
    print("✓ Multiple transactions test passed")
    return True


def test_wal_persistence():
    """测试WAL持久化（fsync）"""
    print("\n" + "="*60)
    print("Test 5: WAL Persistence")
    print("="*60)
    
    cleanup_wal_files()
    
    wal = WALManager('test_wal.log')
    wal.open()
    
    # 写入一些日志
    tid = 1
    wal.begin_transaction(tid)
    wal.append(tid, LogType.UPDATE, b'test data')
    wal.commit(tid)
    
    # 强制持久化
    wal.force()
    
    # 检查文件是否存在且非空
    assert os.path.exists('test_wal.log'), "WAL file should exist"
    file_size = os.path.getsize('test_wal.log')
    assert file_size > 0, "WAL file should not be empty"
    
    wal.close()
    
    # 重新打开验证
    wal2 = WALManager('test_wal.log')
    wal2.open()
    stats = wal2.get_stats()
    assert stats['logs_written'] == 2, f"Should recover log count, got {stats['logs_written']}"
    wal2.close()
    
    print(f"✓ WAL persisted to disk ({file_size} bytes)")
    print("✓ Persistence test passed")
    return True


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print("WAL Test Suite")
    print("="*60)
    
    tests = [
        test_basic_logging,
        test_checkpoint,
        test_recovery_after_crash,
        test_multiple_transactions,
        test_wal_persistence
    ]
    
    passed = 0
    failed = 0
    
    for test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"\n✗ Test {test_func.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
        finally:
            cleanup_wal_files()
    
    print("\n" + "="*60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("="*60)
    
    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)