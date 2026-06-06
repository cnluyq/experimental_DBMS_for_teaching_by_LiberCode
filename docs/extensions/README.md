# 扩展项目建议

完成核心模块后，以下高级项目可进一步深入学习数据库系统。

## 🎯 中级扩展

### 1. 事务管理器 (Transaction Manager)

**目标**：实现完整的ACID事务支持。

**子任务**：
- 事务状态管理（active、committing、aborting、committed、aborted）
- 并发控制：锁管理器（共享锁、排他锁、锁升级）
- 死锁检测和预防（等待图、超时）
- 两阶段锁协议（2PL）
- 隔离级别：READ COMMITTED、REPEATABLE READ、SERIALIZABLE

**挑战**：
- 锁粒度选择（行级 vs 页级）
- 死锁循环检测算法
- 锁升级策略避免开销

**预期成果**：
```sql
BEGIN;
UPDATE users SET balance = balance - 100 WHERE id = 1;
UPDATE accounts SET balance = balance + 100 WHERE id = 2;
COMMIT;  -- 原子性保证
```

---

### 2. 完整WAL实现

**目标**：崩溃恢复机制。

**子任务**：
- 日志记录格式设计（物理日志、逻辑日志）
- 日志管理：日志文件轮转、检查点（Checkpoint）
- 恢复算法：分析、重做、撤销（ARIES）
- 日志组提交（Group Commit）优化

**挑战**：
- 日志与数据页的LSN同步
- 检查点一致性保证
- 长事务的撤销链管理

**预期成果**：
```
[场景] 数据库在COMMIT后崩溃
→ 恢复时，使用WAL重做已提交但未刷盘的事务
→ 撤销未提交事务的修改
```

---

### 3. 查询执行引擎

**目标**：将SQL解析的AST转换为执行计划并执行。

**子任务**：
- 物理算子设计：TableScan、Select、Project、Join、Aggregate
- 火山模型（Volcano Iterator）或向量化执行
- 查询优化器：基于代价的优化（CBO）
- 表达式求值器

**物理算子系统结构**：
```python
class Operator(ABC):
    def open(self): pass
    def next(self) -> Optional[Record]: pass
    def close(self): pass

class TableScan(Operator):
    def __init__(self, table_name, filter=None): ...
class Selection(Operator):
    def __init__(self, child, predicate): ...
class Projection(Operator):
    def __init__(self, child, columns): ...
class HashJoin(Operator):
    def __init__(self, left, right, left_col, right_col): ...
```

**预期成果**：
```sql
SELECT name, SUM(salary)
FROM employees WHERE dept = 'IT'
GROUP BY name
HAVING SUM(salary) > 50000;
-- 能正确执行并返回结果
```

---

## 🚀 高级扩展

### 4. MVCC多版本并发控制

**目标**：替代锁机制，实现无锁并发。

**核心概念**：
- 事务可见性：每个记录有创建事务ID和删除事务ID
- 快照隔离（Snapshot Isolation）
- 版本清理（Vacuum）：回收旧版本
- 写偏斜（Write Skew）检测

**实现思路**：
```cpp
struct RecordVersion {
    RecordID rec_id;
    txn_id_t create_txn;     // 创建此版本的事务
    txn_id_t delete_txn;     // 删除此版本的事务（0表示未删除）
    std::vector<char> data;  // 实际数据
};

// 读操作：只读 commit_timestamp <= snapshot 的记录
// 写操作：创建新版本，设置delete_txn
```

**挑战**：
- 版本链管理
- 垃圾回收（避免过早删除活跃事务需要的版本）
- 索引维护（MVCC下索引如何处理）

---

### 5. 向量化与SIMD优化

**目标**：充分利用现代CPU特性。

**优化方向**：
- 向量化表达式求值：一次处理一批记录
- SIMD指令：AVX2/AVX-512加速过滤、聚合
- 预取（Prefetching）：减少缓存未命中
- NUMA感知：绑定线程到CPU核心

**示例**（向量化SELECT）：
```
传统：for each row: evaluate predicate(row)
向量化：chunk = load 16 rows; mask = evaluate(chunk); filter(chunk, mask)
```

---

## 🌐 系统级扩展

### 6. 客户端-服务器架构

**目标**：支持多客户端网络访问。

**设计**：
- 网络协议：简单的TCP或PostgreSQL兼容协议
- 连接池：管理客户端连接
- 查询调度：公平调度多查询
- 认证和权限

**架构图**：
```
[Client App] ↔ [Client Lib] ↔ [DB Server]
                              ├── Connection Pool
                              ├── Query Scheduler
                              ├── Storage Engine
                              └── Cache (shared)
```

---

### 7. 列式存储

**目标**：OLAP场景的列存格式。

**与行存对比**：
| 维度 | 行存（Row） | 列存（Column） |
|------|------------|----------------|
| 插入 | 快 | 慢 |
| 点查询 | 快 | 慢 |
| 聚合查询 | 慢 | 极快 |
| 压缩率 | 低 | 高 |
| 适用场景 | OLTP | OLAP |

**实现**：
```
Column File:
  Col1: [v1, v2, v3, ...]  (连续存储)
  Col2: [v1, v2, v3, ...]
  Col3: [v1, v2, v3, ...]
```

**挑战**：更新和删除需要位图或Delta存储。

---

### 8. 分布式SQL

**目标**：多机分片（Sharding）和查询。

