#include "page_allocator.h"
#include <algorithm>
#include <stdexcept>

namespace db {

PageAllocator::PageAllocator(FileManager* file_mgr) 
    : file_mgr_(file_mgr), initialized_(false) {
    if (!file_mgr_) {
        throw std::invalid_argument("FileManager cannot be null");
    }
}

PageAllocator::~PageAllocator() = default;

void PageAllocator::initialize() {
    if (initialized_) return;
    
    if (!file_mgr_->is_open()) {
        throw std::runtime_error("FileManager not open");
    }
    
    // 从文件管理器加载空闲页信息
    load_free_pages();
    
    // 加载所有已分配的页（除了空闲页和文件头页）
    uint32_t total_pages = file_mgr_->get_file_size();
    for (uint32_t i = 1; i < total_pages; i++) {
        // 检查该页是否在空闲列表中
        if (std::find(free_list_.begin(), free_list_.end(), i) == free_list_.end()) {
            // 假设非空闲页都已分配（简化逻辑）
            // 实际中可能需要读取页类型来确认
            allocated_pages_.insert(i);
        }
    }
    
    initialized_ = true;
}

uint32_t PageAllocator::allocate(PageType type) {
    if (!initialized_) {
        throw std::runtime_error("PageAllocator not initialized");
    }
    
    FileManager* fm = file_mgr_;
    
    // 优先从空闲列表分配
    if (!free_list_.empty()) {
        uint32_t page_id = free_list_.back();
        free_list_.pop_back();
        
        // 确保该页在已分配集合中
        allocated_pages_.insert(page_id);
        
        // 更新页类型（通过读取页、修改、写回）
        auto page = fm->read_page(page_id);
        page->set_type(type);
        fm->write_page(page.get());
        
        return page_id;
    }
    
    // 没有空闲页，让文件管理器分配新页
    uint32_t page_id = fm->allocate_page(type);
    allocated_pages_.insert(page_id);
    
    return page_id;
}

void PageAllocator::free(uint32_t page_id) {
    if (!initialized_) {
        throw std::runtime_error("PageAllocator not initialized");
    }
    
    if (page_id == 0) {
        throw std::invalid_argument("Cannot free page 0 (file header)");
    }
    
    // 检查页是否已分配
    auto it = allocated_pages_.find(page_id);
    if (it == allocated_pages_.end()) {
        throw std::runtime_error("Page " + std::to_string(page_id) + " is not allocated");
    }
    
    // 从已分配集合移除
    allocated_pages_.erase(it);
    
    // 加入空闲列表
    free_list_.push_back(page_id);
    
    // 通知文件管理器释放页（更新空闲链表）
    file_mgr_->free_page(page_id);
}

std::unique_ptr<Page> PageAllocator::get_page(uint32_t page_id) {
    // 通过文件管理器读取页
    auto page = file_mgr_->read_page(page_id);
    
    // 确保页类型有效（非空闲页）
    if (page->get_type() == PageType::FREE) {
        throw std::runtime_error("Attempting to read free page " + std::to_string(page_id));
    }
    
    return page;
}

void PageAllocator::put_page(Page* page) {
    if (!page) return;
    
    file_mgr_->write_page(page);
}

bool PageAllocator::is_allocated(uint32_t page_id) const {
    return allocated_pages_.find(page_id) != allocated_pages_.end();
}

size_t PageAllocator::get_allocated_count() const {
    return allocated_pages_.size();
}

size_t PageAllocator::get_free_count() const {
    return free_list_.size();
}

void PageAllocator::load_free_pages() {
    free_list_ = file_mgr_->get_free_pages();
    
    // 翻转列表，使得最后加入的（链表头部）先被分配（LIFO策略）
    std::reverse(free_list_.begin(), free_list_.end());
}

void PageAllocator::reset() {
    free_list_.clear();
    allocated_pages_.clear();
    initialized_ = false;
    
    // 重新加载
    load_free_pages();
    
    // 重新计算已分配页
    uint32_t total_pages = file_mgr_->get_file_size();
    for (uint32_t i = 1; i < total_pages; i++) {
        if (std::find(free_list_.begin(), free_list_.end(), i) == free_list_.end()) {
            allocated_pages_.insert(i);
        }
    }
    
    initialized_ = true;
}

} // namespace db