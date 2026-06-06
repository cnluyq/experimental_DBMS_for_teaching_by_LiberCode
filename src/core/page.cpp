#include "page.h"
#include <cstring>
#include <stdexcept>
#include <vector>
#include <utility> // for std::pair

namespace db {

Page::Page(uint32_t page_id, PageType type) 
    : dirty_(false) {
    // 分配页大小的内存
    data_ = new uint8_t[PAGE_SIZE];
    
    // 初始化页头
    header_ = reinterpret_cast<PageHeader*>(data_);
    new (header_) PageHeader();
    
    header_->page_id = page_id;
    header_->type = type;
    header_->free_space = PAGE_SIZE - sizeof(PageHeader);
    
    // 初始化数据区域为0
    memset(get_data(), 0, get_free_space());
}

Page::~Page() {
    delete[] data_;
}

Page::Page(Page&& other) noexcept 
    : data_(other.data_), header_(other.header_), dirty_(other.dirty_) {
    other.data_ = nullptr;
    other.header_ = nullptr;
}

Page& Page::operator=(Page&& other) noexcept {
    if (this != &other) {
        delete[] data_;
        data_ = other.data_;
        header_ = other.header_;
        dirty_ = other.dirty_;
        other.data_ = nullptr;
        other.header_ = nullptr;
    }
    return *this;
}

void Page::reset(PageType type) {
    if (data_ == nullptr) {
        throw std::runtime_error("Page not initialized");
    }
    
    // 重置页头
    new (header_) PageHeader();
    header_->type = type;
    header_->free_space = PAGE_SIZE - sizeof(PageHeader);
    
    // 清零数据区域
    memset(get_data(), 0, get_free_space());
    dirty_ = true;
}

void Page::init_from_raw(const uint8_t* raw_data, size_t size) {
    if (size != PAGE_SIZE) {
        throw std::runtime_error("Invalid page size");
    }
    
    // 复制原始数据
    memcpy(data_, raw_data, PAGE_SIZE);
    dirty_ = false;
}

void Page::serialize(uint8_t* buffer, size_t buffer_size) const {
    if (buffer_size < PAGE_SIZE) {
        throw std::runtime_error("Buffer too small for page serialization");
    }
    memcpy(buffer, data_, PAGE_SIZE);
}

void Page::deserialize(const uint8_t* buffer, size_t buffer_size) {
    if (buffer_size != PAGE_SIZE) {
        throw std::runtime_error("Invalid buffer size for deserialization");
    }
    memcpy(data_, buffer, PAGE_SIZE);
    dirty_ = false;
}

bool Page::allocate(size_t size, uint32_t& offset) {
    // 注意：此方法已被新的槽目录管理替代，保留用于兼容性但不实际操作
    // 实际记录插入使用 insert_record()
    offset = 0;
    return false;
}

// === 辅助函数 ===

// 获取指定槽ID的槽指针
uint8_t* Page::get_slot_ptr(uint16_t slot_id) {
    uint32_t slot_area_start = get_slot_area_start();
    uint8_t* slot_ptr = data_ + slot_area_start + slot_id * sizeof(Slot);
    return slot_ptr;
}

const uint8_t* Page::get_slot_ptr(uint16_t slot_id) const {
    uint32_t slot_area_start = get_slot_area_start();
    const uint8_t* slot_ptr = data_ + slot_area_start + slot_id * sizeof(Slot);
    return slot_ptr;
}

// === 数据页专用方法实现 ===

int Page::insert_record(const uint8_t* record_data, uint16_t record_len) {
    if (header_->type != PageType::DATA) {
        return -1; // 只有数据页支持记录操作
    }
    
    // 检查是否有足够空间存储记录和槽目录
    size_t total_needed = record_len + sizeof(Slot);
    if (total_needed > header_->free_space) {
        return -1; // 空间不足
    }
    
    // 将记录数据写入数据区末尾
    uint32_t record_offset = sizeof(PageHeader) + header_->data_end;
    memcpy(data_ + record_offset, record_data, record_len);
    header_->data_end += record_len;
    header_->free_space -= record_len;
    
    // 将槽目录条目写入槽区末尾（在数据区之后）
    uint16_t slot_id = header_->slot_count;
    Slot* slot = reinterpret_cast<Slot*>(get_slot_ptr(slot_id));
    slot->offset = static_cast<uint16_t>(record_offset - sizeof(PageHeader)); // 相对数据区偏移
    slot->length = record_len;
    header_->slot_count++;
    header_->free_space -= sizeof(Slot);
    
    dirty_ = true;
    return slot_id;
}

bool Page::delete_record(uint16_t slot_id) {
    if (slot_id >= header_->slot_count) {
        return false;
    }
    
    // 获取槽信息
    Slot* slot = reinterpret_cast<Slot*>(get_slot_ptr(slot_id));
    slot->offset = 0xFFFF; // 标记为已删除
    slot->length = 0;
    
    dirty_ = true;
    return true;
}

bool Page::update_record(uint16_t slot_id, const uint8_t* record_data, uint16_t record_len) {
    if (slot_id >= header_->slot_count) {
        return false;
    }
    
    Slot* slot = reinterpret_cast<Slot*>(get_slot_ptr(slot_id));
    if (slot->offset == 0xFFFF) {
        return false; // 记录已删除
    }
    
    // 如果新记录长度相同，原地更新
    if (record_len == slot->length) {
        uint8_t* record_ptr = data_ + sizeof(PageHeader) + slot->offset;
        memcpy(record_ptr, record_data, record_len);
        dirty_ = true;
        return true;
    }
    
    // 长度不同，暂不处理复杂情况（需要紧凑化）
    // 简化实现：返回false
    return false;
}

const uint8_t* Page::get_record(uint16_t slot_id, uint16_t& out_len) const {
    if (slot_id >= header_->slot_count) {
        out_len = 0;
        return nullptr;
    }
    
    const Slot* slot = reinterpret_cast<const Slot*>(get_slot_ptr(slot_id));
    if (slot->offset == 0xFFFF) {
        out_len = 0;
        return nullptr; // 已删除
    }
    
    out_len = slot->length;
    return data_ + sizeof(PageHeader) + slot->offset;
}

void Page::iterate_records(void (*callback)(uint16_t slot_id, const uint8_t* data, uint16_t len, void* ctx), void* ctx) const {
    if (header_->type != PageType::DATA) {
        return;
    }
    
    for (uint16_t i = 0; i < header_->slot_count; i++) {
        const Slot* slot = reinterpret_cast<const Slot*>(get_slot_ptr(i));
        if (slot->offset != 0xFFFF) { // 跳过已删除记录
            const uint8_t* record_data = data_ + sizeof(PageHeader) + slot->offset;
            callback(i, record_data, slot->length, ctx);
        }
    }
}

void Page::compact() {
    if (header_->type != PageType::DATA) {
        return;
    }
    
    // 收集所有有效记录
    using RecordPair = std::pair<Slot, std::vector<uint8_t>>;
    std::vector<RecordPair> valid_records;
    
    for (uint16_t i = 0; i < header_->slot_count; i++) {
        Slot* slot = reinterpret_cast<Slot*>(get_slot_ptr(i));
        if (slot->offset != 0xFFFF) {
            uint8_t* record_data = data_ + sizeof(PageHeader) + slot->offset;
            std::vector<uint8_t> data(record_data, record_data + slot->length);
            valid_records.push_back(RecordPair(*slot, std::move(data)));
        }
    }
    
    // 重置页
    reset(PageType::DATA);
    
    // 重新插入有效记录
    for (auto& rec : valid_records) {
        insert_record(rec.second.data(), static_cast<uint16_t>(rec.second.size()));
    }
    
    dirty_ = true;
}

void Page::deallocate(uint32_t offset, size_t size) {
    // 注意：此方法已不推荐使用，改用slot-based管理
    // 保留用于兼容性，但不再更新record_count
    dirty_ = true;
}

} // namespace db