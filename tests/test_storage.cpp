#include <iostream>
#include <string>
#include "../src/include/storage_engine.h"

using namespace db;

int main() {
    std::cout << "=== 存储引擎测试 ===\n" << std::endl;
    
    try {
        // 1. 创建存储引擎实例
        StorageEngine engine;
        
        // 2. 创建或打开数据库
        std::string db_file = "test_db.dat";
        if (!engine.create_or_open(db_file)) {
            std::cerr << "无法打开数据库文件" << std::endl;
            return 1;
        }
        
        // 3. 查看初始状态
        auto stats1 = engine.get_stats();
        std::cout << "初始状态:" << std::endl;
        std::cout << "  总页数: " << stats1.total_pages << std::endl;
        std::cout << "  已分配页: " << stats1.allocated_pages << std::endl;
        std::cout << "  空闲页: " << stats1.free_pages << std::endl;
        std::cout << "  文件大小: " << stats1.file_size_bytes << " 字节" << std::endl;
        
        // 4. 分配多个数据页
        std::cout << "\n分配数据页..." << std::endl;
        std::vector<uint32_t> data_pages;
        for (int i = 0; i < 5; i++) {
            uint32_t page_id = engine.allocate_data_page();
            data_pages.push_back(page_id);
            std::cout << "  分配数据页 #" << page_id << std::endl;
        }
        
        // 5. 分配索引页
        std::cout << "\n分配索引页..." << std::endl;
        std::vector<uint32_t> index_pages;
        for (int i = 0; i < 3; i++) {
            uint32_t page_id = engine.allocate_index_page();
            index_pages.push_back(page_id);
            std::cout << "  分配索引页 #" << page_id << std::endl;
        }
        
        // 6. 读取并修改数据页（使用槽目录接口）
        std::cout << "\n读取和写入页..." << std::endl;
        for (uint32_t page_id : data_pages) {
            auto page = engine.read_page(page_id);
            std::cout << "  页 #" << page_id 
                      << " (类型: " << static_cast<int>(page->get_type())
                      << ", 空闲空间: " << page->get_free_space() << ")" << std::endl;
            
            // 使用新的槽目录接口插入记录
            const char* test_data = "Hello, Storage Engine! This is a test message.";
            int slot_id = page->insert_record(
                reinterpret_cast<const uint8_t*>(test_data), 
                static_cast<uint16_t>(strlen(test_data) + 1)
            );
            if (slot_id >= 0) {
                page->set_dirty(true);
                engine.write_page(page.get());
                std::cout << "    已插入测试记录到槽 #" << slot_id << std::endl;
            }
        }
        
        // 7. 查看分配后的状态
        auto stats2 = engine.get_stats();
        std::cout << "\n分配后状态:" << std::endl;
        std::cout << "  总页数: " << stats2.total_pages << std::endl;
        std::cout << "  已分配页: " << stats2.allocated_pages << std::endl;
        std::cout << "  空闲页: " << stats2.free_pages << std::endl;
        std::cout << "  文件大小: " << stats2.file_size_bytes << " 字节" << std::endl;
        
        // 8. 测试释放页
        std::cout << "\n释放部分页..." << std::endl;
        if (!data_pages.empty()) {
            uint32_t page_to_free = data_pages[0];
            engine.free_page(page_to_free);
            std::cout << "  已释放页 #" << page_to_free << std::endl;
        }
        
        // 9. 查看释放后的状态
        auto stats3 = engine.get_stats();
        std::cout << "\n释放后状态:" << std::endl;
        std::cout << "  已分配页: " << stats3.allocated_pages << std::endl;
        std::cout << "  空闲页: " << stats3.free_pages << std::endl;
        
        // 10. 刷新并关闭
        std::cout << "\n刷新并关闭数据库..." << std::endl;
        engine.flush();
        engine.close();
        
        // 11. 重新打开数据库，验证持久化
        std::cout << "\n重新打开数据库..." << std::endl;
        if (!engine.create_or_open(db_file)) {
            std::cerr << "无法重新打开数据库" << std::endl;
            return 1;
        }
        
        auto stats4 = engine.get_stats();
        std::cout << "重新打开后状态:" << std::endl;
        std::cout << "  总页数: " << stats4.total_pages << std::endl;
        std::cout << "  已分配页: " << stats4.allocated_pages << std::endl;
        std::cout << "  空闲页: " << stats4.free_pages << std::endl;
        
        // 验证数据持久化：读取之前写入的页（使用新槽目录接口）
        std::cout << "\n验证数据持久化（槽目录）:" << std::endl;
        for (uint32_t page_id : data_pages) {
            if (page_id == data_pages[0]) continue; // 跳过已释放的页
            
            auto page = engine.read_page(page_id);
            std::cout << "  页 #" << page_id 
                      << " (类型: " << static_cast<int>(page->get_type())
                      << ", 槽数: " << page->get_slot_count() << ")" << std::endl;
            
            // 使用迭代器遍历所有记录
            page->iterate_records([](uint16_t slot_id, const uint8_t* data, uint16_t len, void* ctx) {
                std::string record_str(reinterpret_cast<const char*>(data), len);
                std::cout << "    槽#" << slot_id << ": " << record_str << std::endl;
            });
        }
        
        engine.close();
        
        std::cout << "\n=== 测试完成 ===" << std::endl;
        
    } catch (const std::exception& e) {
        std::cerr << "测试失败: " << e.what() << std::endl;
        return 1;
    }
    
    return 0;
}