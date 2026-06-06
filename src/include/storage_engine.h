#ifndef STORAGE_ENGINE_H
#define STORAGE_ENGINE_H

#include <string>
#include <memory>
#include "page.h"
#include "file_manager.h"
#include "page_allocator.h"

namespace db {

// 存储引擎异常
class StorageException : public std::runtime_error {
public:
    explicit StorageException(const std::string& msg) : std::runtime_error(msg) {}
};

// 存储引擎类 - 整合文件管理和页分配，提供高层API
class StorageEngine {
private:
    std::unique_ptr<FileManager> file_mgr_;
    std::unique_ptr<PageAllocator> page_allocator_;
    std::string db_path_;
    
public:
    // 构造函数
    StorageEngine();
    
    // 析构函数
    ~StorageEngine();
    
    // 禁止拷贝
    StorageEngine(const StorageEngine&) = delete;
    StorageEngine& operator=(const StorageEngine&) = delete;
    
    // 创建或打开数据库
    bool create_or_open(const std::string& db_path);
    
    // 关闭数据库
    void close();
    
    // 检查是否已打开
    bool is_open() const;
    
    // 获取数据库路径
    std::string get_db_path() const;
    
    // 分配数据页
    uint32_t allocate_data_page();
    
    // 分配索引页
    uint32_t allocate_index_page();
    
    // 分配元数据页（内部使用）
    uint32_t allocate_metadata_page();
    
    // 释放页
    void free_page(uint32_t page_id);
    
    // 读取页
    std::unique_ptr<Page> read_page(uint32_t page_id);
    
    // 写入页（缓存友好，可批量写回）
    void write_page(Page* page);
    
    // 刷新所有缓存到磁盘
    void flush();
    
    // 获取数据库统计信息
    struct Stats {
        uint32_t total_pages;
        uint32_t allocated_pages;
        uint32_t free_pages;
        size_t file_size_bytes;
    };
    
    Stats get_stats() const;
};

} // namespace db

#endif // STORAGE_ENGINE_H