#ifndef FILE_MANAGER_H
#define FILE_MANAGER_H

#include <string>
#include <vector>
#include <memory>
#include <cstdint>
#include "page.h"

namespace db {

constexpr uint32_t DB_MAGIC = 0x4442544D; // "DBTM"

// 文件头结构（位于文件第一页的开头）
struct FileHeader {
    uint32_t magic;           // 魔数，标识文件类型
    uint32_t version;         // 文件版本
    uint32_t page_size;       // 页大小
    uint32_t total_pages;     // 总页数
    uint32_t free_page_count; // 空闲页数量
    uint32_t first_free_page; // 第一个空闲页ID（空闲链表头）
    uint8_t  reserved[40];    // 保留字段
    
    FileHeader() : magic(DB_MAGIC), version(1), page_size(PAGE_SIZE),
                   total_pages(0), free_page_count(0), first_free_page(0) {
        memset(reserved, 0, sizeof(reserved));
    }
};

// 文件管理异常
class FileException : public std::runtime_error {
public:
    explicit FileException(const std::string& msg) : std::runtime_error(msg) {}
};

// 文件管理类 - 负责文件的创建、打开、关闭和页级操作
class FileManager {
private:
    // 文件信息内部结构
    struct FileInfo {
        int fd;                    // 文件描述符
        std::string filename;      // 文件名
        uint8_t* file_start;       // 文件映射起始地址
        size_t file_size;          // 文件大小（字节）
        FileHeader* file_header;   // 文件头指针
        
        FileInfo() : fd(-1), file_start(nullptr), file_size(0), file_header(nullptr) {}
    };
    
    std::unique_ptr<FileInfo> file_info_;
    
    // 禁止拷贝
    FileManager(const FileManager&) = delete;
    FileManager& operator=(const FileManager&) = delete;
    
public:
    FileManager();
    ~FileManager();
    
    // 打开或创建数据库文件
    bool open(const std::string& filename);
    
    // 关闭文件
    void close();
    
    // 检查文件是否打开
    bool is_open() const;
    
    // 获取文件名
    std::string get_filename() const;
    
    // 获取文件大小（页数）
    uint32_t get_file_size() const;
    
    // 分配新页
    uint32_t allocate_page(PageType type = PageType::DATA);
    
    // 释放页
    void free_page(uint32_t page_id);
    
    // 读取页到内存
    std::unique_ptr<Page> read_page(uint32_t page_id);
    
    // 写入页到文件
    void write_page(Page* page);
    
    // 刷新文件缓冲区
    void flush();
    
    // 获取空闲页列表（用于恢复）
    std::vector<uint32_t> get_free_pages() const;
};

} // namespace db

#endif // FILE_MANAGER_H