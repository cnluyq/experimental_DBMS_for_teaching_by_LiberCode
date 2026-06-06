#ifndef PAGE_ALLOCATOR_H
#define PAGE_ALLOCATOR_H

#include <vector>
#include <unordered_set>
#include "page.h"
#include "file_manager.h"

namespace db {

// 页分配器 - 管理空闲页的分配和回收
class PageAllocator {
private:
    FileManager* file_mgr_;  // 文件管理器
    std::vector<uint32_t> free_list_;  // 空闲页列表
    std::unordered_set<uint32_t> allocated_pages_;  // 已分配页集合
    bool initialized_;       // 是否已初始化
    
    // 从文件管理器加载空闲页信息
    void load_free_pages();
    
public:
    explicit PageAllocator(FileManager* file_mgr);
    ~PageAllocator();
    
    // 初始化
    void initialize();
    
    // 分配页
    uint32_t allocate(PageType type = PageType::DATA);
    
    // 释放页
    void free(uint32_t page_id);
    
    // 获取页（从文件管理器读取）
    std::unique_ptr<Page> get_page(uint32_t page_id);
    
    // 写回页到文件管理器
    void put_page(Page* page);
    
    // 检查页是否已分配
    bool is_allocated(uint32_t page_id) const;
    
    // 获取已分配页数量
    size_t get_allocated_count() const;
    
    // 获取空闲页数量
    size_t get_free_count() const;
    
    // 重置分配器（清空所有分配记录，用于重启）
    void reset();
};

} // namespace db

#endif // PAGE_ALLOCATOR_H