# WAL日志系统模块详解

## 目录
- [概述](#概述)
- [WAL协议原理](#wal协议原理)
- [日志记录格式](#日志记录格式)
- [系统架构](#系统架构)
- [核心类详解](#核心类详解)
- [崩溃恢复算法](#崩溃恢复算法)
- [检查点机制](#检查点机制)
- [实验项目](#实验项目)
- [常见问题](#常见问题)

---

## 概述

Write-Ahead Logging（WAL，预写日志）是数据库保证ACID特性的核心机制。其核心原则是：**在数据页修改之前，必须先将修改记录写入日志**。

### 为什么需要WAL？

1. **原子性（Atomicity）**：通过undo确保事务要么全做要么全不做
2. **持久性（Durability）**：通过redo确保已提交事务的修改不会丢失
3. **性能**：将随机写转化为顺序写，延迟写回数据页

### 关键概念

- **LSN（Log Sequence Number）**：日志序列号，单调递增
- **Force**：事务提交时强制所有修改页面写回磁盘（性能差）
- **No-Force**：提交时不强制写回（延迟写回，性能好）
- **Steal**：缓冲区池可能将未提交页写回磁盘（需要undo）
- **No-Steal**：只有已提交页才写回（不需要undo）

ProjoDB使用 **No-Force + Steal**，即：
- 提交时不强制写数据页（性能好）
- 缓冲区池可能提前写回未提交页（需要undo恢复）

---

## WAL协议原理

### 基本流程

```
事务T1开始：
1. 写日志：[BEGIN, txn_id=T1]
   → 必须fsync到磁盘

2. 修改数据页P：
   a) 内存修改P（标记脏）
   b) 写日志：[UPDATE, txn_id=T1, page_id=P, old_data, new_data]
      → 追加到日志缓冲区，不一定立即fsync

3. 提交：
   a) 写日志：[COMMIT, txn_id=T1]
   b) fsync日志（强制落盘）
   c) 返回"提交成功"给应用
   d) 数据页P可延迟写回（后台刷新）

如果此时崩溃，恢复时：
- 有COMMIT记录 → redo P的修改
- 无COMMIT记录 → undo P的修改（用old_data）
```

### Write-Ahead Logging规则

> **任何数据页P的修改，其对应的日志记录必须在P写回磁盘之前已持久化到磁盘**

形式化：
```
如果日志LSN(page.P) < log中的LSN(update)
则从日志中重做update
```

---

## 日志记录格式

### 日志记录格式

> ⚠️ **注意**：以下描述的是简化版Python教学实现的格式，与C++实现可能略有不同。

**实际代码格式**（`src/core/wal.py`）：
```
HEADER_FORMAT = 'QIBBQ'  # LSN(8), TxnID(4), Type(1), Size(4), PrevLSN(8)
总头部大小：25 bytes
```

### 记录头（固定大小25字节）

```
┌─────────────────────────────────────────────┐
│ LSN (8 bytes)                               │  ← 日志序列号，单调递增
│ TxnID (4 bytes)                             │  ← 事务ID
│ Type (1 byte)                               │  ← 记录类型
│   1=UPDATE, 2=INSERT, 3=DELETE             │
│   4=COMMIT, 5=ABORT, 6=CHECKPOINT          │
│ Size (4 bytes)                              │  ← 负载长度（payload字节数）
│ PrevLSN (8 bytes)                           │  ← 同一事务上一条记录的LSN
└─────────────────────────────────────────────┘
```

### LogType枚举（实际代码）

```python
class LogType(IntEnum):
    UPDATE = 1     # 更新操作
    INSERT = 2     # 插入操作
    DELETE = 3     # 删除操作
    COMMIT = 4     # 事务提交
    ABORT = 5      # 事务中止
    CHECKPOINT = 6 # 检查点

# 注意：简化版不记录BEGIN，事务的第一条操作日志隐含BEGIN
```

### 记录负载（变长）

各操作类型的实际payload格式：

#### UPDATE记录
```python
# 实际代码（build_update_payload函数）：
# page_id(4), offset(4), old_len(2), new_len(2), old_value, new_value
```

```
┌─────────────────────────────────────────────┐
│ PageID (4 bytes)                            │  ← 修改的数据页
│ Offset (4 bytes)                            │  ← 页内偏移
│ old_len (2 bytes)                           │  ← 旧数据长度
│ new_len (2 bytes)                           │  ← 新数据长度
│ old_value (old_len bytes)                   │  ← 修改前的数据
│ new_value (new_len bytes)                   │  ← 修改后的数据
└─────────────────────────────────────────────┘
```

#### INSERT记录
```python
# 实际代码（build_insert_payload函数）：
# page_id(4), offset(4), length(2), data
```

#### DELETE记录
```python
# 实际代码（build_delete_payload函数）：
# page_id(4), offset(4), old_len(2), old_data
```

#### COMMIT/ABORT记录
```
┌─────────────────────────────────────────────┐
│ [空]（仅靠头部Type标识）                    │
└─────────────────────────────────────────────┘
```

#### CHECKPOINT记录
```python
# 实际payload是JSON：
checkpoint_data = {
    'dirty_pages': [(page_id, rec_lsn), ...],
    'active_transactions': [tid1, tid2, ...],
    'timestamp': 'ISO格式时间',
    'next_lsn': 下一个可用LSN
}
```

### 序列化示例（Python）
```

---

## 系统架构

```
┌─────────────────────────────────────────────┐
│           WALManager (管理器)               │
│  • log_begin(txn_id)                       │
│  • log_update(txn_id, page_id, before, after)│
│  • log_commit(txn_id)                      │
│  • log_rollback(txn_id)                    │
│  • flush(lsn)                              │
│  • recover()                               │
├─────────────────────────────────────────────┤
│           LogBuffer (内存缓冲区)            │
│  • 预写日志缓存（减少syscall）             │
│  • 组提交（Group Commit）                  │
├─────────────────────────────────────────────┤
│           LogFile (磁盘文件)                │
│  • 顺序追加写                              │
│  • 固定大小分段（如4MB）                   │
│  • 归档和截断                              │
└─────────────────────────────────────────────┘
```

---

## 核心类详解

### WALManager（Python参考）

```python
class LogRecord:
    """日志记录类（实际实现）"""
    # 格式：LSN(8), TxnID(4), Type(1), Size(4), PrevLSN(8) = 25 bytes
    HEADER_FORMAT = 'QIBBQ'

    def __init__(self, lsn, txn_id, log_type, payload=b'', prev_lsn=0):
        self.lsn = lsn
        self.txn_id = txn_id
        self.type = log_type
        self.payload = payload
        self.prev_lsn = prev_lsn

    def serialize(self) -> bytes:
        header = struct.pack(self.HEADER_FORMAT, self.lsn, self.txn_id,
                            int(self.type), len(self.payload), self.prev_lsn)
        return header + self.payload

    @classmethod
    def deserialize(cls, data: bytes):
        lsn, tid, log_type_int, size, prev_lsn = struct.unpack(
            cls.HEADER_FORMAT, data[:25])
        return cls(lsn, tid, LogType(log_type_int), data[25:25+size], prev_lsn)


class WALManager:
    """
    WAL管理器，提供日志记录接口
    """

    def __init__(self, log_path: str, buffer_size: int = 4096):
        self.log_path = log_path
        self.buffer = bytearray(buffer_size)
        self.buffer_pos = 0
        self.next_lsn = 1
        self.active_txns: Dict[int, int] = {}  # txn_id → last_lsn
        self.file = open(log_path, 'ab+')
        self.file.seek(0, 2)  # 移动到末尾
        # 恢复时读取现有日志

    def log_begin(self, txn_id: int) -> int:
        """记录事务开始"""
        prev_lsn = self.active_txns.get(txn_id, 0)
        record = LogRecord(
            lsn=self.next_lsn,
            prev_lsn=prev_lsn,
            txn_id=txn_id,
            type=LogType.BEGIN,
            payload=b''
        )
        self._append_record(record)
        self.active_txns[txn_id] = self.next_lsn
        self.next_lsn += 1
        return record.lsn

    def log_update(self, txn_id: int, page_id: int,
                   before: bytes, after: bytes) -> int:
        """记录数据页更新"""
        prev_lsn = self.active_txns.get(txn_id, 0)
        # 序列化payload: page_id(4) + before_len(4) + before + after_len(4) + after
        payload = struct.pack('<I', page_id)
        payload += struct.pack('<I', len(before)) + before
        payload += struct.pack('<I', len(after)) + after

        record = LogRecord(
            lsn=self.next_lsn,
            prev_lsn=prev_lsn,
            txn_id=txn_id,
            type=LogType.UPDATE,
            payload=payload
        )
        self._append_record(record)
        self.active_txns[txn_id] = self.next_lsn
        self.next_lsn += 1
        return record.lsn

    def log_commit(self, txn_id: int) -> int:
        """记录事务提交"""
        prev_lsn = self.active_txns.get(txn_id, 0)
        record = LogRecord(
            lsn=self.next_lsn,
            prev_lsn=prev_lsn,
            txn_id=txn_id,
            type=LogType.COMMIT,
            payload=b''
        )
        self._append_record(record)
        # 提交后移除活跃事务
        self.active_txns.pop(txn_id, None)
        self.next_lsn += 1
        return record.lsn

    def _append_record(self, record: LogRecord):
        """追加记录到缓冲区，缓冲区满则刷盘"""
        data = record.serialize()
        if len(data) > len(self.buffer) - self.buffer_pos:
            self._flush_buffer()  # 缓冲区不足，刷盘
        # 复制到缓冲区
        self.buffer[self.buffer_pos:self.buffer_pos+len(data)] = data
        self.buffer_pos += len(data)

    def flush(self, lsn: int = None):
        """
        强制刷日志到磁盘

        Args:
            lsn: 刷写到至少这个LSN（包含），None表示刷全部
        """
        self._flush_buffer()
        self.file.flush()
        os.fsync(self.file.fileno())  # 强制落盘（关键！）

    def close(self):
        self.flush()
        self.file.close()

    def recover(self) -> RecoveryResult:
        """
        崩溃恢复（简化版）

        Returns:
            RecoveryResult(committed_txns, aborted_txns, redos, undos)
        """
        # 1. 分析：扫描整个日志
        txns = {}  # txn_id → {state, last_lsn, pages_modified}
        dirty_pages = {}  # page_id → rec_lsn

        for record in self._scan_log():
            txn_id = record.txn_id
            if txn_id not in txns:
                txns[txn_id] = {'state': 'active', 'last_lsn': 0, 'pages': set()}

            txn = txns[txn_id]
            txn['last_lsn'] = record.lsn

            if record.type == LogType.BEGIN:
                txn['state'] = 'active'
            elif record.type == LogType.COMMIT:
                txn['state'] = 'committed'
            elif record.type == LogType.ROLLBACK:
                txn['state'] = 'aborted'
            elif record.type == LogType.UPDATE:
                # 解析出page_id
                page_id = struct.unpack('<I', record.payload[:4])[0]
                txn['pages'].add(page_id)
                # 记录脏页及其首次修改LSN
                if page_id not in dirty_pages:
                    dirty_pages[page_id] = record.lsn

        # 2. 重做（redo）：所有已提交事务的修改
        redos = []
        for txn_id, txn in txns.items():
            if txn['state'] == 'committed':
                # 从该事务的first_lsn到last_lsn重放所有UPDATE
                redos.extend(self._redo_transaction(txn_id, txn['last_lsn']))

        # 3. 撤销（undo）：所有未提交事务的修改（用before_image）
        undos = []
        for txn_id, txn in txns.items():
            if txn['state'] in ('active', 'aborted'):
                # 逆序撤销（从后往前）
                undos.extend(self._undo_transaction(txn_id, txn['last_lsn']))

        return RecoveryResult(redos, undos)
```

---

## 崩溃恢复算法

### 三阶段恢复（ARIES简化）

#### 阶段1：分析（Analysis）

**目标**：确定哪些事务已提交、哪些未完成、哪些页面需要重做。

**扫描日志**，维护：
- `txn_table`：事务表（txn_id → {state, last_lsn, pages}）
- `dirty_page_table`：脏页表（page_id → rec_lsn）

**事务状态**：
- `COMMITTED`：找到COMMIT记录
- `ACTIVE`：有BEGIN但无COMMIT/ROLLBACK
- `ABORTED`：有ROLLBACK记录

#### 阶段2：重做（Redo）

**目标**：确保所有已提交事务的修改持久化到数据页。

**方法**：
```
从日志最旧的RecLSN开始，向前扫描：
  对每条UPDATE记录：
    如果 page.LSN < record.lsn：
      应用record.after_image到page
```

**幂等性**：重做多次效果相同（因为检查page.LSN）

#### 阶段3：撤销（Undo）

**目标**：回滚所有未提交事务的修改。

**方法**：
```
构造undo队列：所有未提交事务的last_lSN，按LSN降序排列
while 队列不空：
  lsn = 弹出队列头（最大LSN）
  读取该记录（UPDATE）
  用before_image回滚数据页
  如果该事务还有其他UPDATE，将其LSN加入队列
  生成CLR（Compensation Log Record）
```

**生产系统**：ARIES使用CLR和瀑布模型（cascading ablation），但教学系统可以简化为直接回滚。

---

## 检查点机制

### 为什么要检查点？

- 减少恢复时间：无需扫描整个日志
- 定期将内存脏页状态持久化到日志

### 检查点记录格式

```
┌─────────────────────────────────────────────┐
│ Checkpoint开始标记 (magic number)           │
├─────────────────────────────────────────────┤
│ 检查点LSN（本记录的位置）                   │
├─────────────────────────────────────────────┤
│ 脏页表 DirtyPageTable                       │
│   (page_id, rec_lsn) pairs                  │
├─────────────────────────────────────────────┤
│ 活跃事务列表 ActiveTxns                     │
│   [txn_id1, txn_id2, ...]                   │
└─────────────────────────────────────────────┘
```

### 检查点触发时机

1. **定期**：每N条日志或每T秒
2. **脏页阈值**：脏页数量达到一定比例
3. **事务提交**：特定事务（如大事务）提交时
4. **手动**：调用`CHECKPOINT`命令

### 恢复时使用检查点

```
1. 从日志末尾向前扫描，找到最后一个CHECKPOINT记录
2. 加载DirtyPageTable和ActiveTxns
3. Redo从Checkpoint的begin_lsn开始（而非日志开头）
4. Undo从ActiveTxns的last_lsn开始
```

---

## 实验项目

### 实验1：实现基础WAL Manager

**目标**：完成`WALManager`的基本功能。

**步骤**：
1. 在`src/core/wal.cpp`（或`src/core/wal.py`）实现：
   - `log_begin()`, `log_update()`, `log_commit()`
   - 序列化/反序列化
   - 缓冲区管理
2. 实现`flush()`强制刷盘
3. 单元测试：记录日志并能正确读取

**测试**：
```python
# 记录事务
wal = WALManager("test.log")
txn1 = wal.log_begin(1)
wal.log_update(1, 100, b'old', b'new')
wal.log_commit(1)
wal.flush()

# 读取验证
records = list(wal.scan_log())
assert len(records) == 3
```

---

### 实验2：实现恢复算法

**目标**：实现简化的恢复（先分析+redo，undo可选）。

**步骤**：
1. 实现`recover()`方法
2. 实现`_scan_log()`扫描所有记录
3. 实现`_redo_transaction()`重做已提交事务
4. 可选：实现`_undo_transaction()`回滚未提交事务

**测试场景**：
```
1. 正常提交：T1修改页100并提交 → 恢复后数据应为new
2. 崩溃未提交：T1修改页100但未提交 → 恢复后数据应为old
3. 部分提交：T1修改页100，T2修改页101并提交 → 恢复后100=old, 101=new
```

---

### 实验3：组提交（Group Commit）

**目标**：减少fsync频率，提升吞吐。

**问题**：每个事务提交都fsync，性能差。

**方案**：
```python
class WALManager:
    def __init__(self, ...):
        self.pending_commits = []  # 等待刷盘的COMMIT

    def log_commit(self, txn_id):
        # 记录COMMIT到缓冲区
        record = ...
        self._append_record(record)
        self.pending_commits.append(txn_id)

        # 如果达到阈值或超时，批量fsync
        if len(self.pending_commits) >= 10:
            self.flush()
            self.pending_commits.clear()
```

---

## 常见问题

### Q1: 为什么WAL记录要包含before image？

**A**：
- **Steal策略**：缓冲区池可能将未提交页写回磁盘（需要undo）
- **No-Force策略**：提交后数据页可能还在内存（需要redo）
- 只有UPDATE同时包含before/after才能支持：
  - **Undo**：用before回滚未提交修改
  - **Redo**：用after重做已提交修改

如果不用Steal（如SQLite WAL模式），可以不要before image。

---

### Q2: 日志文件会无限增长吗？

**A**：会，需要**日志截断（Truncation）**。

**时机**：
- **检查点后**：所有已提交事务的修改都写回数据文件
- **所有脏页都已重做**：旧日志不再需要

**方法**：
1. 检查点时记录**最早的RecLSN**（脏页表中最小的）
2. 该LSN之前的日志可删除/归档
3. 维护一个**日志序列号归档**表（用于长时间运行的事务）

---

### Q3: fsync性能太慢怎么办？

**A**：
1. **组提交**：累计多个事务一起fsync
2. **异步fsync**：单独线程负责刷盘（但崩溃可能丢数据）
3. **电池备份写缓存（BBWC）**：硬件支持
4. **reorder log writes**：确保顺序性（现代文件系统`O_DIRECT`）

**权衡**：持久性 vs 性能。

---

### Q4: 如何保证WAL自身的原子性？

**A**: WAL文件追加写本身是原子的（文件系统保证小于4KB写原子性）。但记录可能部分写入：
- **解决方案**：每个记录包含magic和checksum
- **恢复时**：读取失败则丢弃该记录（向前找到完整记录）

---

## 参考实现

- `src/core/wal.cpp`：C++版本（需要文件映射，性能优先）
- `src/core/wal.py`：Python参考实现（约600行，易于理解）
- `docs/DATABASE_DESIGN.md`中的WAL章节

---

**下一步**：学习 [事务管理器](transaction.md) 或继续 [实验4：WAL日志](docs/tutorials/exp4_wal.md)
