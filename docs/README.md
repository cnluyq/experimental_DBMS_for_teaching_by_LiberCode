# ProjoDB 文档中心

欢迎来到ProjoDB文档中心！本目录包含完整的项目文档，涵盖架构设计、模块详解和实验教程。

## 📖 文档快速导航

| 文档 | 说明 | 适用对象 |
|------|------|----------|
| [主README](../README.md) | 项目概览、快速开始、核心模块简介 | 所有用户 |
| [实验指南](tutorials/README.md) | 动手实验教程，从零构建DBMS | 学生、初学者 |
| [模块详解](modules/README.md) | 各核心模块详细设计 | 开发者、贡献者 |
| [API参考](api/README.md) | C++/Python API接口说明 | 应用开发者 |
| [设计方案](../docs/DATABASE_DESIGN.md) | 系统架构与详细设计规范 | 架构师、高级开发者 |

---

## 📁 文档结构

```
docs/
├── README.md                    # 本文件：文档索引
├── DATABASE_DESIGN.md           # 详细设计方案（已有）
├── STORAGE_ENGINE.md            # 存储引擎设计（已有）
│
├── modules/                     # 核心模块详解
│   ├── storage.md              # 存储引擎
│   ├── buffer.md               # LRU缓冲区池
│   ├── parser.md               # SQL解析器
│   ├── wal.md                  # WAL日志系统
│   ├── transaction.md          # 事务管理器
│   ├── executor.md             # 查询执行引擎
│   └── index.md                # B+树索引
│
├── tutorials/                   # 实验教程
│   ├── README.md               # 实验指南总览
│   ├── exp1_buffer.md          # 实验1：缓冲区池分析
│   ├── exp2_allocator.md       # 实验2：页分配器实现
│   ├── exp3_bptree.md          # 实验3：B+树索引实现
│   ├── exp4_wal.md             # 实验4：WAL预写日志
│   ├── exp5_transaction.md     # 实验5：事务管理
│   └── experimental_guide.md   # 综合实验指南（新增）
│
├── api/                        # API参考
│   └── README.md               # C++/Python API
│
└── extensions/                 # 高级扩展项目
    └── README.md               # 扩展想法列表
```

---

## 🎯 学习路径建议

### 路径1：快速上手（1-2小时）
1. 阅读主 [README.md](../README.md)
2. 运行示例代码（`examples/`目录）
3. 执行 [实验指南](tutorials/README.md) 中的快速验证
4. 查阅 [API参考](api/README.md) 开始开发

### 路径2：系统学习（1-2周）
1. 阅读 [实验指南](tutorials/README.md) 的5个核心实验
2. 结合 [模块详解](modules/README.md) 深入理解每个组件
3. 动手实现缺失功能
4. 完成实验报告

### 路径3：深入研究（1月+）
1. 精读 [设计方案](../docs/DATABASE_DESIGN.md)
2. 研究每个模块的底层算法
3. 实现高级功能（MVCC、向量化执行、分布式等）
4. 贡献代码到项目

---

## 🔍 按角色查找文档

### 学生
- 开始：主 [README.md](../README.md)
- 实验： [实验指南](tutorials/README.md)
- 理论： [模块详解](modules/README.md)

### 开发者
- API： [API参考](api/README.md)
- 架构： [设计方案](../docs/DATABASE_DESIGN.md)
- 模块： [模块详解](modules/README.md)

### 研究者
- 扩展： [扩展项目](../docs/extensions/README.md)
- 设计： [设计方案](../docs/DATABASE_DESIGN.md)
- 性能：各模块的性能优化建议

---

## 📊 文档状态

| 文档 | 状态 | 最后更新 |
|------|------|----------|
| 主README | ✅ 完成 | 2024-06-04 |
| 存储引擎模块 | ✅ 完成 | 2024-06-04 |
| 缓冲区池模块 | ✅ 完成 | 2024-06-04 |
| SQL解析器模块 | ✅ 完成 | 2024-06-04 |
| WAL日志模块 | ✅ 完成 | 2024-06-04 |
| 事务管理模块 | ✅ 完成 | 2024-06-04 |
| 查询执行器模块 | ✅ 完成 | 2024-06-04 |
| B+树索引模块 | ✅ 完成 | 2024-06-04 |
| 实验指南 | ✅ 完成 | 2024-06-04 |
| API参考 | ⚠️ 部分 | 需更新 |
| 扩展项目 | ⚠️ 部分 | 需补充 |

---

## 📝 贡献文档

如果你想改进文档：

1. Fork项目
2. 编辑对应Markdown文件
3. 提交Pull Request
4. 遵循文档规范（标题层级、代码块格式等）

**文档规范**：
- 使用中文（项目主要语言）
- 代码示例需可运行
- 添加目录（TOC）便于导航
- 提供实验验证步骤

---

## 🗺️ 核心概念总览

### 数据流图

```
用户SQL
   ↓
SQL解析器 → AST
   ↓
执行器 → 物理计划
   ↓
事务管理器 → 获取锁
   ↓
   ├→ 索引扫描（B+树）
   └→ 表扫描（缓冲区池）
         ↓
     WAL日志（预写）
         ↓
    存储引擎（页读写）
         ↓
    文件系统（磁盘）
```

### 模块依赖关系

```
parser → executor → transaction → storage
                       ↘ index ↗
```

- **parser**：SQL → AST
- **executor**：AST → 结果集（调用transaction和storage）
- **transaction**：ACID、锁管理（调用wal、storage）
- **storage**：页I/O（被buffer、wal、index使用）
- **buffer**：页面缓存（供storage和wal使用）
- **index**：B+树（调用storage）
- **wal**：日志（调用storage）

---

## 🚀 快速开始

**5分钟体验ProjoDB**：

```bash
# 1. 克隆并安装
git clone <repo-url>
cd projo
pip install -r requirements.txt

# 2. 运行示例
python examples/demo_parser.py

# 3. 运行测试
pytest tests/test_buffer.py -v

# 4. 查看文档
# 打开 docs/README.md（本文件）
```

---

## 📞 获取帮助

- **文档问题**：在GitHub Issues中标记`documentation`
- **代码问题**：标记`bug`
- **功能请求**：标记`enhancement`
- **讨论区**：GitHub Discussions

---

**祝你学习愉快！** 🎓

探索数据库系统的奥秘，从这里开始。
