#ifndef PAGE_H
#define PAGE_H

#include <cstdint>
#include <cstring>

namespace db {

// 页大小定义（4KB）
constexpr size_t PAGE_SIZE = 4096;

// 页类型枚举
enum class PageType : uint8_t {
    UNKNOWN = 0,
    DATA = 1,        // 数据页
    INDEX = 2,       // 索引页
    METADATA = 3,    // 元数据页
    FREE = 255       // 空闲页
};

// 槽目录条目：记录在页中的位置和长度
struct Slot {
    uint16_t offset;  // 记录在数据区的偏移量（从页头之后开始）
    uint16_t length;  // 记录长度（字节）
    
    Slot() : offset(0), length(0) {}
    Slot(uint16_t off, uint16_t len) : offset(off), length(len) {}
};

// 页头结构（位于每页的开头）
struct PageHeader {
    PageType type;       // 页类型
    uint32_t page_id;    // 页ID（在文件中的位置）
    uint32_t next_free;  // 空闲链表下一页（仅空闲页使用）
    uint16_t free_space; // 空闲空间大小（数据区剩余空间）
    uint16_t slot_count; // 槽数量（数据页使用）
    uint16_t data_end;   // 数据区尾部偏移（从页头之后），用于紧凑存储
    uint8_t  reserved[6]; // 保留字段，用于扩展
    
    PageHeader() : type(PageType::UNKNOWN), page_id(0), next_free(0), 
                   free_space(PAGE_SIZE - sizeof(PageHeader)), 
                   slot_count(0), data_end(0) {
        memset(reserved, 0, sizeof(reserved));
    }
};

// 页类 - 封装页的基本操作
class Page {
private:
    uint8_t* data_;          // 页数据指针
    PageHeader* header_;     // 页头指针
    bool dirty_;             // 脏标志
    
public:
    // 构造函数
    Page(uint32_t page_id = 0, PageType type = PageType::UNKNOWN);
    
    // 析构函数
    ~Page();
    
    // 禁止拷贝
    Page(const Page&) = delete;
    Page& operator=(const Page&) = delete;
    
    // 移动语义
    Page(Page&& other) noexcept;
    Page& operator=(Page&& other) noexcept;
    
    // 获取页ID
    uint32_t get_page_id() const { return header_->page_id; }
    
    // 获取页类型
    PageType get_type() const { return header_->type; }
    
    // 设置页类型
    void set_type(PageType type) { header_->type = type; }
    
    // 获取空闲空间大小
    uint16_t get_free_space() const { return header_->free_space; }
    
    // 获取数据指针（跳过页头）
    uint8_t* get_data() { return data_ + sizeof(PageHeader); }
    
    // 获取常量数据指针
    const uint8_t* get_data() const { return data_ + sizeof(PageHeader); }
    
    // 获取可写的原始数据指针（包含页头）
    uint8_t* get_raw_data() { return data_; }
    
    // 获取常量原始数据指针
    const uint8_t* get_raw_data() const { return data_; }
    
    // 获取页头
    PageHeader* get_header() { return header_; }
    
    // 设置脏标志
    void set_dirty(bool dirty) { dirty_ = dirty; }
    
    // 检查是否脏
    bool is_dirty() const { return dirty_; }
    
    // 重置页内容
    void reset(PageType type = PageType::UNKNOWN);
    
    // 从原始数据初始化页
    void init_from_raw(const uint8_t* raw_data, size_t size);
    
    // 将页内容序列化到缓冲区
    void serialize(uint8_t* buffer, size_t buffer_size) const;
    
    // 从缓冲区反序列化页
    void deserialize(const uint8_t* buffer, size_t buffer_size);
    
    // 分配空间（从空闲空间）
    bool allocate(size_t size, uint32_t& offset);
    
    // === 数据页专用方法（槽目录管理）===
    
    // 获取槽数量
    uint16_t get_slot_count() const { return header_->slot_count; }
    
    // 获取数据区结束位置（从页头之后）
    uint16_t get_data_end() const { return header_->data_end; }
    
    // 获取槽目录起始位置（数据区末尾之后，从页尾向前增长）
    uint32_t get_slot_area_start() const { return sizeof(PageHeader) + header_->data_end; }
    
    // 计算槽目录条目位置
    uint8_t* get_slot_ptr(uint16_t slot_id);
    const uint8_t* get_slot_ptr(uint16_t slot_id) const;
    
    // 插入记录：返回槽ID，或-1表示失败
    int insert_record(const uint8_t* record_data, uint16_t record_len);
    
    // 删除记录（标记为删除，不立即回收空间）
    bool delete_record(uint16_t slot_id);
    
    // 更新记录（替换内容）
    bool update_record(uint16_t slot_id, const uint8_t* record_data, uint16_t record_len);
    
    // 获取记录数据指针和长度
    const uint8_t* get_record(uint16_t slot_id, uint16_t& out_len) const;
    
    // 遍历所有有效记录
    void iterate_records(void (*callback)(uint16_t slot_id, const uint8_t* data, uint16_t len, void* ctx), void* ctx = nullptr) const;
    
    // 紧凑化页面（合并删除的记录碎片）
    void compact();
    
    // 释放空间 - 已废弃，使用delete_record替代
    void deallocate(uint32_t offset, size_t size);
};

} // namespace db

#endif // PAGE_H