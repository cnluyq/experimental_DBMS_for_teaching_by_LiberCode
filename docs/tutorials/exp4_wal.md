# 实验4：WAL预写日志

## 一、实验目标

1. ✅ 理解WAL（Write-Ahead Logging）协议原理
2. ✅ 实现日志记录格式和写入
3. ✅ 实现崩溃恢复算法（分析、重做、撤销）
4. ✅ 理解检查点（Checkpoint）机制
5. ✅ 测试原子提交和回滚

## 二、背景

### 为什么需要WAL？

问题：数据库在提交事务后未将数据刷盘就崩溃 → 数据丢失！

解决方案：WAL协议 —— **先写日志，后写数据**。

```
事务 T1:
  1. 修改内存页P（标记脏）
  2. 写日志记录 [UPDATE, T1, P, old_data, new_data]
  3. 刷日志到磁盘（fsync）
  4. COMMIT：写日志记录 [COMMIT, T1]
  5. 可选：稍后将P写回数据文件
```

崩溃恢复：
```
重启 → 扫描日志 → 找到已提交但数据未持久化的记录 → 重做
                      → 找到未提交的记录 → 撤销
```

## 三、日志记录格式

建议格式（二进制）：

```cpp
struct LogRecord {
    LSN lsn;              // 日志序列号（单调递增）
    LogType type;         // BEGIN/UPDATE/COMMIT/ROLLBACK/CKPT
    txn_id_t txn_id;      // 事务ID
    page_id_t page_id;    // 影响的页面（UPDATE）
    uint32_t payload_len; // 数据长度（old_data + new_data）
    // char old_data[];   // 实际数据跟随其后
    // char new_data[];
};
```

**日志类型**：
- `BEGIN`：事务开始
- `UPDATE`：数据页修改（包含前后镜像）
- `COMMIT`：事务提交
- `ROLLBACK`：事务回滚
- `CKPT`：检查点

## 四、实验任务

### 任务1：实现WAL类框架

```cpp
// src/include/wal.h
class WAL {
public:
    WAL(const std::string& log_path);
    ~WAL();

    // 日志操作
    LSN log_begin(txn_id_t txn_id);
    LSN log_update(txn_id_t txn_id, page_id_t page_id,
                   const std::vector<char>& old_data,
                   const std::vector<char>& new_data);
    LSN log_commit(txn_id_t txn_id);
    LSN log_rollback(txn_id_t txn_id);
    LSN log_checkpoint(const CheckpointInfo& info);

    // 日志管理
    void flush(LSN upto = MAX_LSN);  // 刷盘到指定LSN
    LogRecord read_log(LSN lsn) const;

    // 恢复
    RecoveryResult recover();

    // 统计
    struct Stats {
        uint64_t total_bytes;
        uint64_t num_records;
        LSN last_lsn;
    } get_stats() const;

private:
    std::ofstream log_file_;  // 追加写
    LSN current_lsn_;
    // 缓存：活跃事务、脏页表等
};
```

### 任务2：实现checkpoint

**检查点记录内容**：
```cpp
struct CheckpointInfo {
    std::vector<txn_id_t> active_txns;     // 活跃事务列表
    std::vector<DirtyPage> dirty_pages;    // 脏页列表（page_id, rec_lsn）
    LSN prev_checkpoint_lsn;               // 上一个检查点
};
```

**创建检查点时机**：
- 定时触发（如每5分钟）
- 日志文件大小达到阈值
- 事务提交时主动触发（可选）

### 任务3：实现恢复算法

```cpp
RecoveryResult WAL::recover() {
    // 1. 分析阶段：扫描日志，构建事务表和脏页表
    TransactionTable txn_table;   // txn_id → {status, last_lsn}
    DirtyPageTable dirty_table;   // page_id → rec_lsn

    LSN start_lsn = find_last_checkpoint();
    scan_log_from(start_lsn, txn_table, dirty_table);

    // 2. 重做阶段：对有<commit_lsn的脏页重做
    for (auto& [page_id, rec_lsn] : dirty_table) {
        LSN page_lsn = get_page_lsn(page_id);  // 页头LSN
        if (rec_lsn > page_lsn) {
            redo_page(page_id, rec_lsn);  // 从rec_lsn开始重做
        }
    }

    // 3. 撤销阶段：回滚未提交事务
    for (auto& [txn_id, info] : txn_table) {
        if (info.status == ACTIVE || info.status == PREPARED) {
            undo_transaction(txn_id);
        }
    }

    return { /* 恢复统计 */ };
}
```

### 任务4：集成到StorageEngine

修改`StorageEngine`：
- 写页面前调用WAL记录
- COMMIT时刷WAL
- 重启时自动调用WAL::recover()

### 任务5：测试用例

```python
def test_wal_commit_persistence():
    """测试已提交事务在崩溃后不丢失"""
    engine = StorageEngine()
    engine.create_or_open("test.db")
    wal = engine.get_wal()

    # 模拟事务
    wal.log_begin(txn=1)
    page = engine.allocate_data_page()
    wal.log_update(txn=1, page_id=page, old_data=b'', new_data=b'data')
    wal.log_commit(txn=1)
    wal.flush()

    # 模拟崩溃（不写回数据页）
    engine = None
    wal = None

    # 重启恢复
    engine2 = StorageEngine()
    engine2.create_or_open("test.db")
    engine2.recover()  # 自动调用WAL恢复

    # 验证数据
    recovered_page = engine2.read_page(page)
    assert recovered_page.get_data() == b'data'
```

## 五、挑战与思考

1. 如何确保检查点的一致性？（所有脏页刷盘期间不能有新修改）
2. ARIES恢复算法的三个阶段如何协同？
3. 逻辑日志 vs 物理日志：优缺点？

## 六、评估标准

- [ ] 日志记录格式定义（10分）
- [ ] 日志追加写入和刷盘（15分）
- [ ] checkpoint实现（15分）
- [ ] 恢复算法（ARIES或简版）（30分）
- [ ] 集成测试（崩溃恢复正确性）（20分）
- [ ] 性能测试（日志吞吐量、恢复时间）（10分）

---

**提示**：参考SQLite的`rollback-journal`或`WAL`模式实现。