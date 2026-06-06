# ProjoDB 实验指南：编译、运行与测试SQL

## 🎯 实验目标

完成本指南后，你将能够：
1. ✅ 编译和运行ProjoDB
2. ✅ 使用Python API操作存储引擎和缓冲区池
3. ✅ 解析和执行SQL查询
4. ✅ 运行自动化测试
5. ✅ 进行性能基准测试

---

## 📦 环境准备

### 1. 系统要求

- **操作系统**：Linux (Ubuntu 20.04+), macOS (10.15+), Windows (WSL2)
- **Python**：3.8 或更高版本
  ```bash
  python3 --version  # 应显示 3.8.x 或更高
  ```
- **C++编译器**（可选，用于C++模块）：
  - Linux: `g++` 或 `clang++`
  - macOS: Xcode Command Line Tools
  - Windows: MSVC 或 MinGW
- **Git**：版本控制

### 2. 克隆项目

```bash
# 克隆仓库（替换为实际URL）
git clone https://github.com/your-org/projo.git
cd projo

# 查看目录结构
tree -L 2  # 或 find . -maxdepth 2 -type d
```

### 3. 安装Python依赖

```bash
# 创建虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 验证安装
pip list | grep pytest
```

**requirements.txt** 示例：
```
pytest>=6.0
typing-extensions>=4.0
```

---

## 🚀 快速开始：Python API

### 示例1：存储引擎基础

```python
# examples/demo_storage.py
from src.core.storage_interface import SimpleFileStorage

def demo_storage():
    # 1. 创建/打开数据库文件
    storage = SimpleFileStorage("mydb.dat", page_size=4096)
    print(f"页大小: {storage.get_page_size()} 字节")

    # 2. 分配数据页
    page_id = storage.allocate_page()
    print(f"分配的页ID: {page_id}")

    # 3. 写入页面数据
    data = b"Hello ProjoDB!".ljust(4096, b'\x00')
    storage.page_write(page_id, data)
    print("页面已写入")

    # 4. 读取页面验证
    read_data = storage.page_read(page_id)
    print(f"读取前20字节: {read_data[:20]}")
    assert read_data[:15] == b"Hello ProjoDB!"

    # 5. 关闭
    storage.close()
    print("数据库已关闭")

if __name__ == "__main__":
    demo_storage()
```

**运行**：
```bash
python examples/demo_storage.py
```

---

### 示例2：缓冲区池

```python
# examples/demo_buffer.py
from src.core.buffer import BufferPool
from src.core.storage_interface import InMemoryStorage

def demo_buffer():
    # 1. 初始化
    storage = InMemoryStorage(page_size=4096)
    buffer = BufferPool(num_frames=10, storage_engine=storage)

    # 2. 预热：写入一些页面
    for i in range(5):
        page_id = storage.allocate_page()
        data = f"Page {i}".encode().ljust(4096, b'\x00')
        storage.page_write(page_id, data)

    # 3. 读取测试
    print("=== 缓存命中测试 ===")
    for i in range(5):
        frame = buffer.read_page(page_id=i)
        print(f"读取页 {i}: {frame.data[:10]}")
        buffer.unpin_page(i)

    stats = buffer.get_buffer_stats()
    print(f"\n统计: 命中={stats['hits']}, 未命中={stats['misses']}, 命中率={stats['hit_rate']:.2%}")

    # 4. 修改并标记脏页
    frame = buffer.read_page(page_id=0)
    frame.data[0:5] = b"MERRY"
    buffer.mark_dirty(0)
    buffer.unpin_page(0)

    # 5. 刷新
    buffer.flush_all()
    buffer.shutdown()

if __name__ == "__main__":
    demo_buffer()
```

**运行**：
```bash
python examples/demo_buffer.py
```

---

### 示例3：SQL解析器

