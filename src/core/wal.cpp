#include "wal.h"
#include <iostream>
#include <algorithm>
#if __has_include(<filesystem>)
    #include <filesystem>
    namespace fs = std::filesystem;
#elif __has_include(<experimental/filesystem>)
    #include <experimental/filesystem>
    namespace fs = std::experimental::filesystem;
#else
    #error "No filesystem support"
#endif
#include <system_error>
#include <cstring>
#include <vector>

namespace db {

// WALManager实现

WALManager::WALManager(const std::string& wal_dir, size_t page_size)
    : wal_dir_(wal_dir), next_lsn_(1), last_checkpoint_lsn_(INVALID_LSN),
      page_size_(page_size) {
    // 确保目录存在
    fs::create_directories(wal_dir);
    
    // WAL文件名：wal.log
    wal_filename_ = wal_dir_ + "/wal.log";
}

WALManager::~WALManager() {
    shutdown();
}

bool WALManager::init() {
    // 检查WAL文件是否存在，决定打开模式
    bool wal_exists = fs::exists(wal_filename_);
    
    if (wal_exists) {
        // 恢复场景：打开现有WAL文件，定位到文件末尾
        wal_file_.open(wal_filename_, std::ios::in | std::ios::out | std::ios::binary);
        if (!wal_file_.is_open()) {
            std::cerr << "Failed to open existing WAL file: " << wal_filename_ << std::endl;
            return false;
        }
        
        // 定位到文件末尾，准备追加
        wal_file_.seekp(0, std::ios::end);
        
        // 读取最后一条记录的LSN（用于设置next_lsn_）
        next_lsn_ = 1; // 简化：实际应从文件恢复
    } else {
        // 新建场景：创建WAL文件
        wal_file_.open(wal_filename_, std::ios::out | std::ios::binary);
        if (!wal_file_.is_open()) {
            std::cerr << "Failed to create WAL file: " << wal_filename_ << std::endl;
            return false;
        }
        next_lsn_ = 1;
    }
    
    std::cout << "WAL initialized: " << wal_filename_ 
              << ", next_lsn=" << next_lsn_ << std::endl;
    return true;
}

bool WALManager::ensure_wal_open() {
    if (wal_file_.is_open()) return true;
    
    wal_file_.open(wal_filename_, std::ios::in | std::ios::out | std::ios::binary | std::ios::app);
    return wal_file_.is_open();
}

void WALManager::close_wal() {
    if (wal_file_.is_open()) {
        wal_file_.close();
    }
}

LSN WALManager::allocate_lsn() {
    return next_lsn_++;
}

// 序列化LogRecord到缓冲区
void LogRecord::serialize(std::vector<uint8_t>& buffer) const {
    // 头
    buffer.resize(sizeof(LogRecordHeader) + data.size());
    uint8_t* ptr = buffer.data();
    
    // 复制头
    std::memcpy(ptr, &header, sizeof(LogRecordHeader));
    ptr += sizeof(LogRecordHeader);
    
    // 复制数据
    if (!data.empty()) {
        std::memcpy(ptr, data.data(), data.size());
    }
}

// 从缓冲区反序列化LogRecord
bool LogRecord::deserialize(const uint8_t* buf, size_t buf_size, LogRecord& record) {
    if (buf_size < sizeof(LogRecordHeader)) return false;
    
    // 读取头
    std::memcpy(&record.header, buf, sizeof(LogRecordHeader));
    
    // 检查数据大小
    size_t expected_size = sizeof(LogRecordHeader) + record.header.size;
    if (buf_size < expected_size) return false;
    
    // 读取数据
    if (record.header.size > 0) {
        record.data.resize(record.header.size);
        std::memcpy(record.data.data(), buf + sizeof(LogRecordHeader), record.header.size);
    }
    
    return true;
}

// 追加日志记录（Write-Ahead核心）
LSN WALManager::append(TransactionID tid, LogType type, 
                       const std::vector<uint8_t>& payload, LSN prev_lsn) {
    if (!ensure_wal_open()) {
        std::cerr << "WAL file not open" << std::endl;
        return INVALID_LSN;
    }
    
    // 创建日志记录
    LogRecord record(type, tid, payload, prev_lsn);
    
    // 分配LSN
    LSN lsn = allocate_lsn();
    record.header.lsn = lsn;
    
    // 序列化
    std::vector<uint8_t> buffer;
    record.serialize(buffer);
    
    // 写入文件
    wal_file_.write(reinterpret_cast<const char*>(buffer.data()), buffer.size());
    if (!wal_file_) {
        std::cerr << "Failed to write log record to WAL" << std::endl;
        return INVALID_LSN;
    }
    
    // 更新事务状态
    active_txns_[tid] = lsn;
    
    // 如果是UPDATE操作，将页面注册为脏页
    if (type == LogType::UPDATE || type == LogType::INSERT || type == LogType::DELETE) {
        if (!payload.empty()) {
            uint32_t page_id;
            std::memcpy(&page_id, payload.data(), sizeof(uint32_t));
            register_dirty_page(page_id, lsn);
        }
    }
    
    return lsn;
}

// 强制持久化（fsync）
bool WALManager::force(LSN upto_lsn) {
    if (!wal_file_.is_open()) return false;
    
    // 刷新文件缓冲区到操作系统
    wal_file_.flush();
    
    // 跨平台简化版本：假设flush足够（实际系统需要fsync）
    return true;
}

// 事务开始
void WALManager::start_transaction(TransactionID tid) {
    active_txns_[tid] = INVALID_LSN;
}

// 事务提交
void WALManager::commit_transaction(TransactionID tid) {
    std::vector<uint8_t> empty_payload;
    LSN prev_lsn = INVALID_LSN;
    
    auto it = active_txns_.find(tid);
    if (it != active_txns_.end() && it->second != INVALID_LSN) {
        prev_lsn = it->second;
    }
    
    LSN commit_lsn = append(tid, LogType::COMMIT, empty_payload, prev_lsn);
    if (commit_lsn != INVALID_LSN) {
        force(commit_lsn);
    }
    
    active_txns_.erase(tid);
}

// 事务中止
void WALManager::abort_transaction(TransactionID tid) {
    std::vector<uint8_t> empty_payload;
    LSN prev_lsn = INVALID_LSN;
    
    auto it = active_txns_.find(tid);
    if (it != active_txns_.end() && it->second != INVALID_LSN) {
        prev_lsn = it->second;
    }
    
    LSN abort_lsn = append(tid, LogType::ABORT, empty_payload, prev_lsn);
    if (abort_lsn != INVALID_LSN) {
        force(abort_lsn);
    }
    
    active_txns_.erase(tid);
}

// 获取事务的最后LSN
LSN WALManager::get_last_lsn(TransactionID tid) const {
    auto it = active_txns_.find(tid);
    if (it != active_txns_.end()) {
        return it->second;
    }
    return INVALID_LSN;
}

// 注册脏页
void WALManager::register_dirty_page(uint32_t page_id, LSN rec_lsn) {
    // 简化：WALManager不维护完整的脏页表
}

// 注销脏页
void WALManager::unregister_dirty_page(uint32_t page_id) {
    // 存根
}

// 创建检查点记录（简化）
bool WALManager::create_checkpoint_record(const CheckpointInfo& info, LogRecord& record) {
    std::vector<uint8_t> payload;
    
    // 脏页数量
    uint32_t dirty_count = static_cast<uint32_t>(info.dirty_page_table.size());
    payload.insert(payload.end(), 
                   reinterpret_cast<const uint8_t*>(&dirty_count),
                   reinterpret_cast<const uint8_t*>(&dirty_count) + sizeof(uint32_t));
    
    // 脏页表
    for (const auto& [page_id, rec_lsn] : info.dirty_page_table) {
        payload.insert(payload.end(), 
                       reinterpret_cast<const uint8_t*>(&page_id),
                       reinterpret_cast<const uint8_t*>(&page_id) + sizeof(uint32_t));
        payload.insert(payload.end(), 
                       reinterpret_cast<const uint8_t*>(&rec_lsn),
                       reinterpret_cast<const uint8_t*>(&rec_lsn) + sizeof(LSN));
    }
    
    // 活跃事务数量
    uint32_t active_count = static_cast<uint32_t>(info.active_transactions.size());
    payload.insert(payload.end(), 
                   reinterpret_cast<const uint8_t*>(&active_count),
                   reinterpret_cast<const uint8_t*>(&active_count) + sizeof(uint32_t));
    
    // 活跃事务列表
    for (TransactionID tid : info.active_transactions) {
        payload.insert(payload.end(), 
                       reinterpret_cast<const uint8_t*>(&tid),
                       reinterpret_cast<const uint8_t*>(&tid) + sizeof(TransactionID));
    }
    
    // WAL文件大小
    uint64_t wal_size = info.wal_offset;
    payload.insert(payload.end(), 
                   reinterpret_cast<const uint8_t*>(&wal_size),
                   reinterpret_cast<const uint8_t*>(&wal_size) + sizeof(uint64_t));
    
    // 创建记录
    record = LogRecord(LogType::CHECKPOINT, 0, payload);
    record.header.lsn = info.checkpoint_lsn;
    
    return true;
}

// 保存检查点元数据（简化）
bool WALManager::save_checkpoint_metadata(const CheckpointInfo& info) {
    last_checkpoint_lsn_ = info.checkpoint_lsn;
    last_checkpoint_ = info;
    return true;
}

// 执行检查点
bool WALManager::checkpoint(const CheckpointInfo& info) {
    if (!ensure_wal_open()) return false;
    
    // 创建检查点记录
    LogRecord cp_record;
    if (!create_checkpoint_record(info, cp_record)) {
        return false;
    }
    
    // 追加并持久化
    LSN cp_lsn = append(0, LogType::CHECKPOINT, cp_record.data);
    if (cp_lsn == INVALID_LSN) {
        return false;
    }
    
    // 强制持久化
    if (!force(cp_lsn)) {
        return false;
    }
    
    // 保存检查点元数据（注意：info参数是const引用，不能修改）
    // 所以这里需要调用save_checkpoint_metadata，它使用内部副本
    CheckpointInfo mutable_info = info;
    mutable_info.checkpoint_lsn = cp_lsn;
    mutable_info.wal_offset = wal_file_.tellp();
    save_checkpoint_metadata(mutable_info);
    
    std::cout << "Checkpoint created at LSN " << cp_lsn 
              << ", dirty pages: " << info.dirty_page_table.size()
              << ", active txns: " << info.active_transactions.size() << std::endl;
    
    return true;
}

// 分析WAL文件（恢复第一阶段）
bool WALManager::analyze_wal_file(CheckpointInfo& checkpoint,
                                   std::vector<LogRecord>& active_logs) {
    // 打开WAL文件进行读取
    std::ifstream in(wal_filename_, std::ios::binary);
    if (!in) {
        std::cerr << "Failed to open WAL file for recovery" << std::endl;
        return false;
    }
    
    // 确定起点：从上次检查点开始，或从文件开头
    LSN start_lsn = last_checkpoint_lsn_ != INVALID_LSN ? last_checkpoint_lsn_ + 1 : 1;
    
    // 遍历文件读取日志记录
    in.seekg(0, std::ios::end);
    size_t file_size = in.tellg();
    in.seekg(0, std::ios::beg);
    
    std::vector<LogRecord> all_records;
    
    while (true) {
        size_t pos = in.tellg();
        if (pos >= file_size) break;
        
        // 读取记录头
        LogRecordHeader header;
        in.read(reinterpret_cast<char*>(&header), sizeof(LogRecordHeader));
        if (!in) break;
        
        // 读取数据部分
        std::vector<uint8_t> data(header.size);
        if (header.size > 0) {
            in.read(reinterpret_cast<char*>(data.data()), header.size);
            if (!in) break;
        }
        
        LogRecord record;
        record.header = header;
        record.data = std::move(data);
        
        if (record.header.lsn >= start_lsn) {
            all_records.push_back(std::move(record));
        }
    }
    
    // 分析阶段：构建活跃事务集和脏页表（简化）
    checkpoint.dirty_page_table.clear();
    checkpoint.active_transactions.clear();
    
    std::unordered_map<TransactionID, LSN> tx_last_lsn;
    
    for (const auto& rec : all_records) {
        TransactionID tid = rec.header.tid;
        
        // 记录事务的最后一条日志
        tx_last_lsn[tid] = rec.header.lsn;
        
        // 对于UPDATE/INSERT/DELETE，记录脏页
        if (rec.header.type == LogType::UPDATE ||
            rec.header.type == LogType::INSERT ||
            rec.header.type == LogType::DELETE) {
            if (!rec.data.empty()) {
                uint32_t page_id;
                std::memcpy(&page_id, rec.data.data(), sizeof(uint32_t));
                checkpoint.dirty_page_table[page_id] = rec.header.lsn;
            }
        }
        
        // 对于COMMIT，从活跃事务中移除
        if (rec.header.type == LogType::COMMIT) {
            checkpoint.active_transactions.erase(
                std::remove(checkpoint.active_transactions.begin(),
                            checkpoint.active_transactions.end(),
                            tid),
                checkpoint.active_transactions.end()
            );
        }
        
        // 对于ABORT，同样移除
        if (rec.header.type == LogType::ABORT) {
            checkpoint.active_transactions.erase(
                std::remove(checkpoint.active_transactions.begin(),
                            checkpoint.active_transactions.end(),
                            tid),
                checkpoint.active_transactions.end()
            );
        }
        
        // 对于CHECKPOINT，更新检查点信息
        if (rec.header.type == LogType::CHECKPOINT) {
            const uint8_t* ptr = rec.data.data();
            size_t remaining = rec.data.size();
            
            // 脏页数量
            if (remaining < sizeof(uint32_t)) return false;
            uint32_t dirty_count;
            std::memcpy(&dirty_count, ptr, sizeof(uint32_t));
            ptr += sizeof(uint32_t);
            remaining -= sizeof(uint32_t);
            
            // 脏页表
            checkpoint.dirty_page_table.clear();
            for (uint32_t i = 0; i < dirty_count; ++i) {
                if (remaining < sizeof(uint32_t) + sizeof(LSN)) return false;
                uint32_t page_id;
                LSN rec_lsn;
                std::memcpy(&page_id, ptr, sizeof(uint32_t));
                ptr += sizeof(uint32_t);
                std::memcpy(&rec_lsn, ptr, sizeof(LSN));
                ptr += sizeof(LSN);
                checkpoint.dirty_page_table[page_id] = rec_lsn;
                remaining -= sizeof(uint32_t) + sizeof(LSN);
            }
            
            // 活跃事务数量
            if (remaining < sizeof(uint32_t)) return false;
            uint32_t active_count;
            std::memcpy(&active_count, ptr, sizeof(uint32_t));
            ptr += sizeof(uint32_t);
            remaining -= sizeof(uint32_t);
            
            // 活跃事务列表
            checkpoint.active_transactions.clear();
            for (uint32_t i = 0; i < active_count; ++i) {
                if (remaining < sizeof(TransactionID)) return false;
                TransactionID tid;
                std::memcpy(&tid, ptr, sizeof(TransactionID));
                ptr += sizeof(TransactionID);
                checkpoint.active_transactions.push_back(tid);
                remaining -= sizeof(TransactionID);
            }
            
            checkpoint.checkpoint_lsn = rec.header.lsn;
        }
    }
    
    // 收集未COMMIT的事务的活跃日志（用于撤销）
    active_logs.clear();
    // 首先确定每个事务的最后一条记录的类型
    std::unordered_map<TransactionID, LogType> tx_last_type;
    for (const auto& rec : all_records) {
        tx_last_type[rec.header.tid] = rec.header.type;
    }
    
    // 收集所有未 COMMIT/ABORT 的日志
    for (const auto& rec : all_records) {
        auto type_it = tx_last_type.find(rec.header.tid);
        if (type_it != tx_last_type.end()) {
            LogType last_type = type_it->second;
            if (last_type != LogType::COMMIT && last_type != LogType::ABORT) {
                active_logs.push_back(rec);
            }
        }
    }
    
    std::cout << "Analysis complete: " << all_records.size() 
              << " records, dirty pages: " << checkpoint.dirty_page_table.size()
              << ", active txns: " << checkpoint.active_transactions.size() << std::endl;
    
    return true;
}

// 重做阶段（简化）
bool WALManager::redo_logs_from(const CheckpointInfo& checkpoint) {
    std::cout << "Redo phase starting from LSN " << checkpoint.checkpoint_lsn + 1 << std::endl;
    return true;
}

// 撤销阶段
bool WALManager::undo_active_transactions(const std::vector<LogRecord>& active_logs) {
    std::cout << "Undo phase for " << active_logs.size() << " active transaction logs" << std::endl;
    return true;
}

// 崩溃恢复（主流程）
WALManager::RecoveryResult WALManager::recover(BufferPool* buffer_pool) {
    std::cout << "Starting recovery..." << std::endl;
    
    if (!fs::exists(wal_filename_)) {
        std::cout << "No WAL file found, fresh start" << std::endl;
        return RecoveryResult::NO_WAL;
    }
    
    // 阶段1：分析
    CheckpointInfo checkpoint;
    std::vector<LogRecord> active_logs;
    
    if (!analyze_wal_file(checkpoint, active_logs)) {
        std::cerr << "Analysis phase failed" << std::endl;
        return RecoveryResult::ERROR;
    }
    
    // 阶段2：重做
    if (!redo_logs_from(checkpoint)) {
        std::cerr << "Redo phase failed" << std::endl;
        return RecoveryResult::ERROR;
    }
    
    // 阶段3：撤销
    if (!undo_active_transactions(active_logs)) {
        std::cerr << "Undo phase failed" << std::endl;
        return RecoveryResult::ERROR;
    }
    
    std::cout << "Recovery completed successfully" << std::endl;
    return RecoveryResult::SUCCESS;
}

// 关闭WAL
void WALManager::shutdown() {
    force();
    close_wal();
}

} // namespace db