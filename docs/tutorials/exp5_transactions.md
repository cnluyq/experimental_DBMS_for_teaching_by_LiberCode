# 实验5：事务管理与并发控制

## 实验目标

1. 理解ACID事务特性的实现原理
2. 实现两阶段锁协议（2PL）
3. 学习锁管理器设计
4. 掌握死锁检测和恢复机制

## 实验环境

- 操作系统：Linux/macOS/Windows
- Python：3.8+
- 编辑器：任意文本编辑器

## 背景知识

### ACID特性

- **Atomicity（原子性）**：事务要么全部执行，要么全部不执行
- **Consistency（一致性）**：事务执行前后，数据库保持一致状态
- **Isolation（隔离性）**：并发事务互不干扰
- **Durability（持久性）**：事务提交后，修改永久保存

### 两阶段锁（2PL）

```
阶段1（Growing）：获取锁，不释放
  ├─ lock(table, X)  ✓
  ├─ lock(row, S)    ✓
  └─ ...             ✓

阶段2（Shrinking）：释放锁，不获取
  ├─ unlock(table)   ✓
  └─ unlock(row)     ✓
```

### 锁类型

| 锁模式 | 简写 | 兼容性 | 用途 |
|--------|------|--------|------|
| 共享锁 | S | S+S, S+X | SELECT |
| 排他锁 | X | S+X, X+X | INSERT/UPDATE/DELETE |

## 实验步骤

### 步骤1：理解现有事务管理代码

查看 `src/core/transaction.cpp` 或参考文档 `docs/modules/transaction.md`。

```cpp
// 伪代码：获取锁
bool TransactionManager::acquire_lock(int txn_id, const string& table, LockMode mode) {
    // 1. 检查锁表
    // 2. 如果可以获取，授予锁
    // 3. 否则等待或超时
}
```

### 步骤2：实现锁管理器（Python简化版）

```python
from enum import Enum
from typing import Dict, List, Optional

class LockMode(Enum):
    SHARED = "S"
    EXCLUSIVE = "X"

class TransactionState(Enum):
    ACTIVE = "active"
    COMMITTED = "committed"
    ABORTED = "aborted"

class Lock:
    def __init__(self):
        self.holders: Dict[int, LockMode] = {}  # txn_id -> mode
        self.waiting: List[tuple] = []  # [(txn_id, mode), ...]

class TransactionManager:
    def __init__(self):
        self.lock_table: Dict[str, Lock] = {}  # table -> Lock
        self.transactions: Dict[int, TransactionState] = {}
        self.next_txn_id = 1

    def begin(self) -> int:
        txn_id = self.next_txn_id
        self.next_txn_id += 1
        self.transactions[txn_id] = TransactionState.ACTIVE
        return txn_id

    def acquire_lock(self, txn_id: int, table: str, mode: LockMode) -> bool:
        """
        尝试获取锁
        
        规则：
        - X锁：不能有其他事务持有任何锁
        - S锁：不能有事务持有X锁
        
        返回：True获取成功，False需要等待
        """
        if table not in self.lock_table:
            self.lock_table[table] = Lock()
        
        lock = self.lock_table[table]
        
        # 检查是否可以获取
        if mode == LockMode.EXCLUSIVE:
            # X锁需要表完全空闲
            if len(lock.holders) == 0:
                lock.holders[txn_id] = mode
                return True
        else:
            # S锁需要无X锁
            has_x = any(m == LockMode.EXCLUSIVE for m in lock.holders.values())
            if not has_x:
                lock.holders[txn_id] = mode
                return True
        
        return False  # 需要等待
```

### 步骤3：实现死锁检测

```python
def detect_deadlock(self) -> Optional[List[int]]:
    """
    基于等待图的死锁检测
    
    构建有向图：事务A等待事务B的锁 → A → B
    检测环：DFS或拓扑排序
    """
    # 等待图：waiting[txn] = blocked_by_txn
    wait_graph: Dict[int, int] = {}
    
    for table, lock in self.lock_table.items():
        for txn_id, mode in lock.holders.items():
            # 检查是否有事务在等待这个锁
            for waiting_txn, waiting_mode in lock.waiting:
                if waiting_mode == LockMode.EXCLUSIVE or mode == LockMode.EXCLUSIVE:
                    wait_graph[waiting_txn] = txn_id
    
    # 检测环（DFS）
    visited = set()
    stack = set()
    
    def has_cycle(txn: int) -> bool:
        if txn in stack:
            return True  # 发现环
        if txn in visited:
            return False
        visited.add(txn)
        stack.add(txn)
        
        if txn in wait_graph:
            if has_cycle(wait_graph[txn]):
                return True
        stack.remove(txn)
        return False
    
    for txn in wait_graph:
        if has_cycle(txn):
            return self._get_deadlock_cycle(txn, wait_graph)
    
    return None

def _get_deadlock_cycle(self, start: int, graph: Dict) -> List[int]:
    """获取死锁环中的事务列表"""
    cycle = [start]
    current = start
    while graph.get(current) != start:
        current = graph[current]
        cycle.append(current)
    return cycle
```

