#include "storage_engine.h"
#include <fstream>
#include <iostream>

namespace db {

StorageEngine::StorageEngine() 
    : file_mgr_(std::make_unique<FileManager>()),
      page_allocator_(std::make_unique<PageAllocator>(file_mgr_.get())) {
}

StorageEngine::~StorageEngine() {
    if (is_open()) {
        try {
            close();
        } catch (...) {
            // 忽略析构时的异常
        }
    }
}

bool StorageEngine::create_or_open(const std::string& db_path) {
    db_path_ = db_path;
    
    try {
        // 打开文件
        if (!file_mgr_->open(db_path)) {
            return false;
        }
        
        // 初始化页分配器
        page_allocator_->initialize();
        
        std::cout << "Database opened: " << db_path 
                  << " (pages: " << file_mgr_->get_file_size() << ")" << std::endl;
        
        return true;
    } catch (const std::exception& e) {
        std::cerr << "Failed to open database: " << e.what() << std::endl;
        return false;
    }
}

void StorageEngine::close() {
    if (!is_open()) return;
    
    try {
        // 刷新缓存
        flush();
        
        // 关闭文件管理器
        file_mgr_->close();
        
        // 重置页分配器
        page_allocator_->reset();
        
        db_path_.clear();
        
        std::cout << "Database closed." << std::endl;
    } catch (const std::exception& e) {
        std::cerr << "Error during close: " << e.what() << std::endl;
        throw;
    }
}

bool StorageEngine::is_open() const {
    return file_mgr_->is_open();
}

std::string StorageEngine::get_db_path() const {
    return db_path_;
}

uint32_t StorageEngine::allocate_data_page() {
    return page_allocator_->allocate(PageType::DATA);
}

uint32_t StorageEngine::allocate_index_page() {
    return page_allocator_->allocate(PageType::INDEX);
}

uint32_t StorageEngine::allocate_metadata_page() {
    return page_allocator_->allocate(PageType::METADATA);
}

void StorageEngine::free_page(uint32_t page_id) {
    page_allocator_->free(page_id);
}

std::unique_ptr<Page> StorageEngine::read_page(uint32_t page_id) {
    return page_allocator_->get_page(page_id);
}

void StorageEngine::write_page(Page* page) {
    if (!page) {
        throw StorageException("Cannot write null page");
    }
    
    page_allocator_->put_page(page);
}

void StorageEngine::flush() {
    file_mgr_->flush();
}

StorageEngine::Stats StorageEngine::get_stats() const {
    Stats stats;
    stats.total_pages = file_mgr_->get_file_size();
    stats.allocated_pages = page_allocator_->get_allocated_count();
    stats.free_pages = page_allocator_->get_free_count();
    stats.file_size_bytes = stats.total_pages * PAGE_SIZE;
    
    return stats;
}

} // namespace db