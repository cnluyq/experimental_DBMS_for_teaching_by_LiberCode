#ifndef TRANSACTION_H
#define TRANSACTION_H

#include <cstdint>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <string>
#include "wal.h"

namespace db {

// 前向声明
class BufferPool;

// 事务状态枚举
enum class TransactionState : uint8_t {
    ACTIVE = 1,       // 活跃（正常执行中）
    COMMITTING = 2,   // 正在提交
    ABORTING = 3,     // 正在中止
    COMMITTED = 4,    // 已提交
    ABORTED = 5       // 已中止
};

// 锁模式
enum class LockMode : uint8_t {
    SHARED = 1,       // 共享锁（读锁）
    EXCLUSIVE = 2     // 排他锁（写锁）
};

// 锁请求（用于死锁检测）
struct LockRequest {
    TransactionID tid;
    uint32_t resource_id;  // 页面ID或行ID
    LockMode mode;
    uint64_t timestamp;    // 请求时间戳（用于死锁打破）
};

// 事务信息
struct TransactionInfo {
    TransactionID tid;
    TransactionState state;
    LSN last_lsn;           // 最后一条日志的LSN
    std::unordered_set<uint32_t> locked_resources;  // 持有的锁集合
    bool in_commit_process; // 是否在提交过程中
    uint64_t start_time;    // 事务开始时间
    std::string description; // 事务描述（可选）
    
    TransactionInfo(TransactionID id) 
        : tid(id), state(TransactionState::ACTIVE), last_lsn(INVALID_LSN),
          in_commit_process(false), start_time(0) {}
};

// 锁表条目
struct LockTableEntry {
    std::unordered_set<TransactionID> shared_lock_holders;   // 共享锁持有者
    TransactionID exclusive_lock_holder;                     // 排他锁持有者（或INVALID_TID）
    std::vector<LockRequest> waiting_queue;                  // 等待队列
    
    LockTableEntry() : exclusive_lock_holder(INVALID_TID) {}
    
    bool is_locked() const {
        return exclusive_lock_holder != INVALID_TID || !shared_lock_holders.empty();
    }
    
    bool has_conflict(const LockRequest& req) const {
        if (req.mode == LockMode::EXCLUSIVE) {
            // 排他锁与任何锁都冲突
            return exclusive_lock_holder != INVALID_TID || !shared_lock_holders.empty();
        } else {
            // 共享锁与排他锁冲突
            return exclusive_lock_holder != INVALID_TID;
        }
    }
};

// 事务管理器
class TransactionManager {
private:
    // 配置
    size_t page_size_;
    bool strict_2pl_;           // 是否使用严格2PL
    bool deadlock_detection_enabled_;  // 是否启用死锁检测
    uint64_t next_transaction_id_;     // 下一个事务ID
    uint64_t timestamp_counter_;       // 时间戳计数器（用于死锁检测）
    
    // WAL管理器
    WALManager* wal_manager_;
    
    // 缓冲区池（用于脏页管理）
    BufferPool* buffer_pool_;
    
    // 事务表：事务ID -> 事务信息
    std::unordered_map<TransactionID, std::shared_ptr<TransactionInfo>> transactions_;
    
    // 锁表：资源ID -> 锁表条目
    std::unordered_map<uint32_t, LockTableEntry> lock_table_;
    
    // 线程同步
    mutable std::mutex txn_mutex_;       // 事务表锁
    mutable std::mutex lock_mutex_;      // 锁表锁
    mutable std::mutex wal_mutex_;       // WAL访问锁
    
    // 内部方法
    TransactionID allocate_transaction_id();
    TransactionState validate_transaction(TransactionID tid) const;
    bool acquire_lock_internal(TransactionID tid, uint32_t resource_id, LockMode mode);
    bool check_deadlock(TransactionID tid, const LockRequest& req);
    void release_all_locks(TransactionID tid);
    bool write_log(TransactionID tid, LogType type, const std::vector<uint8_t>& payload = {});
    
    // 死锁检测（简化：基于等待图）
    bool build_wait_for_graph(std::unordered_map<TransactionID, std::vector<TransactionID>>& graph);
    TransactionID detect_deadlock();
    
    // 统计信息
    struct Stats {
        uint64_t transactions_begun;
        uint64_t transactions_committed;
        uint64_t transactions_aborted;
        uint64_t lock_acquired;
        uint64_t lock_wait_time_total;
        uint64_t deadlocks_detected;
        uint32_t current_active_transactions;
    } stats_;
    
public:
    TransactionManager(WALManager* wal, size_t page_size = 4096, bool strict_2pl = true);
    ~TransactionManager();
    
    // 初始化
    bool init();
    
    // 事务生命周期
    TransactionID begin(const std::string& description = "");
    bool commit(TransactionID tid);
    bool rollback(TransactionID tid);
    
    // 事务状态查询
    TransactionState get_transaction_state(TransactionID tid) const;
    std::shared_ptr<TransactionInfo> get_transaction_info(TransactionID tid) const;
    bool is_transaction_active(TransactionID tid) const;
    
    // 锁操作
    bool lock_shared(TransactionID tid, uint32_t resource_id);
    bool lock_exclusive(TransactionID tid, uint32_t resource_id);
    bool unlock(TransactionID tid, uint32_t resource_id);
    bool unlock_all(TransactionID tid);
    
    // 隔离级别设置
    void set_strict_2pl(bool enable) { strict_2pl_ = enable; }
    bool is_strict_2pl() const { return strict_2pl_; }
    
    // 死锁检测
    void set_deadlock_detection(bool enable) { deadlock_detection_enabled_ = enable; }
    bool is_deadlock_detection_enabled() const { return deadlock_detection_enabled_; }
    
    // 强制事务中止（用于死锁解决）
    bool force_abort(TransactionID tid, const std::string& reason);
    
    // 检查点（收集脏页和活跃事务信息）
    bool get_checkpoint_info(CheckpointInfo& info) const;
    
    // 恢复支持
    bool recover_active_transactions();
    
    // 统计
    std::string get_stats() const;
    
    // 关闭
    void shutdown();
};

} // namespace db

#endif // TRANSACTION_H