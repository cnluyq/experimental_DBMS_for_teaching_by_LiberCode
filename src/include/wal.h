#ifndef WAL_H
#define WAL_H

#include <cstdint>
#include <vector>
#include <string>
#include <fstream>
#include <unordered_map>
#include "page.h"

namespace db {

// 前向声明
class BufferPool;

// 日志序列号（LSN）
using LSN = uint64_t;
constexpr LSN INVALID_LSN = 0;

// 事务ID
using TransactionID = uint32_t;
constexpr TransactionID INVALID_TID = 0;

// 日志类型
enum class LogType : uint8_t {
    UPDATE = 1,     // 更新操作
    INSERT = 2,     // 插入操作
    DELETE = 3,     // 删除操作
    COMMIT = 4,     // 事务提交
    ABORT = 5,      // 事务中止
    CHECKPOINT = 6  // 检查点
};

// 日志记录通用头（固定长度部分）
struct LogRecordHeader {
    LSN lsn;              // 日志序列号
    TransactionID tid;    // 事务ID
    LogType type;         // 日志类型
    uint32_t size;        // 数据部分大小
    LSN prev_lsn;         // 同一事务的上一条日志（0表示第一条）
    
    // 计算记录总大小（头+数据）
    uint32_t total_size() const { return sizeof(LogRecordHeader) + size; }
};

// Update日志的数据部分
struct UpdateLogData {
    uint32_t page_id;     // 被修改的页面ID
    uint32_t offset;      // 数据偏移
    uint16_t length;      // 数据长度
    // 后面跟着：旧值（length字节）+ 新值（length字节）
};

// Insert/Delete日志的数据部分
struct ModifyLogData {
    uint32_t page_id;     // 页面ID
    uint32_t offset;      // 插入/删除位置
    uint16_t length;      // 数据长度
    // 后面跟着：数据内容（length字节）
};

// 检查点记录的数据部分
struct CheckpointData {
    uint32_t dirty_page_count; // 脏页数量
    // 脏页表：每个条目 {page_id, rec_lsn}
    // 然后是活跃事务列表
    // 最后是WAL文件尾位置（用于恢复起点）
};

// 日志记录（完整）
struct LogRecord {
    LogRecordHeader header;
    std::vector<uint8_t> data;
    
    LogRecord() = default;
    
    LogRecord(LogType type, TransactionID tid, const std::vector<uint8_t>& payload,
              LSN prev_lsn = INVALID_LSN)
        : header{INVALID_LSN, tid, type, static_cast<uint32_t>(payload.size()), prev_lsn}
        , data(payload) {}
    
    // 序列化到缓冲区
    void serialize(std::vector<uint8_t>& buffer) const;
    
    // 从缓冲区反序列化
    static bool deserialize(const uint8_t* buf, size_t buf_size, LogRecord& record);
};

// 检查点信息
struct CheckpointInfo {
    LSN checkpoint_lsn;  // 检查点记录的LSN
    std::unordered_map<uint32_t, LSN> dirty_page_table;  // {page_id -> rec_lsn}
    std::vector<TransactionID> active_transactions;     // 活跃事务列表
    uint64_t wal_offset;  // WAL文件尾位置（字节偏移）
};

// WAL管理器
class WALManager {
private:
    std::string wal_dir_;           // WAL文件目录
    std::string wal_filename_;      // 当前WAL文件名
    std::ofstream wal_file_;        // WAL文件流
    LSN next_lsn_;                  // 下一个可用的LSN
    LSN last_checkpoint_lsn_;       // 最近一次检查点的LSN
    size_t page_size_;              // 日志页大小（通常与数据页一致）
    
    // 运行时状态（用于恢复）
    CheckpointInfo last_checkpoint_;
    std::unordered_map<TransactionID, LSN> active_txns_;  // 活跃事务及其最后一条日志LSN
    
    // 内部方法
    bool ensure_wal_open();
    void close_wal();
    LSN allocate_lsn();
    bool write_record_to_file(const LogRecord& record);
    bool fsync_file();
    
    // 检查点相关
    bool create_checkpoint_record(const CheckpointInfo& info, LogRecord& record);
    bool save_checkpoint_metadata(const CheckpointInfo& info);
    
    // 恢复相关
    bool analyze_wal_file(CheckpointInfo& checkpoint, 
                          std::vector<LogRecord>& active_logs);
    bool redo_logs_from(const CheckpointInfo& checkpoint);
    bool undo_active_transactions(const std::vector<LogRecord>& active_logs);
    
public:
    WALManager(const std::string& wal_dir, size_t page_size = 4096);
    ~WALManager();
    
    // 初始化WAL系统
    bool init();
    
    // 追加日志记录（Write-Ahead核心）
    LSN append(TransactionID tid, LogType type, 
               const std::vector<uint8_t>& payload, LSN prev_lsn = INVALID_LSN);
    
    // 强制持久化（fsync）
    bool force(LSN upto_lsn = INVALID_LSN);
    
    // 事务相关
    LSN get_last_lsn(TransactionID tid) const;
    void start_transaction(TransactionID tid);
    void commit_transaction(TransactionID tid);
    void abort_transaction(TransactionID tid);
    
    // 检查点
    bool checkpoint(const CheckpointInfo& info);
    CheckpointInfo get_last_checkpoint() const { return last_checkpoint_; }
    
    // 脏页表管理（由BufferPool调用）
    void register_dirty_page(uint32_t page_id, LSN rec_lsn);
    void unregister_dirty_page(uint32_t page_id);
    
    // 崩溃恢复
    enum class RecoveryResult { SUCCESS, NO_WAL, ERROR };
    RecoveryResult recover(BufferPool* buffer_pool = nullptr);
    
    // 关闭WAL
    void shutdown();
    
    // 获取统计信息
    uint64_t get_next_lsn() const { return next_lsn_; }
    uint64_t get_last_checkpoint_lsn() const { return last_checkpoint_lsn_; }
};

} // namespace db

#endif // WAL_H