```python
# examples/demo_parser.py
from src.parser import parse

def demo_parser():
    test_sqls = [
        "SELECT * FROM users",
        "SELECT name, age FROM users WHERE age > 18",
        "INSERT INTO users VALUES (1, 'Alice', 25)",
        "CREATE TABLE users (id INT PRIMARY KEY, name VARCHAR(50), age INT)",
        "UPDATE users SET age = 26 WHERE id = 1",
        "DELETE FROM users WHERE age < 18",
        "BEGIN; COMMIT;",
    ]

    for sql in test_sqls:
        print(f"\nSQL: {sql}")
        try:
            ast = parse(sql)
            print(f"  → {type(ast).__name__}")
            if hasattr(ast, 'where_clause') and ast.where_clause:
                print(f"  → WHERE: {ast.where_clause}")
        except Exception as e:
            print(f"  ✗ 错误: {e}")

if __name__ == "__main__":
    demo_parser()
```

**运行**：
```bash
python examples/demo_parser.py
```

---

### 示例4：WAL日志

```python
# examples/demo_wal.py
from src.core.wal import WALManager
import os

def demo_wal():
    log_path = "demo_wal.log"
    if os.path.exists(log_path):
        os.remove(log_path)

    # 1. 创建WAL管理器
    wal = WALManager(log_path)
    print("WAL管理器已创建")

    # 2. 记录事务操作
    txn1 = 1
    wal.log_begin(txn1)
    print(f"记录 BEGIN 事务 {txn1}")

    wal.log_update(
        txn_id=txn1,
        page_id=100,
        before=b"old_data_12345",
        after=b"new_data_67890"
    )
    print("记录 UPDATE (页100)")

    wal.log_commit(txn1)
    print(f"记录 COMMIT 事务 {txn1}")

    wal.flush()
    print("日志已刷盘")

    # 3. 查看日志文件
    size = os.path.getsize(log_path)
    print(f"日志文件大小: {size} 字节")

    # 4. 模拟崩溃恢复
    print("\n=== 模拟恢复 ===")
    result = wal.recover()
    print(f"重做 {len(result.redos)} 条，撤销 {len(result.undos)} 条")
    for r in result.redos:
        print(f"  REDO: 事务{r.txn_id}, 页{r.page_id}")
    for u in result.undos:
        print(f"  UNDO: 事务{u.txn_id}, 页{u.page_id}")

    wal.close()
    print("WAL已关闭")

if __name__ == "__main__":
    demo_wal()
```

**运行**：
```bash
python examples/demo_wal.py
```

---

## 🔧 编译C++模块（可选）

如果你需要更高性能或想学习C++，可以编译核心存储引擎。

### 1. 构建静态库

```bash
# 在项目根目录
make build
# 或
make all
```

**输出**：
- `libdb_storage.a`：静态库
- 各 `.o` 目标文件

### 2. 运行C++测试

```bash
make test
# 或直接
./test_storage
```

### 3. 清理

```bash
make clean
```

---

## 🧪 运行自动化测试

### 使用pytest运行所有测试

```bash
# 基础运行
pytest tests/ -v

# 或使用Make
make check
```

### 测试模块细分

```bash
# 测试缓冲区池
pytest tests/test_buffer.py -v

# 测试B+树
pytest tests/test_bplus_tree.py -v

# 测试WAL
pytest tests/test_wal.py -v

# 测试解析器
pytest tests/parser/test_sql_parser.py -v

# 测试存储引擎（C++）
make test
```

### 测试覆盖率（可选）

```bash
# 安装pytest-cov
pip install pytest-cov

# 运行并查看覆盖率
pytest tests/ --cov=src --cov-report=html
# 打开 htmlcov/index.html 查看详细报告
```

---

## 💻 动手实验：构建简单数据库应用

让我们从头到尾走一遍，创建一个简单的用户管理系统。

### 步骤1：创建数据库表

```python
# myapp.py
from src.executor.table_manager import TableManager
from src.core.buffer import BufferPool
from src.core.storage_interface import SimpleFileStorage

def create_users_table():
    storage = SimpleFileStorage("mydb.dat")
    buffer = BufferPool(num_frames=50, storage_engine=storage)

    table_mgr = TableManager(buffer)
    table_mgr.create_table(
        "users",
        columns=[
            ("id", "INT"),
            ("name", "VARCHAR(50)"),
            ("age", "INT")
        ],
        primary_key="id"
    )
    print("表 'users' 已创建")
    buffer.shutdown()
```

### 步骤2：插入数据

