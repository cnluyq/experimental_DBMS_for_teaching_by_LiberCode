# 实验性教学DBMS - 存储引擎模块
# 使用C++17标准

CXX = g++
CXXFLAGS = -std=c++17 -Wall -Wextra -Wpedantic -O2 -g
LDFLAGS = -lstdc++fs 

# 源文件路径
SRC_DIR = src
CORE_SRCS = $(SRC_DIR)/core/page.cpp $(SRC_DIR)/core/file_manager.cpp \
            $(SRC_DIR)/core/page_allocator.cpp $(SRC_DIR)/core/storage_engine.cpp \
            $(SRC_DIR)/core/wal.cpp $(SRC_DIR)/core/transaction.cpp
INC_DIR = $(SRC_DIR)/include

# 测试文件
TEST_SRCS = tests/test_storage.cpp

# 目标
TARGET = db_storage
TEST_TARGET = test_storage

# 默认目标
all: $(TARGET)

# 静态库
$(TARGET):
	$(CXX) $(CXXFLAGS) -I$(INC_DIR) -c $(SRC_DIR)/core/page.cpp -o page.o
	$(CXX) $(CXXFLAGS) -I$(INC_DIR) -c $(SRC_DIR)/core/file_manager.cpp -o file_manager.o
	$(CXX) $(CXXFLAGS) -I$(INC_DIR) -c $(SRC_DIR)/core/page_allocator.cpp -o page_allocator.o
	$(CXX) $(CXXFLAGS) -I$(INC_DIR) -c $(SRC_DIR)/core/storage_engine.cpp -o storage_engine.o
	$(CXX) $(CXXFLAGS) -I$(INC_DIR) -c $(SRC_DIR)/core/wal.cpp -o wal.o
	$(CXX) $(CXXFLAGS) -I$(INC_DIR) -c $(SRC_DIR)/core/transaction.cpp -o transaction.o
	ar rcs lib$(TARGET).a page.o file_manager.o page_allocator.o storage_engine.o wal.o transaction.o
	echo "Static library lib$(TARGET).a built"

# 测试程序
test: $(TEST_TARGET)

$(TEST_TARGET): $(TEST_SRCS) $(TARGET)
	$(CXX) $(CXXFLAGS) -I$(INC_DIR) tests/test_storage.cpp -L. -l$(TARGET) -o $(TEST_TARGET)

# 运行测试
run-test: $(TEST_TARGET)
	./$(TEST_TARGET)

# 清理
clean:
	rm -f *.o *.a $(TEST_TARGET) core.*
	rm -rf test_db.dat

# 帮助
help:
	@echo "可用目标:"
	@echo "  all       - 构建存储引擎静态库 (libdb_storage.a)"
	@echo "  test      - 构建并运行测试程序"
	@echo "  run-test  - 运行测试程序（需先构建）"
	@echo "  clean     - 清理构建文件和测试文件"
	@echo "  help      - 显示此帮助信息"

.PHONY: all test run-test clean help