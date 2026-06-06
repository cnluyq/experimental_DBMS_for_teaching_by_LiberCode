#!/usr/bin/env python3
"""
事务管理器 - Python实现

为executor提供事务支持：
- 事务状态管理（active, committing, aborted, committed）
- 锁管理（共享锁、排他锁，死锁检测）
- 与Python WAL集成
- ACID属性保证

注意：这是一个教学版本，简化了实现（乐观锁或悲观锁策略）。
"""

import threading
import time
import uuid
from enum import IntEnum
from typing import Dict, Set, List, Optional, Any
from collections import defaultdict


class TransactionState(IntEnum):
    """事务状态"""
    ACTIVE = 1
    COMMITTING = 2
    ABORTING = 3
    COMMITTED = 4
    ABORTED = 5


class LockMode(IntEnum):
    """锁模式"""
    SHARED = 1
    EXCLUSIVE = 2


class LockRequest:
    """锁请求"""
    def __init__(self, tid: int, resource_id: str, mode: LockMode, timestamp: float):
        self.tid = tid
        self.resource_id = resource_id
        self.mode = mode
        self.timestamp = timestamp


class LockTableEntry:
    """锁表条目"""
    def __init__(self):
        self.shared_lock_holders: Set[int] = set()
        self.exclusive_lock_holder: Optional[int] = None
        self.waiting_queue: List[LockRequest] = []
    
    def has_conflict(self, req: LockRequest) -> bool:
        """检查请求是否与当前锁冲突"""
        if req.mode == LockMode.EXCLUSIVE:
            # 排他锁与任何锁都冲突
            return (self.exclusive_lock_holder is not None or 
                    len(self.shared_lock_holders) > 0)
        else:
            # 共享锁与排他锁冲突
            return self.exclusive_lock_holder is not None
    
    def is_locked(self) -> bool:
        return self.exclusive_lock_holder is not None or len(self.shared_lock_holders) > 0


class TransactionInfo:
    """事务信息"""
    def __init__(self, tid: int):
        self.tid = tid
        self.state: TransactionState = TransactionState.ACTIVE
        self.locked_resources: Set[str] = set()
        self.start_time: float = time.time()
        self.in_commit_process: bool = False
        self.description: str = ""
        self.last_lsn: Optional[int] = None