```python
def insert_sample_data():
    # 同上初始化 storage, buffer, table_mgr
    table_mgr = TableManager(buffer)

    # 插入记录
    records = [
        (1, "Alice", 25),
        (2, "Bob", 30),
        (3, "Charlie", 35),
        (4, "David", 28),
    ]

    for rec in records:
        table_mgr.insert("users", rec)
        print(f"插入: {rec}")

    buffer.shutdown()
```

### 步骤3：查询数据

```python
def query_users():
    # 初始化
    storage = SimpleFileStorage("mydb.dat")
    buffer = BufferPool(num_frames=50, storage_engine=storage)

    # 使用执行器（假设已实现）
    from src.executor.executor import Executor
    executor = Executor(buffer)

    # 执行SQL
    sql = "SELECT * FROM users WHERE age > 25"
    ast = parse(sql)
    results = executor.execute(ast)

    for row in results:
        print(row)

    buffer.shutdown()
```

---

## ⚡ 性能基准测试

### 缓冲区命中率测试

```python
# experiments/benchmark_buffer.py
from src.core.buffer import BufferPool
from src.core.storage_interface import SimpleFileStorage
import random, time

def benchmark(num_frames=100, num_accesses=10000, workload="random"):
    """
    Args:
        num_frames: 缓冲区帧数
        num_accesses: 总访问次数
        workload: "random"随机 或 "sequential"顺序
    """
    storage = SimpleFileStorage("benchmark.db")
    buffer = BufferPool(num_frames=num_frames, storage_engine=storage)

    # 预创建1000个页面
    num_pages = 1000
    for i in range(num_pages):
        page_id = storage.allocate_page()
        storage.page_write(page_id, f"Page {i}".ljust(4096, b'\x00'))

    # 生成访问序列
    if workload == "random":
        accesses = [random.randint(0, num_pages-1) for _ in range(num_accesses)]
    else:
        accesses = list(range(num_prames % num_pages) for _ in range(num_accesses))

    # 执行
    start = time.time()
    for page_id in accesses:
        frame = buffer.read_page(page_id, pin=False)  # pin=False模拟只读
        _ = frame.data[0]
    elapsed = time.time() - start

    stats = buffer.get_buffer_stats()
    buffer.shutdown()

    print(f"=== 缓冲区基准测试 ===")
    print(f"帧数: {num_frames}")
    print(f"访问次数: {num_accesses}")
    print(f"工作负载: {workload}")
    print(f"命中率: {stats['hit_rate']:.2%}")
    print(f"总时间: {elapsed:.3f}s")
    print(f"平均访问时间: {elapsed/num_accesses*1000:.3f}ms")

if __name__ == "__main__":
    benchmark(num_frames=100, num_accesses=10000, workload="random")
```

---

### B+树性能测试

```python
# experiments/benchmark_bptree.py
from src.index.bplus_tree import BPlusTree
from src.core.storage_interface import InMemoryStorage
import random, time

def benchmark_bptree(num_keys=10000, order=32):
    storage = InMemoryStorage(page_size=4096)
    tree = BPlusTree(storage, order=order)

    # 插入
    keys = random.sample(range(1000000), num_keys)
    start = time.time()
    for key in keys:
        tree.insert(key, f"value_{key}")
    insert_time = time.time() - start
    print(f"插入 {num_keys} 条: {insert_time:.3f}s ({num_keys/insert_time:.0f} ops/s)")

    # 点查询
    random_keys = random.sample(keys, min(1000, num_keys))
    start = time.time()
    for key in random_keys:
        tree.search(key)
    search_time = time.time() - start
    print(f"点查询 1000 次: {search_time:.3f}s ({1000/search_time:.0f} ops/s)")

    # 范围查询
    low = random.randint(0, 500000)
    high = low + 1000
    start = time.time()
    count = 0
    for k, v in tree.range_scan(low, high):
        count += 1
    range_time = time.time() - start
    print(f"范围查询 [{low}, {high}): 找到 {count} 条，{range_time:.6f}s")

    tree.close()

if __name__ == "__main__":
    benchmark_bptree(num_keys=10000)
```

---

## 🐛 调试技巧

### 1. 开启详细日志

```python
import logging
logging.basicConfig(level=logging.DEBUG)
# 或针对特定模块
logging.getLogger('src.core.buffer').setLevel(logging.DEBUG)
```

