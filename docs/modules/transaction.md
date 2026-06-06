# 事务管理器模块详解

## 目录
- [概述](#概述)
- [ACID特性](#acid特性)
- [并发控制](#并发控制)
  - [两阶段锁（2PL）](#两阶段锁2pl)
  - [锁类型](#锁类型)
  - [死锁处理](#死锁处理)
- [系统架构](#系统架构)
- [核心类详解](#核心类详解)
- [隔离级别](#隔离级别)
- [与WAL协同](#与wal协同)
- [实验项目](#实验项目)
- [常见问题](#常见问题)

---

## 概述

事务管理器负责维护数据库的ACID特性，提供并发事务控制。ProjoDB实现**严格两阶段锁（Strict 2PL）**，配合WAL实现原子性和持久性。

### 核心职责

1. **事务生命周期**：BEGIN → 操作 → COMMIT/ROLLBACK
2. **并发控制**：锁管理（共享锁S、排他锁X）
3. **隔离性**：防止脏读、不可重复读、幻读
4. **恢复协调**：与WAL协作，保证持久性

### 重要概念

- **事务ID (txn_id)**：全局唯一，单调递增
- **锁粒度**：表级锁（教学简化，可扩展为行级）
- **锁模式**：S（共享）允许多读，X（排他）独占
- **锁表**：table_name → 等待队列 + 持有事务列表

---

## ACID特性

### 原子性（Atomicity）

**定义**：事务要么全部完成，要么全部不执行。

**实现**：
- 正常提交：记录COMMIT日志
- 异常回滚：用UPDATE的before_image回滚所有修改
- WAL保证即使崩溃也能undo

### 一致性（Consistency）

**定义**：事务将数据库从一致状态转换到另一一致状态。

**实现**：
- 应用层保证业务规则（如余额不为负）
- 约束检查：主键、外键、非空等（完整性和约束模块）

### 隔离性（Isolation）

**定义**：并发事务互不干扰。

**实现**：
- 锁机制：2PL确保可串行化
- 隔离级别：Read Committed（默认）

### 持久性（Durability）

**定义**：已提交事务的修改永久保留。

**实现**：
- WAL：提交前刷日志到磁盘
- 后台刷脏页（延迟写）

---

## 并发控制

### 两阶段锁（2PL）

#### 规则

1. **Growing Phase**：可以获取锁，不能释放
2. **Shrinking Phase**：可以释放锁，不能获取新锁
3. **释放时机**：COMMIT或ROLLBACK时一次性释放所有锁

#### 为什么能保证可串行化？

**冲突可串行化**：2PL防止循环依赖，等价于某个串行顺序。

**示例**：
```
事务T1: 读A → 读B → 写A → 提交
事务T2:         读A → 写B → 提交
```
2PL下，如果T2在T1释放A锁前读取A，则T2必须等待，消除了冲突。

---

### 锁类型

| 模式 | 互操作性 | 说明 | SQL对应 |
|------|----------|------|---------|
| S (Shared) | S✓ S✓ X✗ | 共享锁，多事务可同时读 | `SELECT ... LOCK IN SHARE MODE` |
| X (Exclusive) | S✗ X✗ X✗ | 排他锁，独占读写 | `SELECT ... FOR UPDATE`, `INSERT/UPDATE/DELETE` |

#### 锁升级（Lock Escalation）

**问题**：大量行锁升级为表锁，降低并发。

**ProjoDB策略**：暂时使用表级锁（简化），不考虑升级。

---

### 死锁处理

#### 死锁检测（Wait-Die / Wound-Wait）

**Wait-Die**（较老事务等，年轻事务死）：
```
如果 Txn T 想锁住资源，而该资源被 Txn S 持有：
  如果 T.timestamp < S.timestamp（T更老）：
    T 等待 S 释放锁
  否则：
    T 回滚（die）并稍后重试
```

**Wound-Wait**（较老事务 wound，年轻事务等）：
```
如果 T 想锁住资源，而该资源被 S 持有：
  如果 T.timestamp < S.timestamp（T更老）：
    S 回滚（wound），T 获得锁
  否则：
    T 等待 S 释放
```

**ProjoDB方案**：简单超时回滚（适合教学）
```python
def acquire_lock(self, txn_id, table, mode, timeout=5):
    start = time.time()
    while True:
        with self.lock:
            # 检查是否可以获取锁
            if self._can_acquire(table, txn_id, mode):
                self._grant_lock(table, txn_id, mode)
                return True

        # 等待或超时
        if time.time() - start > timeout:
            raise TransactionError(f"Lock timeout for {table}")
        time.sleep(0.01)
```

---

## 系统架构

```
TransactionManager
├── 事务表：txn_id → Transaction（状态、锁集）
├── 锁表：table_name → Lock（模式、持有者、等待队列）
├── 等待图 Wait-For Graph（死锁检测）
└── WALManager（日志交互）
```

---

## 核心类详解

### Transaction

```python
class Transaction:
    """事务对象"""

    def __init__(self, txn_id):
        self.txn_id = txn_id
        self.state = TransactionState.ACTIVE  # ACTIVE, COMMITTED, ABORTED
        self.locks: Dict[str, LockMode] = {}  # table → mode
        self.undo_log: List[LogRecord] = []  # 用于回滚

class TransactionState(Enum):
    ACTIVE = "active"
    COMMITTED = "committed"
    ABORTED = "aborted"
```

### TransactionManager

```python
class TransactionManager:
    """事务管理器"""

    def __init__(self, wal_manager):
        self.wal = wal_manager
        self.txns: Dict[int, Transaction] = {}
        self.next_txn_id = 1
        self.lock_table: Dict[str, Lock] = {}  # table → Lock
        self.lock = threading.RLock()

    def begin(self) -> int:
        """开始新事务"""
        txn_id = self.next_txn_id
        self.next_txn_id += 1

        txn = Transaction(txn_id)
        self.txns[txn_id] = txn

        # 记录BEGIN日志
        self.wal.log_begin(txn_id)

        return txn_id

    def commit(self, txn_id: int):
        """提交事务"""
        txn = self._get_txn(txn_id)
        if txn.state != TransactionState.ACTIVE:
            raise TransactionError(f"Transaction {txn_id} not active")

        # 1. 写COMMIT日志
        self.wal.log_commit(txn_id)
        self.wal.flush()  # 强制刷盘（持久性保证）

        # 2. 释放所有锁
        self._release_all_locks(txn)

        # 3. 标记事务已提交
        txn.state = TransactionState.COMMITTED

        # 4. 清理事务表（可选延迟，直到所有使用该事务的线程完）
        # 通常等待所有使用该txn_id的线程完成
        self.txns.pop(txn_id, None)

    def rollback(self, txn_id: int):
        """回滚事务"""
        txn = self._get_txn(txn_id)

        # 1. 根据undo_log回滚数据页（用before_image）
        for record in reversed(txn.undo_log):
            self._apply_undo(record)

        # 2. 写ROLLBACK日志
        self.wal.log_rollback(txn_id)
        self.wal.flush()

        # 3. 释放所有锁
        self._release_all_locks(txn)

        # 4. 标记事务已回滚
        txn.state = TransactionState.ABORTED
        self.txns.pop(txn_id, None)

    def acquire_lock(self, txn_id: int, table: str, mode: LockMode, timeout=5):
        """
        获取表锁

        Args:
            mode: LockMode.SHARED or LockMode.EXCLUSIVE
            timeout: 超时秒数，None表示无限等待

        Returns:
            True 获取成功，否则抛出异常
        """
        start = time.time()
        while True:
            with self.lock:
                if self._can_acquire(table, txn_id, mode):
                    self._grant_lock(table, txn_id, mode)
                    return True

            # 检查超时
            if timeout and (time.time() - start) > timeout:
                raise TransactionError(f"Lock wait timeout for {table}")

            time.sleep(0.01)  # 等待一段时间再试

    def _can_acquire(self, table: str, txn_id: int, mode: LockMode) -> bool:
        """检查是否可以获取锁（不实际获取）"""
        lock = self.lock_table.get(table)
        if not lock:
            return True  # 无锁

        # 如果请求X锁，必须无其他任何锁
        if mode == LockMode.EXCLUSIVE:
            if len(lock.holders) == 1 and txn_id in lock.holders:
                return True  # 自己已有X锁，重入适用？
            return len(lock.holders) == 0 and len(lock.waiting) == 0

        # 如果请求S锁，必须无X锁（S锁可共享）
        if mode == LockMode.SHARED:
            if LockMode.EXCLUSIVE in lock.holders.values():
                return False
            if txn_id in lock.holders:
                return True  # 已有S锁
            return True

        return False

    def _grant_lock(self, table: str, txn_id: int, mode: LockMode):
        """授予锁"""
        if table not in self.lock_table:
            self.lock_table[table] = Lock()
        lock = self.lock_table[table]
        lock.holders[txn_id] = mode
        # 从等待队列移除（如果存在）
        lock.waiting = [(tid, m) for tid, m in lock.waiting if tid != txn_id]

    def _release_all_locks(self, txn: Transaction):
        """释放事务的所有锁"""
        with self.lock:
            for table in list(txn.locks.keys()):
                lock = self.lock_table.get(table)
                if lock:
                    lock.holders.pop(txn.txn_id, None)
                    # 如果锁不再被持有，通知等待者（简化：重新检查所有等待）
                    if not lock.holders:
                        # 实际应唤醒特定等待者，此处简化
                        pass

    def _get_txn(self, txn_id) -> Transaction:
        txn = self.txns.get(txn_id)
        if not txn:
            raise TransactionError(f"Transaction {txn_id} not found")
        return txn
```

### Lock

```python
class Lock:
    """表锁"""

    def __init__(self):
        self.holders: Dict[int, LockMode] = {}  # txn_id → mode
        self.waiting: List[Tuple[int, LockMode]] = []  # [(txn_id, mode)]

class LockMode(Enum):
    SHARED = "S"
    EXCLUSIVE = "X"
```

---

## 隔离级别

### 标准隔离级别

| 级别 | 脏读 | 不可重复读 | 幻读 | 实现 |
|------|------|------------|------|------|
| Read Uncommitted | ✗ | ✗ | ✗ | 无锁或S锁 |
| Read Committed | ✓ | ✗ | ✗ | S锁，读完后释放 |
| Repeatable Read | ✓ | ✓ | ✗ | S锁，事务全程持有 |
| Serializable | ✓ | ✓ | ✓ | 全表X锁或范围锁 |

### ProjoDB实现

**默认：Read Committed**

实现方式：
- SELECT：获取S锁，读完释放（或事务结束时释放）
- UPDATE/DELETE：获取X锁，事务结束释放

**升级到Repeatable Read**：
- 所有锁保持到事务结束
- 需要实现锁表遍历和检查

---

## 与WAL协同

### 日志记录指令

**代码插入点**：

```python
class Executor:
    def execute_update(self, table, new_values, where):
        txn_id = self.txn_manager.current_txn_id

        # 1. 获取锁
        self.txn_manager.acquire_lock(txn_id, table, LockMode.EXCLUSIVE)

        # 2. 读取旧数据（用于before image）
        old_data = self.storage.read_record(...)

        # 3. 记录日志（before & after）
        self.wal.log_update(
            txn_id=txn_id,
            page_id=page_id,
            before=old_data,
            after=new_data
        )

        # 4. 执行修改（内存/缓冲）
        self.storage.update_record(...)

        # 5. 记录undo信息
        txn = self.txn_manager.get_transaction(txn_id)
        txn.undo_log.append(record)
```

### 提交流程

```python
def commit(self, txn_id):
    # 1. 写COMMIT日志
    self.wal.log_commit(txn_id)

    # 2. 刷日志到磁盘（关键：确保日志持久）
    self.wal.flush()

    # 3. 释放锁
    self.txn_manager.release_locks(txn_id)

    # 4. 标记事务完成
    self.txn_manager.end_transaction(txn_id)

    # 5. 数据页延迟写回（后台线程）
    # buffer_manager.flush_dirty_pages_async()
```

---

## 实验项目

### 实验1：实现锁管理器

**目标**：完成`TransactionManager`的锁管理功能。

**步骤**：
1. 实现`acquire_lock()`、`_can_acquire()`、`_grant_lock()`
2. 实现锁表（`lock_table`）数据结构
3. 实现`_release_all_locks()`
4. 单元测试：多事务并发访问同一表

**测试场景**：
```python
# 事务1获取X锁
txn1 = txn_mgr.begin()
txn_mgr.acquire_lock(txn1, 'users', X)

# 事务2尝试获取X锁（应阻塞或超时）
txn2 = txn_mgr.begin()
try:
    txn_mgr.acquire_lock(txn2, 'users', X, timeout=1)
    assert False, "应超时"
except TransactionError:
    pass  # 预期
```

---

### 实验2：实现S锁/X锁互斥

**目标**：验证S/X锁的正确互斥性。

**测试**：
1. T1获取S锁 → T2可以获取S锁（共享）
2. T1持有S锁 → T2请求X锁（应等待）
3. T1持有X锁 → T2任何锁都等待

---

### 实验3：死锁检测

**目标**：实现基于等待图的死锁检测。

**步骤**：
1. 维护等待图：txn_waiting_for[txn] = blocked_by_txn
2. 周期性检测环（拓扑排序或DFS）
3. 选择一个事务回滚（最年轻或最少代价）
4. 释放其锁，通知等待者

**等待图维护**：
```python
# 当T1等待T2的锁时：
self.wait_graph[txn1] = txn2

# 检测死锁（简单DFS）
def detect_deadlock(self):
    visited = set()
    stack = set()

    def dfs(txn):
        if txn in stack:
            return True  # 发现环
        if txn in visited:
            return False
        visited.add(txn)
        stack.add(txn)
        for victim in self.wait_graph.get(txn, []):
            if dfs(victim):
                return True
        stack.remove(txn)
        return False

    for txn in self.wait_graph:
        if dfs(txn):
            return True
    return False
```

---

### 实验4：隔离级别实验

**目标**：演示不同隔离级别下的并发异常。

**场景**：脏读、不可重复读

```sql
-- 事务1（未提交）
BEGIN;
UPDATE users SET balance = 100 WHERE id = 1;
-- 事务2
BEGIN;
SELECT balance FROM users WHERE id = 1;  -- Read Uncommitted: 读到100（脏读）
COMMIT;
-- 事务1
ROLLBACK;
```

观察不同锁策略下的结果。

---

## 常见问题

### Q1: 锁粒度如何选择？

**A**:
- **表级锁**：简单，适合教学；并发低，不适合生产
- **行级锁**：复杂（需要索引或记录ID），并发高
- **页级锁**：折中方案

ProjoDB教学可先实现表级锁，后续扩展行级锁。

---

### Q2: 如何实现锁超时和重试？

**A**：
```python
def acquire_lock(self, txn_id, table, mode, timeout=5, retry_interval=0.01):
    start = time.time()
    while True:
        try:
            self._try_acquire(txn_id, table, mode)
            return True
        except LockBusyError:
            if timeout and time.time() - start > timeout:
                raise TimeoutError()
            time.sleep(retry_interval)  # 等待后重试
```

---

### Q3: 锁表大小无限增长怎么办？

**A**：
- 事务结束时清理该事务的所有锁条目
- 定期清理长时间未活动的事务（防内存泄漏）
- 分布式锁管理器需要额外机制（如租约）

---

### Q4: 事务嵌套怎么处理？

**A**：通常不支持嵌套（BEGIN后不能再BEGIN）。有三种方案：
1. **不支持**：嵌套BEGIN返回错误
2. **保存点（SAVEPOINT）**：部分回滚到标记点
3. **隐式嵌套**：计数，最外层COMMIT才真正提交

ProjoDB简化：不支持嵌套。

---

## 参考代码

- `src/core/transaction.cpp`：C++实现（约500行）
- `docs/DATABASE_DESIGN.md`中的事务章节
- 测试文件：`tests/test_transaction.py`（待创建）

---

**下一步**：学习 [查询执行器](executor.md) 或继续 [实验5：事务管理](docs/tutorials/exp5_transaction.md)
