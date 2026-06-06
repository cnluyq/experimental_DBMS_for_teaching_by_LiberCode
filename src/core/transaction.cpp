#include "transaction.h"
#include "wal.h"
#include <iostream>
#include <algorithm>
#include <sstream>
#include <iomanip>
#include <thread>
#include <chrono>
#include 

namespace db {

// 事务管理器实现

TransactionManager::TransactionManager(WALManager* wal, size_t page_size, bool strict_2pl)
    : wal_manager_(wal), buffer_pool_(nullptr), page_size_(page_size),
      strict_2pl_(strict_2pl), deadlock_detection_enabled_(true),
      next_transaction_id_(1), timestamp_counter_(0) {
    stats_ = {0, 0, 0, 0, 0, 0, 0};
}

TransactionManager::~TransactionManager() {
    shutdown();
}

bool TransactionManager::init() {
    if (!wal_manager_) {
        std::cerr << "WALManager not set" << std::endl;
        return false;
    }
    
    // 恢复：如果有崩溃，WAL会在缓冲区恢复阶段处理
    // 这里我们只需要清理未完成的事务（如果WAL没有自动处理）
    recover_active_transactions();
    
    std::cout << "TransactionManager initialized" << std::endl;
    return true;
}

// 分配事务ID
TransactionID TransactionManager::allocate_transaction_id() {
    return next_transaction_id_++;
}

// 验证事务有效性
TransactionState TransactionManager::validate_transaction(TransactionID tid) const {
    std::lock_guard<std::mutex> lock(txn_mutex_);
    
    auto it = transactions_.find(tid);
    if (it == transactions_.end()) {
        return TransactionState::ABORTED; // 或抛出异常
    }
    
    return it->second->state;
}

// 写入事务日志（封装WAL调用）
bool TransactionManager::write_log(TransactionID tid, LogType type, 
                                   const std::vector<uint8_t>& payload) {
    std::lock_guard<std::mutex> lock(wal_mutex_);
    
    // 获取事务的最后LSN
    LSN prev_lsn = INVALID_LSN;
    auto txn_it = transactions_.find(tid);
    if (txn_it != transactions_.end()) {
        prev_lsn = txn_it->second->last_lsn;
    }
    
    // 调用WAL追加
    LSN lsn = wal_manager_->append(tid, type, payload, prev_lsn);
    if (lsn == INVALID_LSN) {
        return false;
    }
    
    // 更新事务的最后LSN
    if (txn_it != transactions_.end()) {
        txn_it->second->last_lsn = lsn;
    }
    
    return true;
}

// 死锁检测（基于等待图）
bool TransactionManager::build_wait_for_graph(
    std::unordered_map<TransactionID, std::vector<TransactionID>>& graph) {
    std::lock_guard<std::mutex> lock(lock_mutex_);
    
    graph.clear();
    
    // 遍历锁表，构建等待关系
    for (const auto& kv : lock_table_) {
        const auto& resource_id = kv.first;
        const auto& entry = kv.second;
        
        // 如果有排他锁持有者
        if (entry.exclusive_lock_holder != INVALID_TID) {
            TransactionID holder = entry.exclusive_lock_holder;
            // 排他锁持有者的锁被其他事务等待
            for (const auto& req : entry.waiting_queue) {
                graph[req.tid].push_back(holder);
            }
        } else if (!entry.shared_lock_holders.empty()) {
            // 共享锁持有者被排他锁请求者等待
            TransactionID holder = *entry.shared_lock_holders.begin(); // 简化：任选一个
            for (const auto& req : entry.waiting_queue) {
                if (req.mode == LockMode::EXCLUSIVE) {
                    graph[req.tid].push_back(holder);
                }
            }
        }
    }
    
    return !graph.empty();
}

// 检测死锁（寻找环）
TransactionID TransactionManager::detect_deadlock() {
    if (!deadlock_detection_enabled_) {
        return INVALID_TID;
    }
    
    std::unordered_map<TransactionID, std::vector<TransactionID>> wait_for_graph;
    if (!build_wait_for_graph(wait_for_graph)) {
        return INVALID_TID;
    }
    
    // DFS寻找环
    std::unordered_set<TransactionID> visited;
    std::unordered_set<TransactionID> rec_stack;
    
    std::function<bool(TransactionID)> dfs = [&](TransactionID tid) -> bool {
        visited.insert(tid);
        rec_stack.insert(tid);
        
        auto it = wait_for_graph.find(tid);
        if (it != wait_for_graph.end()) {
            for (TransactionID neighbor : it->second) {
                if (rec_stack.count(neighbor)) {
                    // 发现环！返回环中的一个事务
                    return true;
                }
                if (!visited.count(neighbor)) {
                    if (dfs(neighbor)) {
                        return true;
                    }
                }
            }
        }
        
        rec_stack.erase(tid);
        return false;
    };
    
    // 遍历所有事务，寻找环
    for (const auto& [tid, _] : wait_for_graph) {
        visited.clear();
        rec_stack.clear();
        if (dfs(tid)) {
            // 简化：返回当前tid（实际应选择 youngest 或访问最少的作为victim）
            return tid;
        }
    }
    
    return INVALID_TID;
}

// 获取锁（带死锁检测）
bool TransactionManager::acquire_lock_internal(TransactionID tid, 
                                                uint32_t resource_id, 
                                                LockMode mode) {
    // 检查事务状态
    TransactionState state = validate_transaction(tid);
    if (state == TransactionState::ABORTING || state == TransactionState::ABORTED) {
        return false;
    }
    
    LockRequest req{tid, resource_id, mode, timestamp_counter_++};
    
    while (true) {
        std::unique_lock<std::mutex> lock(lock_mutex_);
        
        auto& entry = lock_table_[resource_id];
        
        // 检查是否有冲突
        if (!entry.has_conflict(req)) {
            // 无冲突，立即获取锁
            if (mode == LockMode::SHARED) {
                entry.shared_lock_holders.insert(tid);
            } else {
                entry.exclusive_lock_holder = tid;
            }
            
            // 记录事务持有的锁
            auto txn_it = transactions_.find(tid);
            if (txn_it != transactions_.end()) {
                txn_it->second->locked_resources.insert(resource_id);
            }
            
            stats_.lock_acquired++;
            return true;
        }
        
        // 有冲突，需要等待
        entry.waiting_queue.push_back(req);
        
        // 检查死锁
        TransactionID deadlock_victim = detect_deadlock();
        if (deadlock_victim != INVALID_TID && deadlock_victim == tid) {
            // 当前事务是死锁victim，立即中止
            entry.waiting_queue.pop_back(); // 移除自己的请求
            force_abort(tid, "Deadlock detected");
            
            std::lock_guard<std::mutex> txn_lock(txn_mutex_);
            stats_.deadlocks_detected++;
            return false;
        }
        
        // 等待（简化：释放锁并重试，模拟条件等待）
        lock.unlock();
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
}

// 事务开始
TransactionID TransactionManager::begin(const std::string& description) {
    TransactionID tid = allocate_transaction_id();
    
    std::lock_guard<std::mutex> txn_lock(txn_mutex_);
    
    // 创建事务信息
    auto txn = std::make_shared<TransactionInfo>(tid);
    txn->state = TransactionState::ACTIVE;
    txn->start_time = timestamp_counter_++;
    txn->description = description;
    
    transactions_[tid] = txn;
    
    // 写入BEGIN日志（第一条写作为事务开始标记）
    std::vector<uint8_t> payload;
    write_log(tid, LogType::UPDATE, payload);
    
    stats_.transactions_begun++;
    stats_.current_active_transactions++;
    
    std::cout << "Transaction " << tid << " begun" << std::endl;
    
    return tid;
}

// 事务提交
bool TransactionManager::commit(TransactionID tid) {
    std::shared_ptr<TransactionInfo> txn;
    {
        std::lock_guard<std::mutex> txn_lock(txn_mutex_);
        
        auto it = transactions_.find(tid);
        if (it == transactions_.end()) {
            std::cerr << "Transaction " << tid << " not found" << std::endl;
            return false;
        }
        
        txn = it->second;
        
        if (txn->state != TransactionState::ACTIVE) {
            std::cerr << "Transaction " << tid << " is not active (state=" 
                      << static_cast<int>(txn->state) << ")" << std::endl;
            return false;
        }
        
        // 标记为正在提交
        txn->state = TransactionState::COMMITTING;
        txn->in_commit_process = true;
    }
    
    // 严格2PL：提交前释放所有锁
    if (strict_2pl_) {
        unlock_all(tid);
    }
    
    // 写入COMMIT日志
    if (!write_log(tid, LogType::COMMIT)) {
        std::cerr << "Failed to write COMMIT log for transaction " << tid << std::endl;
        rollback(tid);
        return false;
    }
    
    // 强制持久化
    LSN commit_lsn = INVALID_LSN;
    {
        std::lock_guard<std::mutex> txn_lock(txn_mutex_);
        auto it = transactions_.find(tid);
        if (it != transactions_.end()) {
            commit_lsn = it->second->last_lsn;
        }
    }
    
    if (commit_lsn != INVALID_LSN) {
        std::lock_guard<std::mutex> wal_lock(wal_mutex_);
        wal_manager_->force(commit_lsn);
    }
    
    // 清理事务
    {
        std::lock_guard<std::mutex> txn_lock(txn_mutex_);
        auto it = transactions_.find(tid);
        if (it != transactions_.end()) {
            txn = it->second;
            txn->state = TransactionState::COMMITTED;
            transactions_.erase(it);
        }
        
        stats_.transactions_committed++;
        stats_.current_active_transactions--;
    }
    
    std::cout << "Transaction " << tid << " committed (LSN=" << commit_lsn << ")" << std::endl;
    return true;
}

// 事务回滚
bool TransactionManager::rollback(TransactionID tid) {
    std::shared_ptr<TransactionInfo> txn;
    {
        std::lock_guard<std::mutex> txn_lock(txn_mutex_);
        
        auto it = transactions_.find(tid);
        if (it == transactions_.end()) {
            std::cerr << "Transaction " << tid << " not found for rollback" << std::endl;
            return false;
        }
        
        txn = it->second;
        
        if (txn->state == TransactionState::ABORTING || txn->state == TransactionState::ABORTED) {
            std::cerr << "Transaction " << tid << " is already aborting/aborted" << std::endl;
            return false;
        }
        
        txn->state = TransactionState::ABORTING;
        txn->in_commit_process = true;
    }
    
    // 释放所有锁
    unlock_all(tid);
    
    // 写入ABORT日志
    if (!write_log(tid, LogType::ABORT)) {
        std::cerr << "Failed to write ABORT log for transaction " << tid << std::endl;
    }
    
    // 强制持久化ABORT记录
    LSN abort_lsn = INVALID_LSN;
    {
        std::lock_guard<std::mutex> txn_lock(txn_mutex_);
        auto it = transactions_.find(tid);
        if (it != transactions_.end()) {
            abort_lsn = it->second->last_lsn;
        }
    }
    
    if (abort_lsn != INVALID_LSN) {
        std::lock_guard<std::mutex> wal_lock(wal_mutex_);
        wal_manager_->force(abort_lsn);
    }
    
    // 清理事务
    {
        std::lock_guard<std::mutex> txn_lock(txn_mutex_);
        auto it = transactions_.find(tid);
        if (it != transactions_.end()) {
            txn = it->second;
            txn->state = TransactionState::ABORTED;
            transactions_.erase(it);
        }
        
        stats_.transactions_aborted++;
        stats_.current_active_transactions--;
    }
    
    std::cout << "Transaction " << tid << " rolled back" << std::endl;
    return true;
}

// 获取事务状态
TransactionState TransactionManager::get_transaction_state(TransactionID tid) const {
    std::lock_guard<std::mutex> lock(txn_mutex_);
    
    auto it = transactions_.find(tid);
    if (it == transactions_.end()) {
        return TransactionState::ABORTED;
    }
    
    return it->second->state;
}

// 获取事务信息
std::shared_ptr<TransactionInfo> TransactionManager::get_transaction_info(
    TransactionID tid) const {
    std::lock_guard<std::mutex> lock(txn_mutex_);
    
    auto it = transactions_.find(tid);
    if (it == transactions_.end()) {
        return nullptr;
    }
    
    return it->second;
}

// 检查事务是否活跃
bool TransactionManager::is_transaction_active(TransactionID tid) const {
    TransactionState state = get_transaction_state(tid);
    return state == TransactionState::ACTIVE || state == TransactionState::COMMITTING;
}

// 获取共享锁
bool TransactionManager::lock_shared(TransactionID tid, uint32_t resource_id) {
    return acquire_lock_internal(tid, resource_id, LockMode::SHARED);
}

// 获取排他锁
bool TransactionManager::lock_exclusive(TransactionID tid, uint32_t resource_id) {
    return acquire_lock_internal(tid, resource_id, LockMode::EXCLUSIVE);
}

// 释放锁
bool TransactionManager::unlock(TransactionID tid, uint32_t resource_id) {
    std::lock_guard<std::mutex> lock(lock_mutex_);
    
    auto it = lock_table_.find(resource_id);
    if (it == lock_table_.end()) {
        return false;
    }
    
    auto& entry = it->second;
    
    // 从共享锁集合中移除
    auto shared_it = entry.shared_lock_holders.find(tid);
    if (shared_it != entry.shared_lock_holders.end()) {
        entry.shared_lock_holders.erase(shared_it);
    }
    
    // 如果是排他锁持有者
    if (entry.exclusive_lock_holder == tid) {
        entry.exclusive_lock_holder = INVALID_TID;
    }
    
    // 从事务的锁集合中移除
    {
        std::lock_guard<std::mutex> txn_lock(txn_mutex_);
        auto txn_it = transactions_.find(tid);
        if (txn_it != transactions_.end()) {
            txn_it->second->locked_resources.erase(resource_id);
        }
    }
    
    // 唤醒等待队列中兼容的请求
    if (!entry.waiting_queue.empty()) {
        std::vector<LockRequest> new_waiting_queue;
        
        for (const auto& req : entry.waiting_queue) {
            if (!entry.has_conflict(req)) {
                // 可以授予
                if (req.mode == LockMode::SHARED) {
                    entry.shared_lock_holders.insert(req.tid);
                } else {
                    entry.exclusive_lock_holder = req.tid;
                }
                
                {
                    std::lock_guard<std::mutex> txn_lock(txn_mutex_);
                    auto txn_it = transactions_.find(req.tid);
                    if (txn_it != transactions_.end()) {
                        txn_it->second->locked_resources.insert(resource_id);
                    }
                }
                stats_.lock_acquired++;
            } else {
                new_waiting_queue.push_back(req);
            }
        }
        
        entry.waiting_queue = std::move(new_waiting_queue);
    }
    
    return true;
}

// 释放事务的所有锁
bool TransactionManager::unlock_all(TransactionID tid) {
    std::lock_guard<std::mutex> txn_lock(txn_mutex_);
    
    auto txn_it = transactions_.find(tid);
    if (txn_it == transactions_.end()) {
        return false;
    }
    
    // 复制锁集合（unlock会修改原集合）
    auto locked_resources = txn_it->second->locked_resources;
    
    for (uint32_t resource_id : locked_resources) {
        unlock(tid, resource_id);
    }
    
    return true;
}

// 强制中止事务
bool TransactionManager::force_abort(TransactionID tid, const std::string& reason) {
    std::cout << "Forcing abort of transaction " << tid << " (reason: " << reason << ")" << std::endl;
    unlock_all(tid);
    return rollback(tid);
}

// 获取检查点信息
bool TransactionManager::get_checkpoint_info(CheckpointInfo& info) const {
    std::lock_guard<std::mutex> txn_lock(txn_mutex_);
    std::lock_guard<std::mutex> lock_mtx(lock_mutex_);
    
    info.dirty_page_table.clear();
    info.active_transactions.clear();
    
    // 收集活跃事务
    for (const auto& [tid, txn] : transactions_) {
        if (txn->state == TransactionState::ACTIVE || txn->state == TransactionState::COMMITTING) {
            info.active_transactions.push_back(tid);
        }
    }
    
    // 脏页由BufferPool独立管理
    if (buffer_pool_) {
        // 预留接口：buffer_pool_->get_dirty_pages();
    }
    
    return true;
}

// 恢复活跃事务
bool TransactionManager::recover_active_transactions() {
    std::lock_guard<std::mutex> txn_lock(txn_mutex_);
    
    CheckpointInfo checkpoint = wal_manager_->get_last_checkpoint();
    transactions_.clear();
    
    std::cout << "Recovered " << checkpoint.active_transactions.size() 
              << " active transactions from checkpoint" << std::endl;
    return true;
}

// 获取统计信息
std::string TransactionManager::get_stats() const {
    std::lock_guard<std::mutex> txn_lock(txn_mutex_);
    
    std::stringstream ss;
    ss << "Transaction Manager Statistics:\n";
    ss << "  Transactions begun: " << stats_.transactions_begun << "\n";
    ss << "  Transactions committed: " << stats_.transactions_committed << "\n";
    ss << "  Transactions aborted: " << stats_.transactions_aborted << "\n";
    ss << "  Current active: " << stats_.current_active_transactions << "\n";
    ss << "  Locks acquired: " << stats_.lock_acquired << "\n";
    ss << "  Deadlocks detected: " << stats_.deadlocks_detected << "\n";
    ss << "  Strict 2PL: " << (strict_2pl_ ? "enabled" : "disabled") << "\n";
    ss << "  Deadlock detection: " << (deadlock_detection_enabled_ ? "enabled" : "disabled") << "\n";
    
    return ss.str();
}

// 关闭事务管理器
void TransactionManager::shutdown() {
    std::cout << "Shutting down TransactionManager..." << std::endl;
    
    std::vector<TransactionID> active_txns;
    {
        std::lock_guard<std::mutex> txn_lock(txn_mutex_);
        for (const auto& [tid, txn] : transactions_) {
            if (txn->state == TransactionState::ACTIVE || txn->state == TransactionState::COMMITTING) {
                active_txns.push_back(tid);
            }
        }
    }
    
    // 回滚所有未完成的事务
    for (TransactionID tid : active_txns) {
        std::cout << "Rolling back active transaction " << tid << " during shutdown" << std::endl;
        rollback(tid);
    }
    
    std::cout << get_stats() << std::endl;
    
    {
        std::lock_guard<std::mutex> lock(lock_mutex_);
        lock_table_.clear();
    }
}

} // namespace db