### 步骤4：测试锁和死锁

```python
def test_locking():
    tm = TransactionManager()
    
    # 事务1获取X锁
    t1 = tm.begin()
    assert tm.acquire_lock(t1, "users", LockMode.EXCLUSIVE)
    print(f"T1: 获得X锁 on users")
    
    # 事务2尝试获取S锁（应失败）
    t2 = tm.begin()
    assert not tm.acquire_lock(t2, "users", LockMode.SHARED)
    print(f"T2: 等待S锁 on users")
    
    # 事务2尝试获取X锁（应失败）
    assert not tm.acquire_lock(t2, "users", LockMode.EXCLUSIVE)
    print(f"T2: 等待X锁 on users")
    
    # 事务1提交，释放锁
    tm.commit(t1)
    print(f"T1: 提交，释放锁")
    
    # 现在事务2可以获得S锁
    assert tm.acquire_lock(t2, "users", LockMode.SHARED)
    print(f"T2: 获得S锁")
    
    tm.commit(t2)
    print("测试通过！")

def test_deadlock():
    tm = TransactionManager()
    
    # 创建死锁场景
    t1 = tm.begin()  # T1持有A，等待B
    t2 = tm.begin()  # T2持有B，等待A
    
    tm.acquire_lock(t1, "A", LockMode.EXCLUSIVE)
    tm.acquire_lock(t2, "B", LockMode.EXCLUSIVE)
    
    # T1尝试获取B（被T2持有）
    tm.lock_table["B"].waiting.append((t1, LockMode.EXCLUSIVE))
    
    # T2尝试获取A（被T1持有）
    tm.lock_table["A"].waiting.append((t2, LockMode.EXCLUSIVE))
    
    # 检测死锁
    cycle = tm.detect_deadlock()
    print(f"检测到死锁: {cycle}")
    assert cycle is not None
    
    # 选择一个事务回滚打破死锁
    victim = min(cycle)  # 选择ID最小
    tm.abort(victim)
    print(f"回滚事务 {victim}，打破死锁")
```

## 扩展任务

### 扩展1：实现超时回滚

```python
def acquire_lock_with_timeout(self, txn_id, table, mode, timeout=5):
    import time
    start = time.time()
    
    while True:
        if self.acquire_lock(txn_id, table, mode):
            return True
        
        if time.time() - start > timeout:
            raise TimeoutError(f"Lock timeout for {table}")
        
        time.sleep(0.1)  # 等待100ms重试
```

### 扩展2：实现锁升级

```python
# S锁升级为X锁
def upgrade_lock(self, txn_id: int, table: str) -> bool:
    lock = self.lock_table.get(table)
    if not lock:
        return False
    
    # 只有当前事务持有S锁才能升级
    if lock.holders.get(txn_id) != LockMode.SHARED:
        return False
    
    # 检查是否有其他S锁持有者
    has_other_s = any(tid != txn_id and mode == LockMode.SHARED
                      for tid, mode in lock.holders.items())
    if has_other_s:
        return False
    
    # 可以升级
    lock.holders[txn_id] = LockMode.EXCLUSIVE
    return True
```

## 验证标准

完成本实验后，你的代码应该能够：

- [ ] 正确处理S锁和X锁的互斥
- [ ] 正确处理锁等待队列
- [ ] 检测死锁并找出环
- [ ] 回滚死锁中的事务
- [ ] 通过上述所有测试用例

## 参考资料

- `docs/modules/transaction.md`：事务管理器详解
- `src/core/transaction.cpp`：C++实现参考
- `tests/`目录：单元测试

## 思考题

1. 为什么严格2PL（Strict 2PL）比普通2PL更好？
2. 如果不使用锁，还有什么方式实现并发控制？
3. 死锁检测的频率如何选择？太频繁影响性能，太慢会导致长时间等待。

---

**下一步**：完成实验后，尝试 [实验6：查询执行引擎](exp6_query_engine.md)（如已实现）