### 2. 使用pdb断点调试

```python
import pdb

def my_function():
    pdb.set_trace()  # 调试开始
    # ...
    # n: next, s: step into, c: continue, l: list, p var: print
```

### 3. 可视化B+树结构

```python
def print_bptree(tree):
    """打印B+树结构（调试）"""
    root = tree._read_node(tree.root_id)
    print_tree(root, "")

def print_tree(node, indent):
    if node.is_leaf():
        print(f"{indent}Leaf: {node.keys}")
    else:
        print(f"{indent}Internal: {node.keys}")
        for ptr in node.pointers:
            child = tree._read_node(ptr)
            print_tree(child, indent + "  ")
```

---

## 📊 性能优化建议

### 1. 缓冲区调优
- 增加`num_frames`提高命中率（检查命中率-帧数曲线）
- 使用Clock算法替代LRU（低开销）
- 预取（Prefetching）顺序访问的下一个页

### 2. B+树调优
- 选择合适的order（通常一页填满）
- 批量插入（排序后构建更高效）
- 使用复合索引（多列）

### 3. WAL调优
- 组提交：批量fsync
- 日志缓冲区大小：4KB-64KB

---

## 🧩 故障排除

### 问题1：`ImportError: No module named 'src'`

**解决方案**：
```bash
# 确保在项目根目录运行
cd projo
python -m examples.demo_storage  # 使用-m
# 或设置PYTHONPATH
export PYTHONPATH=/path/to/projo:$PYTHONPATH
python examples/demo_storage.py
```

### 问题2：权限错误（写入数据库文件）

**解决方案**：
```bash
# 检查文件权限
ls -la mydb.dat
# 更改所有者或权限
chmod 644 mydb.dat
# 或运行在可写目录
mkdir -p /tmp/projo_test && cd /tmp/projo_test
```

### 问题3：C++编译错误

**解决方案**：
```bash
# 确保g++支持C++17
g++ --version
# 应显示 7.x 或更高

# 检查Makefile中的CXXFLAGS
make clean && make build
```

### 问题4：测试失败（时序问题）

**解决方案**：
- 确保测试间清理临时文件
- WAL日志文件冲突：每次测试使用唯一文件名
- 多线程测试：增加等待/重试

---

## 📚 下一步学习路径

完成基础实验后，建议按以下顺序深入：

1. **存储引擎进阶**
   - 实现位图页分配器
   - 添加页压缩
   - 多文件表空间

2. **索引优化**
   - 实现变长键处理
   - 添加前缀压缩
   - 并发B+树（锁耦合）

3. **事务与并发**
   - 实现行级锁
   - 死锁检测
   - 隔离级别Read Committed

4. **查询执行**
   - 实现火山模型完整算子
   - 添加简单优化器
   - 支持JOIN

5. **WAL与恢复**
   - 完整ARIES恢复
   - 检查点机制
   - 日志截断

---

## 📝 实验报告模板

完成实验后，建议撰写报告。

```markdown
# 实验报告：XXX

## 一、实验目标
- [ ] 目标1
- [ ] 目标2

## 二、环境配置
- 操作系统：
- Python版本：
- 实验日期：

## 三、设计与实现
### 3.1 方案设计
[你的设计思路，可画图]

### 3.2 关键代码
```python
# 你的核心实现
def my_function():
    pass
```

### 3.3 测试方法
[如何验证正确性]

## 四、实验结果
### 4.1 功能验证
[截图/输出]

### 4.2 性能数据
[表格]

### 4.3 问题与解决
[遇到的问题]

## 五、分析与讨论
- 时间复杂度：
- 空间复杂度：
- 可能的优化：

## 六、总结与收获
[200字总结]
```

---

## 🆘 获取帮助

### 文档
- 主README：`README.md`
- 模块文档：`docs/modules/`
- 设计文档：`docs/DATABASE_DESIGN.md`

### 代码
- 示例：`examples/`
- 测试：`tests/`
- 源文件：`src/`

### 社区
- GitHub Issues：报告bug或提问
- Discussions：讨论设计思路

---

**祝实验顺利！** 🎉

有任何问题，请查看文档或在GitHub Issues中提问。