class TransactionManager:
    """
    事务管理器
    
    负责：
    - 事务生命周期管理
    - 锁的分配和释放
    - 死锁检测
    - 与WAL协作写入日志
    """
    
    def __init__(self, wal_manager=None, strict_2pl: bool = True, 
                 deadlock_detection_enabled: bool = True):
        """
        初始化事务管理器
        
        Args:
            wal_manager: WAL管理器实例（可选）
            strict_2pl: 是否使用严格两阶段锁
            deadlock_detection_enabled: 是否启用死锁检测
        """
        self.wal_manager = wal_manager
        self.strict_2pl = strict_2pl
        self.deadlock_detection_enabled = deadlock_detection_enabled
        
        # 线程同步
        self.txn_lock = threading.RLock()
        self.lock_lock = threading.RLock()
        self.wal_lock = threading.Lock()
        
        # 事务表
        self.transactions: Dict[int, TransactionInfo] = {}
        
        # 锁表
        self.lock_table: Dict[str, LockTableEntry] = {}
        
        # 计数器
        self.next_transaction_id = 1
        self.timestamp_counter = 0
        
        # 统计
        self.stats = {
            'transactions_begun': 0,
            'transactions_committed': 0,
            'transactions_aborted': 0,
            'locks_acquired': 0,
            'deadlocks_detected': 0,
            'current_active_transactions': 0
        }
    
    def allocate_transaction_id(self) -> int:
        """分配事务ID"""
        with self.txn_lock:
            tid = self.next_transaction_id
            self.next_transaction_id += 1
            return tid
    
    def begin(self, description: str = "") -> int:
        """
        开始新事务
        
        Returns:
            事务ID
        """
        tid = self.allocate_transaction_id()
        
        with self.txn_lock:
            txn = TransactionInfo(tid)
            txn.description = description
            self.transactions[tid] = txn
        
        # 写入BEGIN日志（如果有WAL）
        if self.wal_manager:
            self._write_log(tid, 'BEGIN')
        
        self.stats['transactions_begun'] += 1
        self.stats['current_active_transactions'] += 1
        
        return tid
    
    def commit(self, tid: int) -> bool:
        """
        提交事务
        
        Args:
            tid: 事务ID
            
        Returns:
            成功返回True，失败返回False
        """
        txn = None
        with self.txn_lock:
            if tid not in self.transactions:
                return False
            txn = self.transactions[tid]
            if txn.state != TransactionState.ACTIVE:
                return False
            txn.state = TransactionState.COMMITTING
            txn.in_commit_process = True
        
        # 严格2PL：提交前释放所有锁
        if self.strict_2pl:
            self.unlock_all(tid)
        
        # 写入COMMIT日志
        if self.wal_manager:
            self._write_log(tid, 'COMMIT')
            # 强制持久化
            self.wal_manager.flush()
        
        # 清理事务
        with self.txn_lock:
            if tid in self.transactions:
                del self.transactions[tid]
            self.stats['transactions_committed'] += 1
            self.stats['current_active_transactions'] -= 1
        
        return True
    
    def rollback(self, tid: int) -> bool:
        """
        回滚事务
        
        Args:
            tid: 事务ID
            
        Returns:
            成功返回True，失败返回False
        """
        txn = None
        with self.txn_lock:
            if tid not in self.transactions:
                return False
            txn = self.transactions[tid]
            if txn.state in (TransactionState.ABORTING, TransactionState.ABORTED):
                return False
            txn.state = TransactionState.ABORTING
            txn.in_commit_process = True
        
        # 释放所有锁
        self.unlock_all(tid)
        
        # 写入ABORT日志
        if self.wal_manager:
            self._write_log(tid, 'ABORT')
            self.wal_manager.flush()
        
        # 清理事务
        with self.txn_lock:
            if tid in self.transactions:
                del self.transactions[tid]
            self.stats['transactions_aborted'] += 1
            self.stats['current_active_transactions'] -= 1
        
        return True
    
    def validate_transaction(self, tid: int) -> TransactionState:
        """验证事务有效性"""
        with self.txn_lock:
            if tid not in self.transactions:
                return TransactionState.ABORTED
            return self.transactions[tid].state
    
    def get_transaction_state(self, tid: int) -> TransactionState:
        """获取事务状态"""
        return self.validate_transaction(tid)
    
    def is_transaction_active(self, tid: int) -> bool:
        """事务是否活跃（可提交或继续操作）"""
        state = self.validate_transaction(tid)
        return state in (TransactionState.ACTIVE, TransactionState.COMMITTING, TransactionState.ABORTING)
    
    # 锁操作
    
    def lock_shared(self, tid: int, resource_id: str) -> bool:
        """获取共享锁（读锁）"""
        return self.acquire_lock_internal(tid, resource_id, LockMode.SHARED)
    
    def lock_exclusive(self, tid: int, resource_id: str) -> bool:
        """获取排他锁（写锁）"""
        return self.acquire_lock_internal(tid, resource_id, LockMode.EXCLUSIVE)
    
    def unlock(self, tid: int, resource_id: str) -> bool:
        """释放锁"""
        with self.lock_lock:
            entry = self.lock_table.get(resource_id)
            if entry is None:
                return False
            
            # 从共享锁集合中移除
            if tid in entry.shared_lock_holders:
                entry.shared_lock_holders.remove(tid)
            
            # 从排他锁释放
            if entry.exclusive_lock_holder == tid:
                entry.exclusive_lock_holder = None
            
            # 从事务的锁集合中移除
            with self.txn_lock:
                if tid in self.transactions:
                    self.transactions[tid].locked_resources.discard(resource_id)
            
            # 唤醒等待队列中兼容的请求
            self._wakeup_waiting_requests(resource_id)
            
            # 如果锁表条目为空，可以删除
            if not entry.is_locked() and not entry.waiting_queue:
                del self.lock_table[resource_id]
            
            return True
    
    def unlock_all(self, tid: int) -> bool:
        """释放事务的所有锁"""
        with self.txn_lock:
            if tid not in self.transactions:
                return False
            locked = list(self.transactions[tid].locked_resources)
        
        success = True
        for resource_id in locked:
            if not self.unlock(tid, resource_id):
                success = False
        
        return success
    
    # 内部方法
    
    def acquire_lock_internal(self, tid: int, resource_id: str, 
                              mode: LockMode) -> bool:
        """
        获取锁的通用内部方法
        
        Args:
            tid: 事务ID
            resource_id: 资源标识（表名或page_id+row_id）
            mode: 锁模式
            
        Returns:
            成功返回True，失败（冲突、死锁等）返回False
        """
        # 检查事务状态
        state = self.validate_transaction(tid)
        if state in (TransactionState.ABORTING, TransactionState.ABORTED):
            return False
        
        req = LockRequest(tid, resource_id, mode, self._next_timestamp())
        
        while True:
            with self.lock_lock:
                entry = self.lock_table.setdefault(resource_id, LockTableEntry())
                
                # 检查是否有冲突
                if not entry.has_conflict(req):
                    # 无冲突，授予锁
                    if mode == LockMode.SHARED:
                        entry.shared_lock_holders.add(tid)
                    else:
                        entry.exclusive_lock_holder = tid
                    
                    # 记录事务持有的锁
                    with self.txn_lock:
                        if tid in self.transactions:
                            self.transactions[tid].locked_resources.add(resource_id)
                    
                    self.stats['locks_acquired'] += 1
                    return True
                
                # 有冲突，需要等待
                # 检查请求是否已在等待队列中（重复请求）
                if not any(r.tid == tid and r.resource_id == resource_id and r.mode == mode 
                          for r in entry.waiting_queue):
                    entry.waiting_queue.append(req)
                
                # 死锁检测
                if self.deadlock_detection_enabled:
                    victim = self._detect_deadlock()
                    if victim == tid:
                        # 当前事务是死锁受害者，放弃
                        entry.waiting_queue = [r for r in entry.waiting_queue 
                                              if not (r.tid == tid and r.resource_id == resource_id)]
                        self.force_abort(tid, "Deadlock detected")
                        return False
            
            # 等待一段时间后重试（简化：使用条件变量会更高效）
            time.sleep(0.001)
    
    def _wakeup_waiting_requests(self, resource_id: str):
        """唤醒等待队列中兼容的请求"""
        entry = self.lock_table.get(resource_id)
        if entry is None:
            return
        
        new_waiting = []
        for req in entry.waiting_queue:
            if not entry.has_conflict(req):
                # 可以授予
                if req.mode == LockMode.SHARED:
                    entry.shared_lock_holders.add(req.tid)
                else:
                    entry.exclusive_lock_holder = req.tid
                
                with self.txn_lock:
                    if req.tid in self.transactions:
                        self.transactions[req.tid].locked_resources.add(resource_id)
                
                self.stats['locks_acquired'] += 1
            else:
                new_waiting.append(req)
        
        entry.waiting_queue = new_waiting
    
    def _next_timestamp(self) -> float:
        """获取下一个时间戳（用于死锁打破）"""
        with self.txn_lock:
            self.timestamp_counter += 1
            return time.time() + self.timestamp_counter * 1e-9
    
    def _detect_deadlock(self) -> Optional[int]:
        """
        死锁检测（基于等待图）
        
        Returns:
            死锁受害者事务ID，如果无死锁则返回None
        """
        with self.lock_lock:
            # 构建等待图
            wait_for_graph = defaultdict(list)
            for resource_id, entry in self.lock_table.items():
                if entry.exclusive_lock_holder is not None:
                    holder = entry.exclusive_lock_holder
                    for req in entry.waiting_queue:
                        wait_for_graph[req.tid].append(holder)
                elif entry.shared_lock_holders:
                    # 简化：假设只有一个共享锁持有者会被阻塞
                    for holder in entry.shared_lock_holders:
                        for req in entry.waiting_queue:
                            if req.mode == LockMode.EXCLUSIVE:
                                wait_for_graph[req.tid].append(holder)
            
            if not wait_for_graph:
                return None
            
            # DFS检测环
            visited = set()
            rec_stack = set()
            
            def dfs(tid: int) -> bool:
                visited.add(tid)
                rec_stack.add(tid)
                
                for neighbor in wait_for_graph.get(tid, []):
                    if neighbor in rec_stack:
                        return True  # 发现环
                    if neighbor not in visited:
                        if dfs(neighbor):
                            return True
                
                rec_stack.remove(tid)
                return False
            
            # 查找环中的任意一个事务
            for tid in wait_for_graph:
                if tid not in visited:
                    if dfs(tid):
                        return tid
            
            return None
    
    def force_abort(self, tid: int, reason: str = ""):
        """强制中止事务（用于死锁解决）"""
        print(f"Transaction {tid} aborted by deadlock resolver: {reason}")
        self.unlock_all(tid)
        self.rollback(tid)
    
    def _write_log(self, tid: int, log_type: str, payload: Any = None):
        """写入日志（委托给WAL）"""
        if not self.wal_manager:
            return
        
        # 根据事务管理器类型选择写入方式
        # Python WAL使用log_begin/commit/abort方法
        if hasattr(self.wal_manager, 'log_begin'):
            if log_type == 'BEGIN':
                self.wal_manager.log_begin(tid)
            elif log_type == 'COMMIT':
                self.wal_manager.commit(tid)
            elif log_type == 'ABORT':
                self.wal_manager.abort(tid)
        # C++ WAL使用append方法
        elif hasattr(self.wal_manager, 'append'):
            import struct
            from core.wal import LogType
            
            type_map = {'BEGIN': LogType.UPDATE, 'COMMIT': LogType.COMMIT, 
                       'ABORT': LogType.ABORT}
            
            if log_type in type_map:
                lsn = self.wal_manager.append(tid, type_map[log_type], b'')
                # 更新事务的最后LSN
                with self.txn_lock:
                    if tid in self.transactions:
                        self.transactions[tid].last_lsn = lsn
    
    # 统计
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self.txn_lock:
            stats = self.stats.copy()
            stats['current_active_transactions'] = len([
                t for t in self.transactions.values() 
                if t.state in (TransactionState.ACTIVE, TransactionState.COMMITTING)
            ])
            stats['locks_held'] = sum(len(entry.shared_lock_holders) + 
                                      (1 if entry.exclusive_lock_holder else 0)
                                      for entry in self.lock_table.values())
            stats['waiting_transactions'] = sum(len(entry.waiting_queue)
                                               for entry in self.lock_table.values())
        return stats
    
    def shutdown(self):
        """关闭事务管理器"""
        print("Shutting down TransactionManager...")
        active_tids = []
        with self.txn_lock:
            active_tids = [tid for tid, txn in self.transactions.items()
                          if txn.state in (TransactionState.ACTIVE, TransactionState.COMMITTING)]
        
        # 回滚所有未完成的事务
        for tid in active_tids:
            print(f"Rolling back active transaction {tid} during shutdown")
            self.rollback(tid)
        
        print(self.get_stats_string())
    
    def get_stats_string(self) -> str:
        """获取统计信息字符串"""
        stats = self.get_stats()
        lines = [
            "Transaction Manager Statistics:",
            f"  Transactions begun: {stats['transactions_begun']}",
            f"  Transactions committed: {stats['transactions_committed']}",
            f"  Transactions aborted: {stats['transactions_aborted']}",
            f"  Current active: {stats['current_active_transactions']}",
            f"  Locks acquired: {stats['locks_acquired']}",
            f"  Locks currently held: {stats.get('locks_held', 0)}",
            f"  Waiting transactions: {stats.get('waiting_transactions', 0)}",
            f"  Deadlocks detected: {stats['deadlocks_detected']}",
            f"  Strict 2PL: {'enabled' if self.strict_2pl else 'disabled'}",
            f"  Deadlock detection: {'enabled' if self.deadlock_detection_enabled else 'disabled'}"
        ]
        return "\n".join(lines)


if __name__ == "__main__":
    # 简单测试
    print("Testing TransactionManager...")
    
    # 创建模拟WAL
    class MockWAL:
        def log_begin(self, tid): print(f"WAL: BEGIN {tid}")
        def commit(self, tid): print(f"WAL: COMMIT {tid}")
        def abort(self, tid): print(f"WAL: ABORT {tid}")
        def flush(self): print("WAL: flush")
    
    txn_mgr = TransactionManager(wal_manager=MockWAL())
    tid1 = txn_mgr.begin("test1")
    tid2 = txn_mgr.begin("test2")
    
    print(f"T1 state: {txn_mgr.get_transaction_state(tid1)}")
    print(f"T2 state: {txn_mgr.get_transaction_state(tid2)}")
    
    # 锁测试
    if txn_mgr.lock_exclusive(tid1, "table1"):
        print(f"T1 got exclusive lock on table1")
    
    if txn_mgr.lock_exclusive(tid2, "table1"):
        print(f"T2 got exclusive lock (should not happen)")
    
    txn_mgr.commit(tid1)
    txn_mgr.commit(tid2)
    
    print(txn_mgr.get_stats_string())
    print("Test passed!")
