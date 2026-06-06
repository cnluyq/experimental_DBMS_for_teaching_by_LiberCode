# 事务管理器接口文档

## 概述

事务管理器提供ACID保证的核心支持，包括：
- 事务生命周期管理
- 并发控制（锁管理）
- WAL集成
- 死锁检测

## 核心组件

### TransactionState（事务状态枚举）

```python
class TransactionState(IntEnum):
    ACTIVE = 1        # 活跃
    COMMITTING = 2    # 提交中
    ABORTING = 3      # 回滚中
    COMMITTED = 4     # 已提交
    ABORTED = 5       # 已回滚
```

### LockMode（锁模式枚举）

```python
class LockMode(IntEnum):
    SHARED = 1        # 共享锁（读锁）
    EXCLUSIVE = 2     # 排他锁（写锁）
```

### TransactionManager（主类）

```python
from executor.transaction_manager import TransactionManager

txn_mgr = TransactionManager(
    wal_manager=wal_instance,      # 可选：WAL管理器
    strict_2pl=True,               # 严格两阶段锁
    deadlock_detection_enabled=True # 死锁检测
)
```

## 事务操作接口

### 开始事务

```python
tid = txn_mgr.begin(description: str = "") -> int
"""
返回值: 事务ID (int)
说明: 
  - 自动分配唯一的事务ID
  - 如果配置了WAL，写入BEGIN日志
  - 事务状态设为ACTIVE
"""
```

### 提交事务

```python
success = txn_mgr.commit(tid: int) -> bool
"""
参数: tid - 事务ID
返回值: 
  - True: 提交成功
  - False: 提交失败（事务不存在或状态不对）

说明:
  - 使用strict_2pl时，自动释放所有锁
  - 写入COMMIT日志并flush
  - 从事务表移除
"""
```

### 回滚事务

```python
success = txn_mgr.rollback(tid: int) -> bool
"""
参数: tid - 事务ID
返回值:
  - True: 回滚成功
  - False: 回滚失败

说明:
  - 释放事务持有的所有锁
  - 写入ABORT日志
  - 从事务表移除
"""
```

### 状态查询

```python
state = txn_mgr.get_transaction_state(tid: int) -> TransactionState
is_active = txn_mgr.is_transaction_active(tid: int) -> bool
```

## 锁操作接口

### 获取共享锁（读锁）

```python
success = txn_mgr.lock_shared(tid: int, resource_id: str) -> bool
"""
参数:
  - tid: 事务ID
  - resource_id: 资源标识（如 "table_name" 或 "table:row_id"）

返回值:
  - True: 成功获取锁
  - False: 获取失败（冲突或事务已结束）
  
说明:
  - 多个事务可以同时持有同一资源的共享锁
  - 共享锁与排他锁互斥
"""
```

### 获取排他锁（写锁）

```python
success = txn_mgr.lock_exclusive(tid: int, resource_id: str) -> bool
"""
参数:
  - tid: 事务ID
  - resource_id: 资源标识

返回值:
  - True: 成功获取锁
  - False: 获取失败

说明:
  - 排他锁独占资源
  - 与任何其他锁冲突
"""
```

### 释放锁

```python
success = txn_mgr.unlock(tid: int, resource_id: str) -> bool
```

### 释放所有锁

```python
success = txn_mgr.unlock_all(tid: int) -> bool
```

## 与Executor集成

### 方式1：使用Executor内置事务（当前实现）

Executor内部维护了简单的事务状态：

```python
executor = Executor(
    storage_engine=db_storage,
    buffer_pool=buffer,
    wal=wal,
    txn_manager=None  # 可选，暂未使用
)

# 通过SQL语句控制事务
executor.execute(ast)  # BEGIN
executor.execute(ast)  # DML操作
executor.execute(ast)  # COMMIT

# 或使用显式API
executor.start_transaction()
# ... 操作 ...
executor.commit_transaction()
executor.rollback_transaction()
```

### 方式2：集成完整TransactionManager（推荐）

```python
from executor.transaction_manager import TransactionManager

# 1. 初始化各组件
storage = SimpleFileStorage("db.dat", 4096)
buffer = BufferPool(100, storage)
wal = WALManager("wal.log", 4096)
wal.open()

# 2. 创建事务管理器
txn_mgr = TransactionManager(wal_manager=wal, strict_2pl=True)

# 3. 在操作前获取锁
tid = txn_mgr.begin("batch_insert")

# 锁住目标表
if not txn_mgr.lock_exclusive(tid, "users"):
    txn_mgr.rollback(tid)
    raise RuntimeError("无法获取锁")

# 4. 执行操作
manager.insert_record(data)
txn_mgr.unlock(tid, "users")

# 5. 提交
txn_mgr.commit(tid)
```

## 锁资源命名约定

```
表级锁:    "table:{table_name}"
行级锁:    "row:{table_name}:{row_id}"
页面级锁:   "page:{page_id}"
索引级锁:   "index:{index_name}"
```

## 统计信息

```python
stats = txn_mgr.get_stats()
# {
#   'transactions_begun': 42,
#   'transactions_committed': 40,
#   'transactions_aborted': 2,
#   'current_active_transactions': 0,
#   'locks_acquired': 156,
#   'locks_held': 0,
#   'waiting_transactions': 0,
#   'deadlocks_detected': 1
# }
```

## 优雅关闭

```python
# 关闭前回滚未完成事务
txn_mgr.shutdown()
# 输出统计信息
print(txn_mgr.get_stats_string())
```

## 注意事项

1. **严格2阶段锁（Strict 2PL）**: 默认启用，所有锁在COMMIT/ROLLBACK时释放
2. **死锁检测**: 默认启用，检测到死锁时选择受害者事务自动回滚
3. **线程安全**: TransactionManager内部使用锁保护共享状态，可安全用于多线程环境
4. **WAL集成**: 如果传入WAL管理器，事务操作会自动记录日志
5. **锁超时**: 当前简化实现未包含锁超时机制，可通过死锁检测处理长时间等待

## 示例代码

```python
# 完整使用示例
from executor.transaction_manager import TransactionManager

# 创建模拟WAL
class MockWAL:
    def log_begin(self, tid): print(f"[WAL] BEGIN {tid}")
    def commit(self, tid): print(f"[WAL] COMMIT {tid}")
    def abort(self, tid): print(f"[WAL] ABORT {tid}")
    def flush(self): pass

# 初始化
txn_mgr = TransactionManager(wal_manager=MockWAL())

# 开始事务
tid1 = txn_mgr.begin("更新用户余额")
tid2 = txn_mgr.begin("记录日志")

# 获取锁
txn_mgr.lock_exclusive(tid1, "accounts")

# 执行业务逻辑...

# 释放锁
txn_mgr.unlock(tid1, "accounts")

# 提交
txn_mgr.commit(tid1)
txn_mgr.commit(tid2)

# 输出统计
print(txn_mgr.get_stats_string())
```