**核心组件**：
- 分片策略：哈希、范围、列表
- 分布式查询：将SQL分解到各分片、结果合并
- 事务协调：2PC（两阶段提交）
- 故障转移：副本（Replication）

**架构**：
```
       [Coordinator]
           /  |  \\
          /   |   \\
  [Shard1] [Shard2] [Shard3]
```

**示例SQL**：
```sql
-- 用户表按user_id哈希分片
SELECT * FROM users WHERE user_id = 12345;
→ 路由到 Shard(user_id % 3)

SELECT * FROM users WHERE age > 18;
→ 广播到所有分片，合并结果
```

---

## 🔬 实验性功能

### 9. 机器学习索引

**想法**：用神经网络预测键位置。

**参考**：Google的**learned index**论文。
- 用训练好的模型替代B+树搜索
- 预测模型：键 → 位置（近似）
- 需要二级精确查找（如二分）

**潜在优势**：
- 模型比树小（适合内存）
- 预测O(1) vs 搜索O(log n)

---

### 10. 时序数据库功能

**目标**：支持时间序列数据。

**特性**：
- 按时间分区（Time Partitioning）
- 时间索引：时间到主键的映射
- 降采样（Downsampling）：自动聚合
-  retention策略：自动删除旧数据

**适用场景**：IoT、监控日志、金融行情。

---

### 11. 图数据库支持

**目标**：存储和查询图结构。

**实现**：
- 顶点和边表
- 属性图模型
- 图遍历：BFS、DFS
- 图查询语言：Cypher-like或SPARQL

**示例**：
```cypher
MATCH (u:User)-[:FRIEND]->(f)-[:LIKES]->(m:Movie)
WHERE u.name = 'Alice' AND m.genre = 'Sci-Fi'
RETURN m.title;
```

---

### 12. 向量数据库

**目标**：AI应用的相似度搜索。

**核心**：
- 向量存储：浮点数组
- 索引：HNSW、IVF、LSH等近似最近邻（ANN）
- 距离度量：L2、余弦相似度、内积

**示例**：
```sql
CREATE VECTOR INDEX img_idx ON images (embedding) USING HNSW;
SELECT * FROM images WHERE embedding NEAR [0.1, 0.2, ...] LIMIT 10;
```

---

## 📈 性能优化项目

### 13. 混合存储引擎

**目标**：内存+磁盘分层。

**策略**：
- 热数据：存储在内存表（跳表、哈希）
- 冷数据：在磁盘B+树
- 自动迁移：LRU或基于访问频率

---

### 14. 并行查询执行

**目标**：多线程并行执行单个查询。

**并行度**：
- 算子级并行：不同算子在不同线程
- 数据级并行：分区并行扫描、并行Join
- Pipeline并行：流水线执行减少中间结果落盘

---

### 15. 自适应自调优

**目标**：系统自动优化。

**可调参数**：
- 缓冲区大小
- 索引选择（自动创建/删除索引）
- 查询计划选择

**方法**：强化学习或基于历史统计反馈调整。

---

## 📚 研究型扩展

### 16. LSM树存储

**目标**：写优化存储（替代B+树）。

**LSM-Tree组件**：
- 内存 MemTable（跳过列表）
- 持久化 SSTable（排序字符串表）
- 压缩（Compaction）合并小文件

**适用**：高写入场景（如Kafka、Cassandra）。

---

### 17. 区块链式不可变存储

**目标**：数据只追加、历史可验证。

**技术**：
- Merkle树验证完整性
- 时间戳服务
- 可验证查询（Proof of Inclusion）

---

## 🛠️ 工具与生态

### 18. 监控与分析工具

- 性能指标导出（Prometheus格式）
- 慢查询日志
- 执行计划可视化
- 存储碎片分析

---

### 19. 备份与恢复

- 全量备份（快照）
- 增量备份（基于WAL）
- 时间点恢复（PITR）
- 跨数据中心复制

---

### 20. 文件格式兼容

- **Parquet/ORC**：支持读写列存格式
- **Avro/JSON**：半结构化数据
- **MySQL/PG Dump**：兼容性导入

---

## 📝 项目模板

每个扩展项目建议包含：

```
proj-name/
├── README.md              # 项目介绍
├── design.md              # 设计方案
├── src/                   # 代码实现
├── tests/                 # 单元测试
├── benchmarks/            # 性能测试
├── docs/                  # 详细文档
└── report.pdf            # 最终报告
```

---

## 🔗 参考资源

- **开源DBMS**：PostgreSQL、MySQL、SQLite、TiDB、CockroachDB
- **论文**：
  - The Design and Implementation of InnoDB
  - Spanner: Google's Globally-Distributed Database
  - The Log-Structured Merge-Tree (LSM-Tree)
  - ARIES: A Transaction Recovery Method
- **课程**：
  - CMU 15-721 Advanced Database Systems
  - Stanford CS346: Database System Implementation

---

## 🎓 毕业项目建议

组合多个扩展，完成**全功能分布式DBMS**：

```
核心引擎 + B+树 + WAL + 事务 + 简单SQL
    ↓
添加：MVCC + 向量化执行
    ↓
添加：客户端-服务器 + 复制
    ↓
添加：分片 + 分布式查询
    ↓
添加：监控 + 备份恢复
    ↓
完成：可生产使用的教学级DBMS！
```

---

**你也可以自创项目**：发现需求 → 设计 → 实现 → 测试 → 文档。

祝你实验愉快！✨