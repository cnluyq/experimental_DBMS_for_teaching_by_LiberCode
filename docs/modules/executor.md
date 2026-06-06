# 查询执行引擎模块详解

## 目录
- [概述](#概述)
- [火山模型](#火山模型)
- [执行计划](#执行计划)
  - [逻辑计划](#逻辑计划)
  - [物理计划](#物理计划)
- [核心运算符](#核心运算符)
- [表达式求值](#表达式求值)
- [执行上下文](#执行上下文)
- [优化器扩展](#优化器扩展)
- [实验项目](#实验项目)
- [常见问题](#常见问题)

---

## 概述

查询执行引擎负责将SQL语句转换为结果集。它接收AST或物理计划，逐行产生结果。

### 执行流程

```
SQL文本
  ↓
Parser → AST
  ↓
Optimizer → 物理计划（PlanNode）
  ↓
Executor → 迭代器，产生Row
  ↓
ResultSet → 返回给客户端
```

### 设计选择：火山模型（Volcano）

**迭代器接口**：
```python
class Operator:
    def open(self): pass      # 初始化
    def next(self) -> Row:    # 下一行
        raise StopIteration   # 结束
    def close(self): pass     # 清理
```

**优点**：
- 流水线执行：算子之间不物化中间结果
- 内存友好：一次处理一行
- 简单直观

**缺点**：
- 函数调用开销大（每行一次）
- 难以向量化优化

---

## 火山模型

### 核心接口

```python
class Operator(ABC):
    """算子基类"""

    @abstractmethod
    def open(self, context: ExecutionContext):
        """打开算子，初始化状态"""

    @abstractmethod
    def next(self) -> Optional[Tuple]:
        """返回下一行，None表示结束"""

    @abstractmethod
    def close(self):
        """关闭算子，释放资源"""

    def __iter__(self):
        self.open(self.context)
        return self

    def __next__(self):
        row = self.next()
        if row is None:
            raise StopIteration
        return row
```

### 数据流

```
SeqScan("users")
    ↓ 迭代每行
Filter(age > 18)
    ↓ 过滤
Project(name, age)
    ↓ 投影
→ 结果
```

---

## 执行计划

### 逻辑计划（Logical Plan）

**表示**：关系代数树
```
Project(name, age)
   ↓
Filter(age > 18)
   ↓
SeqScan(users)
```

**节点类型**：
- `LogicalScanNode(table)`
- `LogicalFilterNode(condition, child)`
- `LogicalProjectNode(columns, child)`
- `LogicalJoinNode(left, right, condition)`

---

### 物理计划（Physical Plan）

**表示**：具体实现节点
```
SeqScanOperator(table, buffer_pool)
    ↓
FilterOperator(expr, buffer_pool)
    ↓
ProjectOperator(columns, buffer_pool)
```

**节点类型**（ProjoDB）：

| 算子 | 对应SQL | 说明 |
|------|---------|------|
| `SeqScanOperator` | `SELECT * FROM table` | 全表扫描 |
| `IndexScanOperator` | `SELECT ... WHERE indexed_col = ?` | 索引扫描 |
| `FilterOperator` | `WHERE`条件 | 谓词过滤 |
| `ProjectOperator` | `SELECT col1, col2` | 列投影 |
| `NestedLoopJoinOperator` | `FROM t1, t2` | 嵌套循环连接 |

---

## 核心运算符

### 1. SeqScanOperator（表扫描）

```python
class SeqScanOperator(Operator):
    """顺序扫描表"""

    def __init__(self, table_name: str, context: ExecutionContext):
        self.table_name = table_name
        self.context = context
        self.heap_file = None
        self.record_manager = None
        self.iterator = None

    def open(self, context):
        # 获取表的存储管理器
        self.record_manager = context.table_manager.get_record_manager(self.table_name)
        self.iterator = self.record_manager.scan()  # 返回所有record_id的迭代器

    def next(self) -> Optional[Tuple]:
        """返回下一行（已解码的tuple）"""
        try:
            record_id = next(self.iterator)
            # 从缓冲区读取数据页
            record = self.record_manager.read_record(record_id)
            return record  # tuple格式：(col1_val, col2_val, ...)
        except StopIteration:
            return None

    def close(self):
        self.iterator = None
```

---

### 2. FilterOperator（过滤）

```python
class FilterOperator(Operator):
    """条件过滤"""

    def __init__(self, condition: Expression, child: Operator, context: ExecutionContext):
        self.condition = condition
        self.child = child
        self.context = context

    def open(self, context):
        self.child.open(context)

    def next(self) -> Optional[Tuple]:
        """从child获取行，应用谓词，返回符合条件的行"""
        while True:
            row = self.child.next()
            if row is None:
                return None
            # 求值条件表达式
            result = Evaluator.evaluate(self.condition, row, self.context.schema)
            if result:  # 为True或非零
                return row

    def close(self):
        self.child.close()
```

---

### 3. ProjectOperator（投影）

```python
class ProjectOperator(Operator):
    """列投影"""

    def __init__(self, columns: List[str], child: Operator, context: ExecutionContext):
        self.columns = columns  # 需要保留的列名
        self.child = child
        self.context = context
        self.column_indices = None  # 列名到child输出索引的映射

    def open(self, context):
        self.child.open(context)
        # 建立列索引映射
        child_schema = self.child.get_schema()  # [col1, col2, ...]
        self.column_indices = [child_schema.index(col) for col in self.columns]

    def next(self) -> Optional[Tuple]:
        row = self.child.next()
        if row is None:
            return None
        # 只选择特定列
        return tuple(row[i] for i in self.column_indices)

    def close(self):
        self.child.close()
```

---

### 4. IndexScanOperator（索引扫描）

```python
class IndexScanOperator(Operator):
    """使用索引查找"""

    def __init__(self, table_name: str, index_name: str,
                 key_value: Any, context: ExecutionContext):
        self.table_name = table_name
        self.index_name = index_name
        self.key_value = key_value
        self.context = context

    def open(self, context):
        self.index = context.index_manager.get_index(self.table_name, self.index_name)
        # 查找匹配的record_id列表
        self.record_ids = self.index.find(self.key_value)
        self.pos = 0

    def next(self) -> Optional[Tuple]:
        if self.pos >= len(self.record_ids):
            return None
        record_id = self.record_ids[self.pos]
        self.pos += 1
        # 读取记录
        record = self.context.table_manager.read_record(self.table_name, record_id)
        return record
```

---

### 5. NestedLoopJoinOperator（嵌套循环连接）

```python
class NestedLoopJoinOperator(Operator):
    """嵌套循环连接（简单实现）"""

    def __init__(self, left: Operator, right: Operator,
                 condition: Expression, context: ExecutionContext):
        self.left = left
        self.right = right
        self.condition = condition
        self.context = context
        self.left_done = False
        self.left_cache = []  # 缓存左表所有行
        self.right_iter = None

    def open(self, context):
        self.left.open(context)
        # 缓存整个左表（小表优化）
        while True:
            row = self.left.next()
            if row is None:
                break
            self.left_cache.append(row)
        self.left.close()

        self.right.open(context)
        self.right_iter = iter(self.right)

    def next(self) -> Optional[Tuple]:
        """暴力枚举：for each left_row: for each right_row: if match yield"""
        while True:
            try:
                right_row = next(self.right_iter)
                for left_row in self.left_cache:
                    combined = left_row + right_row
                    if Evaluator.evaluate(self.condition, combined, self.context.schema):
                        return combined
            except StopIteration:
                # 右表耗尽，但左表可能还有未连接的？已缓存所有左表，说明完成
                return None

    def close(self):
        self.right.close()
```

---

## 表达式求值

### Evaluator类

```python
class Evaluator:
    """表达式求值器"""

    @staticmethod
    def evaluate(expr: Expression, row: Tuple, schema: List[ColumnDef]) -> Any:
        """
        Args:
            expr: 表达式节点
            row: 当前行数据（按schema顺序）
            schema: 表结构定义

        Returns:
            求值结果（布尔、数字、字符串等）
        """
        if isinstance(expr, ColumnNode):
            col_idx = schema.index(expr.column_name)
            return row[col_idx]

        elif isinstance(expr, ValueNode):
            return expr.value

        elif isinstance(expr, BinaryOpNode):
            left_val = Evaluator.evaluate(expr.left, row, schema)
            right_val = Evaluator.evaluate(expr.right, row, schema)

            if expr.op == 'AND':
                return bool(left_val) and bool(right_val)
            elif expr.op == 'OR':
                return bool(left_val) or bool(right_val)
            elif expr.op == '=':
                return left_val == right_val
            elif expr.op == '!=':
                return left_val != right_val
            elif expr.op == '>':
                return left_val > right_val
            elif expr.op == '<':
                return left_val < right_val
            elif expr.op == '>=':
                return left_val >= right_val
            elif expr.op == '<=':
                return left_val <= right_val
            else:
                raise EvaluationError(f"Unknown operator: {expr.op}")

        elif isinstance(expr, NullNode):
            return None

        else:
            raise EvaluationError(f"Unknown expression type: {type(expr)}")
```

**注意**：类型检查和NULL处理需要完善。

---

## 执行上下文

```python
class ExecutionContext:
    """执行上下文，传递共享资源"""

    def __init__(self, txn_id: int, buffer_pool, index_manager,
                 table_manager, wal_manager):
        self.txn_id = txn_id
        self.buffer_pool = buffer_pool
        self.index_manager = index_manager
        self.table_manager = table_manager
        self.wal_manager = wal_manager

    def get_table_schema(self, table_name: str) -> List[ColumnDef]:
        """获取表结构"""
        return self.table_manager.get_schema(table_name)
```

---

## 优化器扩展

当前ProjoDB**没有物理优化器**，直接使用逻辑AST生成物理算子。

### 简单的规则优化

```python
class SimpleOptimizer:
    """简单优化器"""

    def optimize(self, ast: ASTNode) -> PhysicalPlan:
        """AST → PhysicalPlan"""

        if isinstance(ast, SelectNode):
            # 从后往前构建算子
            child = self._plan_scan(ast.table_name)

            # WHERE → Filter
            if ast.where_clause:
                child = FilterOperator(ast.where_clause, child, context)

            # SELECT → Project
            if ast.columns != ['*']:
                child = ProjectOperator(ast.columns, child, context)

            return child

    def _plan_scan(self, table_name: str) -> Operator:
        """选择扫描方式（索引 vs 顺序）"""
        # 检查 WHERE 中是否有等值条件匹配索引
        # 如果有，使用IndexScanOperator
        # 否则使用SeqScanOperator
        return SeqScanOperator(table_name, self.context)
```

---

## 实验项目

### 实验1：实现简单执行器

**目标**：完成`Executor`类，支持`SELECT * FROM table`。

**步骤**：
1. 创建`Executor`类，接收AST
2. 实现`SeqScanOperator`
3. 不求值WHERE/PROJECT，直接返回所有行
4. 测试：`SELECT * FROM users` 应返回所有记录

---

### 实验2：实现FilterOperator

**目标**：支持WHERE条件。

**步骤**：
1. 实现`FilterOperator`
2. 实现`Evaluator.evaluate()`
3. 支持`=, !=, >, <, >=, <=, AND, OR`
4. 测试：`SELECT * FROM users WHERE age > 18`

---

### 实验3：实现ProjectOperator

**目标**：支持选择特定列。

**步骤**：
1. 实现`ProjectOperator`
2. 处理列顺序
3. 处理`SELECT *`（所有列）
4. 测试：`SELECT name, age FROM users`

---

### 实验4：支持INSERT语句

**目标**：实现插入操作。

**步骤**：
1. 在`Executor`添加`execute_insert(ast)`
2. 调用存储引擎或记录管理器插入记录
3. 记录WAL日志（自动化，WAL在存储层）
4. 测试：`INSERT INTO users VALUES (1, 'Alice', 25)`

---

### 实验5：实现嵌套循环连接（可选）

**目标**：支持多表连接（FROM多个表）。

**步骤**：
1. 实现`NestedLoopJoinOperator`
2. 在Optimizer识别多表FROM
3. 生成连接计划
4. 测试：`SELECT * FROM users, orders WHERE users.id = orders.user_id`

---

## 常见问题

### Q1: 为什么不用向量化执行？

**A**：火山模型每行调用一次函数，开销大。向量化执行（如Apache Arrow）批量处理（一次1024行），利用SIMD指令。适合OLAP，但教学用火山模型更简单。

---

### Q2: 如何实现真正的管道化（pipeline）？

**A**：当前实现算子间通过`next()`拉取。还可以：
- **推模型（Push）**：生产者调用`consume(row)`推送
- **混合**：大结果用拉，小中间结果用推

---

### Q3: 内存管理：中间结果物化吗？

**A**：火山模型**不物化**中间结果（除了NestedLoopJoin可能缓存小表）。物化（如HashJoin）需要更多内存，但减少重复计算。

---

### Q4: 错误处理：算子失败怎么办？

**A**： Propagate异常到上层，最终中断整个查询。
```python
def next(self):
    try:
        return self.child.next()
    except StorageError as e:
        raise QueryExecutionError("Failed to read from child") from e
```

---

## 参考代码

- `src/executor/executor.py`：主执行器
- `src/executor/evaluator.py`：表达式求值
- `src/executor/plan.py`：计划节点定义
- `src/executor/context.py`：执行上下文

---

**下一步**：学习 [B+树索引](index.md) 或继续 [实验5：查询执行器](docs/tutorials/exp6_query_engine.md)（待编写）
