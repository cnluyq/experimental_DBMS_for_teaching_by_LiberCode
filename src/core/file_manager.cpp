#include "file_manager.h"
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <cstring>
#include <stdexcept>
#include <iostream>

namespace db {

FileManager::FileManager() : file_info_(std::make_unique<FileInfo>()) {}

FileManager::~FileManager() {
    close();
}

bool FileManager::open(const std::string& filename) {
    if (file_info_->fd != -1) {
        close(); // 先关闭已有文件
    }
    
    file_info_->filename = filename;
    
    // 尝试打开已存在的文件
    file_info_->fd = ::open(filename.c_str(), O_RDWR);
    bool create_new = false;
    
    if (file_info_->fd == -1) {
        // 文件不存在，创建新文件
        file_info_->fd = ::open(filename.c_str(), O_RDWR | O_CREAT, 0644);
        if (file_info_->fd == -1) {
            throw FileException("Failed to create file: " + filename);
        }
        create_new = true;
    }
    
    // 获取文件大小
    struct stat st;
    if (::fstat(file_info_->fd, &st) == -1) {
        ::close(file_info_->fd);
        file_info_->fd = -1;
        throw FileException("Failed to get file size");
    }
    
    file_info_->file_size = st.st_size;
    
    if (create_new) {
        // 初始化新文件
        // 至少分配1页（文件头）
        file_info_->file_size = PAGE_SIZE;
        if (::ftruncate(file_info_->fd, file_info_->file_size) == -1) {
            ::close(file_info_->fd);
            file_info_->fd = -1;
            throw FileException("Failed to set file size");
        }
        
        // 映射文件
        file_info_->file_start = static_cast<uint8_t*>(
            mmap(nullptr, file_info_->file_size, PROT_READ | PROT_WRITE, 
                 MAP_SHARED, file_info_->fd, 0));
        if (file_info_->file_start == MAP_FAILED) {
            ::close(file_info_->fd);
            file_info_->fd = -1;
            throw FileException("Failed to map file");
        }
        
        // 初始化文件头
        file_info_->file_header = reinterpret_cast<FileHeader*>(file_info_->file_start);
        new (file_info_->file_header) FileHeader();
        file_info_->file_header->total_pages = 1; // 文件头占用第0页
        file_info_->file_header->page_size = PAGE_SIZE;
        
        // 初始化第0页为元数据页
        Page meta_page(0, PageType::METADATA);
        meta_page.serialize(file_info_->file_start + PAGE_SIZE, PAGE_SIZE);
        
        flush();
    } else {
        // 映射已有文件
        file_info_->file_start = static_cast<uint8_t*>(
            mmap(nullptr, file_info_->file_size, PROT_READ | PROT_WRITE, 
                 MAP_SHARED, file_info_->fd, 0));
        if (file_info_->file_start == MAP_FAILED) {
            ::close(file_info_->fd);
            file_info_->fd = -1;
            throw FileException("Failed to map existing file");
        }
        
        file_info_->file_header = reinterpret_cast<FileHeader*>(file_info_->file_start);
        
        // 验证文件格式
        if (file_info_->file_header->magic != DB_MAGIC) {
            munmap(file_info_->file_start, file_info_->file_size);
            ::close(file_info_->fd);
            file_info_->fd = -1;
            throw FileException("Invalid database file format");
        }
    }
    
    return true;
}

void FileManager::close() {
    if (file_info_->fd != -1) {
        flush();
        
        if (file_info_->file_start) {
            munmap(file_info_->file_start, file_info_->file_size);
            file_info_->file_start = nullptr;
        }
        
        ::close(file_info_->fd);
        file_info_->fd = -1;
        file_info_->file_header = nullptr;
        file_info_->filename.clear();
    }
}

bool FileManager::is_open() const {
    return file_info_->fd != -1;
}

std::string FileManager::get_filename() const {
    return file_info_->filename;
}

uint32_t FileManager::get_file_size() const {
    if (!file_info_->file_header) return 0;
    return file_info_->file_header->total_pages;
}

uint32_t FileManager::allocate_page(PageType type) {
    if (!file_info_->file_header) {
        throw FileException("File not open");
    }
    
    FileHeader* hdr = file_info_->file_header;
    uint32_t page_id;
    
    // 优先从空闲链表分配
    if (hdr->first_free_page != 0) {
        // 读取空闲页的页头获取下一个空闲页
        uint8_t* free_page_data = file_info_->file_start + 
                                   hdr->first_free_page * PAGE_SIZE;
        PageHeader* free_header = reinterpret_cast<PageHeader*>(free_page_data);
        
        page_id = hdr->first_free_page;
        hdr->first_free_page = free_header->next_free;
        hdr->free_page_count--;
    } else {
        // 没有空闲页，扩展文件
        page_id = hdr->total_pages;
        hdr->total_pages++;
        
        // 扩展文件映射
        size_t new_size = hdr->total_pages * PAGE_SIZE;
        if (munmap(file_info_->file_start, file_info_->file_size) == -1) {
            throw FileException("Failed to unmap file for resize");
        }
        
        // 调整文件大小
        if (::ftruncate(file_info_->fd, new_size) == -1) {
            throw FileException("Failed to extend file");
        }
        
        // 重新映射
        file_info_->file_start = static_cast<uint8_t*>(
            mmap(nullptr, new_size, PROT_READ | PROT_WRITE, 
                 MAP_SHARED, file_info_->fd, 0));
        if (file_info_->file_start == MAP_FAILED) {
            throw FileException("Failed to remap file after resize");
        }
        
        file_info_->file_size = new_size;
        file_info_->file_header = reinterpret_cast<FileHeader*>(file_info_->file_start);
    }
    
    // 初始化新页
    Page new_page(page_id, type);
    uint8_t* page_data = file_info_->file_start + page_id * PAGE_SIZE;
    new_page.serialize(page_data, PAGE_SIZE);
    
    return page_id;
}

void FileManager::free_page(uint32_t page_id) {
    if (page_id == 0) {
        throw FileException("Cannot free page 0 (file header)");
    }
    
    if (!file_info_->file_header) {
        throw FileException("File not open");
    }
    
    if (page_id >= file_info_->file_header->total_pages) {
        throw FileException("Invalid page ID");
    }
    
    FileHeader* hdr = file_info_->file_header;
    
    // 读取该页的页头
    uint8_t* page_data = file_info_->file_start + page_id * PAGE_SIZE;
    PageHeader* page_header = reinterpret_cast<PageHeader*>(page_data);
    
    // 设置为空闲页并加入空闲链表
    Page free_page(page_id, PageType::FREE);
    page_header->type = PageType::FREE;
    page_header->next_free = hdr->first_free_page;
    page_header->free_space = PAGE_SIZE - sizeof(PageHeader);
    page_header->slot_count = 0;
    page_header->data_end = 0;
    
    hdr->first_free_page = page_id;
    hdr->free_page_count++;
    
    // Dirty marking handled automatically by mmap. Modifications take effect
    // immediately, but flush ensures data is synced to disk.
}

std::unique_ptr<Page> FileManager::read_page(uint32_t page_id) {
    if (!file_info_->file_header) {
        throw FileException("File not open");
    }
    
    if (page_id >= file_info_->file_header->total_pages) {
        throw FileException("Page ID out of range: " + std::to_string(page_id));
    }
    
    // 从映射内存直接读取
    uint8_t* page_data = file_info_->file_start + page_id * PAGE_SIZE;
    
    auto page = std::make_unique<Page>();
    page->init_from_raw(page_data, PAGE_SIZE);
    
    return page;
}

void FileManager::write_page(Page* page) {
    if (!file_info_->file_header) {
        throw FileException("File not open");
    }
    
    uint32_t page_id = page->get_page_id();
    if (page_id >= file_info_->file_header->total_pages) {
        throw FileException("Page ID out of range");
    }
    
    uint8_t* page_data = file_info_->file_start + page_id * PAGE_SIZE;
    page->serialize(page_data, PAGE_SIZE);
}

void FileManager::flush() {
    if (file_info_->file_start) {
        // msync确保数据写入磁盘
        if (msync(file_info_->file_start, file_info_->file_size, MS_SYNC) == -1) {
            std::cerr << "Warning: msync failed: " << strerror(errno) << std::endl;
        }
    }
}

std::vector<uint32_t> FileManager::get_free_pages() const {
    std::vector<uint32_t> free_list;
    
    if (!file_info_->file_header) return free_list;
    
    uint32_t current = file_info_->file_header->first_free_page;
    while (current != 0) {
        free_list.push_back(current);
        
        // 获取下一个空闲页
        uint8_t* page_data = file_info_->file_start + current * PAGE_SIZE;
        PageHeader* header = reinterpret_cast<PageHeader*>(page_data);
        current = header->next_free;
    }
    
    return free_list;
}

} // namespace db