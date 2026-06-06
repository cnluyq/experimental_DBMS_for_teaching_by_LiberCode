# SQL解析器模块详解

## 目录
- [概述](#概述)
- [处理流程](#处理流程)
- [词法分析（Tokenizer）](#词法分析tokenizer)
- [语法分析（Parser）](#语法分析parser)
- [抽象语法树（AST）](#抽象语法树ast)
- [错误处理](#错误处理)
- [SQL支持范围](#sql支持范围)
- [实验项目](#实验项目)
- [常见问题](#常见问题)

---

## 概述

SQL解析器将SQL字符串转换为**抽象语法树（AST）**，供后续执行器使用。ProjoDB采用**递归下降**解析方法，配合自定义词法分析器。

### 为什么自写解析器？

1. **教学目的**：理解编译原理基础（词法、语法分析）
2. **精简可控**：只支持教学SQL子集，避免复杂语法
3. **调试友好**：清晰的错误位置和AST结构
4. **易于扩展**：学生可逐步添加新语法

### 输入输出

```
"SELECT name, age FROM users WHERE age > 18"
        ↓
[Token(SELECT), Token(IDENT, name), ...]
        ↓
SelectNode(columns=['name','age'], table='users', where=BinaryOp('>', ...))
```

---

## 处理流程

```
SQL字符串
   ↓
[Tokenizer] → Token流
   ↓
[Parser] → AST
   ↓
[Optimizer] → 物理计划（可选）
   ↓
[Executor] → 结果集
```

---

## 词法分析（Tokenizer）

### 功能

将原始SQL字符串分解为**Token序列**。

### Token类型

| 类型 | 示例 | 说明 |
|------|------|------|
| `KEYWORD` | `SELECT`, `FROM`, `WHERE` | SQL关键字（大小写不敏感） |
| `IDENTIFIER` | `users`, `name`, `age` | 标识符（表名、列名） |
| `INTEGER` | `123`, `-45` | 整数 |
| `FLOAT` | `3.14`, `-0.5` | 浮点数 |
| `STRING` | `'hello'`, `'world'` | 字符串（单引号） |
| `OPERATOR` | `=`, `!=`, `>`, `<`, `>=`, `<=` | 运算符 |
| `LPAREN` | `(` | 左括号 |
| `RPAREN` | `)` | 右括号 |
| `COMMA` | `,` | 逗号 |
| `SEMICOLON` | `;` | 分号（语句结束） |
| `EOF` | (无) | 文件结束 |

### Token数据结构

```python
class Token:
    type: str      # 类型名
    value: str     # 原始字符串
    line: int      # 行号（错误报告）
    column: int    # 列号（错误报告）

    def __repr__(self):
        return f"Token({self.type}, '{self.value}')"
```

### 词法规则

**标识符**：
```
规则：以字母或下划线开头，后跟字母、数字、下划线
正则：^[a-zA-Z_][a-zA-Z0-9_]*$
示例：users, user_name, _temp1
```

**关键字**（大小写不敏感）：
```
SELECT, FROM, WHERE, INSERT, INTO, VALUES,
UPDATE, SET, DELETE, CREATE, DROP, TABLE,
BEGIN, COMMIT, ROLLBACK, AND, OR, NOT, NULL
```

**字符串**：
```
以单引号括起，支持转义'\''
示例：'hello', 'it''s', 'line1\nline2'
```

**数字**：
```
整数：[-]?[0-9]+
浮点数：[-]?[0-9]+(\.[0-9]*)?  (暂时不支持科学计数法)
```

**运算符**：
```
=  !=  >  <  >=  <=
```

### 状态机实现

```python
class Tokenizer:
    def __init__(self, sql: str):
        self.sql = sql
        self.pos = 0
        self.line = 1
        self.column = 1

    def tokenize(self) -> List[Token]:
        tokens = []
        while self.pos < len(self.sql):
            ch = self.sql[self.pos]

            if ch.isspace():
                self._consume_whitespace()
            elif ch.isalpha() or ch == '_':
                tokens.append(self._read_identifier())
            elif ch.isdigit() or (ch == '-' and self._peek().isdigit()):
                tokens.append(self._read_number())
            elif ch == "'":
                tokens.append(self._read_string())
            elif ch in ('=', '!', '<', '>'):
                tokens.append(self._read_operator())
            elif ch in ('(', ')', ',', ';'):
                tokens.append(self._read_single_char(ch))
            else:
                raise TokenizerError(f"Unknown character: {ch}")

        tokens.append(Token('EOF', '', self.line, self.column))
        return tokens

    def _read_identifier(self) -> Token:
        start = self.pos
        while self.pos < len(self.sql) and (
            self.sql[self.pos].isalnum() or self.sql[self.pos] == '_'
        ):
            self.pos += 1
        value = self.sql[start:self.pos]
        # 检查是否为关键字
        if value.upper() in KEYWORDS:
            return Token('KEYWORD', value.upper(), self.line, self.column)
        return Token('IDENTIFIER', value, self.line, self.column)
```

---

## 语法分析（Parser）

### 方法

**递归下降**（Recursive Descent）：每个非终结符对应一个`parse_*()`方法。

### 语法规则（BNF简化版）

```
statement    ::= select_stmt
               | insert_stmt
               | update_stmt
               | delete_stmt
               | create_table_stmt
               | drop_table_stmt
               | begin_stmt
               | commit_stmt
               | rollback_stmt

select_stmt  ::= SELECT column_list FROMIDENTIFIER [WHERE expr]
insert_stmt  ::= INSERT INTO IDENTIFIER [(col_list)] VALUES (val_list)
update_stmt  ::= UPDATE IDENTIFIER SET set_list [WHERE expr]
delete_stmt  ::= DELETE FROM IDENTIFIER [WHERE expr]
create_table ::= CREATE TABLE IDENTIFIER '(' column_def_list ')'
drop_table   ::= DROP TABLE IDENTIFIER

column_list  ::= '*' | IDENTIFIER (',' IDENTIFIER)*
col_list     ::= IDENTIFIER (',' IDENTIFIER)*
column_def   ::= IDENTIFIER type [PRIMARY KEY]
column_def_list ::= column_def (',' column_def)*
set_list     ::= IDENTIFIER '=' expr (',' IDENTIFIER '=' expr)*
val_list     ::= expr (',' expr)*

expr         ::= or_expr
or_expr      ::= and_expr ('OR' and_expr)*
and_expr     ::= cmp_expr ('AND' cmp_expr)*
cmp_expr     ::= primary (comp_op primary)?
primary      ::= IDENTIFIER | INTEGER | FLOAT | STRING | NULL | '(' expr ')'
comp_op      ::= '=' | '!=' | '>' | '<' | '>=' | '<='
```

### 优先级处理

- `OR` 优先级最低
- `AND` 中等
- 比较运算符 `=, !=, >, <, >=, <=` 最高

**示例**：
```
age > 18 AND status = 'active' OR admin = true
     ↓
OR( AND(>(age,18), =(status,'active')), =(admin,true) )
```

### 递归下降实现

```python
class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = -1
        self.current_token = None
        self.advance()

    def advance(self):
        self.pos += 1
        if self.pos < len(self.tokens):
            self.current_token = self.tokens[self.pos]
        else:
            self.current_token = None

    def expect(self, token_type, token_value=None):
        """消费并验证当前token"""
        if self.current_token is None:
            raise ParserError("Unexpected end of input")

        if self.current_token.type != token_type:
            raise ParserError(f"Expected {token_type} but got {self.current_token.type}")

        if token_value and self.current_token.value.upper() != token_value:
            raise ParserError(f"Expected '{token_value}' but got '{self.current_token.value}'")

        token = self.current_token
        self.advance()
        return token

    def parse(self):
        """入口点"""
        if self.current_token is None:
            raise ParserError("Empty input")

        # 根据首个token决定语句类型
        token_type = self.current_token.type
        if token_type == 'SELECT':
            return self.parse_select()
        elif token_type == 'INSERT':
            return self.parse_insert()
        # ... 其他语句
        else:
            raise ParserError(f"Unsupported statement: {token_type}")

    def parse_select(self):
        """解析SELECT语句"""
        self.expect('KEYWORD', 'SELECT')
        columns = self.parse_column_list()
        self.expect('KEYWORD', 'FROM')
        table_name = self.expect('IDENTIFIER').value
        where_clause = None
        if self.current_token and self.current_token.type == 'KEYWORD' and \
           self.current_token.value.upper() == 'WHERE':
            self.advance()
            where_clause = self.parse_expr()
        return SelectNode(columns, table_name, where_clause)

    def parse_column_list(self) -> List[str]:
        """解析列列表：'*' 或 col1, col2, ..."""
        if self.current_token.value == '*':
            self.advance()
            return ['*']
        columns = []
        while True:
            columns.append(self.expect('IDENTIFIER').value)
            if self.current_token and self.current_token.type == 'COMMA':
                self.advance()
                continue
            break
        return columns

    def parse_expr(self) -> Expression:
        """解析表达式（处理优先级）"""
        return self.parse_or()

    def parse_or(self) -> Expression:
        """or_expr → and_expr ('OR' and_expr)*"""
        node = self.parse_and()
        while self.current_token and self.current_token.type == 'KEYWORD' and \
              self.current_token.value.upper() == 'OR':
            self.advance()
            right = self.parse_and()
            node = BinaryOpNode(node, 'OR', right)
        return node

    def parse_and(self) -> Expression:
        """and_expr → cmp_expr ('AND' cmp_expr)*"""
        node = self.parse_cmp()
        while self.current_token and self.current_token.type == 'KEYWORD' and \
              self.current_token.value.upper() == 'AND':
            self.advance()
            right = self.parse_cmp()
            node = BinaryOpNode(node, 'AND', right)
        return node

    def parse_cmp(self) -> Expression:
        """cmp_expr → primary (comp_op primary)?"""
        node = self.parse_primary()
        if self.current_token and self.current_token.type == 'OPERATOR':
            op = self.current_token.value
            # 标准化运算符（!= 可能被读成!和=）
            if op == '!=':
                self.advance()
            elif op in ('=', '>', '<', '>=', '<='):
                self.advance()
            else:
                return node  # 不是比较运算符

            right = self.parse_primary()
            node = BinaryOpNode(node, op, right)
        return node

    def parse_primary(self) -> Expression:
        """primary → IDENTIFIER | INTEGER | FLOAT | STRING | NULL | '(' expr ')'"""
        token = self.current_token

        if token.type == 'IDENTIFIER':
            self.advance()
            return ColumnNode(token.value)
        elif token.type == 'INTEGER':
            self.advance()
            return ValueNode(int(token.value), 'integer')
        elif token.type == 'FLOAT':
            self.advance()
            return ValueNode(float(token.value), 'float')
        elif token.type == 'STRING':
            self.advance()
            return ValueNode(token.value[1:-1], 'string')  # 去掉引号
        elif token.type == 'KEYWORD' and token.value.upper() == 'NULL':
            self.advance()
            return NullNode()
        elif token.type == 'LPAREN':
            self.advance()
            node = self.parse_expr()
            self.expect('RPAREN')
            return node
        else:
            raise ParserError(f"Unexpected token: {token}")
```

---

## 抽象语法树（AST）

### 设计原则

- **不可变**：一旦创建，AST节点不应修改（方便后续优化）
- **类型安全**：每个节点类型有固定字段
- **可遍历**：提供`accept(visitor)`或直接属性访问

### 节点层级结构

```
ASTNode (基类)
├── Statement (语句)
│   ├── DDL
│   │   ├── CreateTableNode
│   │   └── DropTableNode
│   ├── DML
│   │   ├── SelectNode
│   │   ├── InsertNode
│   │   ├── UpdateNode
│   │   └── DeleteNode
│   └── Transaction
│       ├── BeginNode
│       ├── CommitNode
│       └── RollbackNode
└── Expression (表达式)
    ├── BinaryOpNode
    ├── ColumnNode
    ├── ValueNode
    └── NullNode
```

### 详细定义

#### 语句节点

```python
class ASTNode:
    """基类（可选）"""
    pass

# CREATE TABLE
class CreateTableNode(ASTNode):
    table_name: str
    columns: List[ColumnDef]  # [(name, type, constraints)]

    def __init__(self, table_name, columns):
        self.table_name = table_name
        self.columns = columns

# DROP TABLE
class DropTableNode(ASTNode):
    table_name: str

# SELECT
class SelectNode(ASTNode):
    columns: List[str]        # ['*'] 或 ['col1', 'col2']
    table_name: str
    where_clause: Optional[Expression]

# INSERT
class InsertNode(ASTNode):
    table_name: str
    columns: List[str]        # 可选，None表示全部列
    values: List[Expression]

# UPDATE
class UpdateNode(ASTNode):
    table_name: str
    set_clauses: List[Tuple[str, Expression]]  # [(col, expr), ...]
    where_clause: Optional[Expression]

# DELETE
class DeleteNode(ASTNode):
    table_name: str
    where_clause: Optional[Expression]

# 事务
class BeginNode(ASTNode): pass
class CommitNode(ASTNode): pass
class RollbackNode(ASTNode): pass
```

#### 表达式节点

```python
class Expression:
    """表达式基类"""
    pass

# 二元运算
class BinaryOpNode(Expression):
    left: Expression
    op: str            # '=', '!=', '>', '<', '>=', '<=', 'AND', 'OR'
    right: Expression

# 列引用
class ColumnNode(Expression):
    column_name: str

# 常量
class ValueNode(Expression):
    value: Any        # 实际值（int, float, str）
    value_type: str   # 'integer', 'float', 'string'

# NULL
class NullNode(Expression):
    pass
```

#### 列定义（CREATE TABLE用）

```python
class ColumnDef:
    name: str
    data_type: str    # 'INT', 'VARCHAR(50)', 'BOOLEAN', 'FLOAT'
    constraints: List[str]  # ['PRIMARY KEY', 'NOT NULL']
```

### 示例AST

**SQL**：
```sql
SELECT name, age FROM users WHERE age > 18 AND status = 'active'
```

**AST**：
```python
SelectNode(
    columns=['name', 'age'],
    table_name='users',
    where_clause=BinaryOpNode(
        op='AND',
        left=BinaryOpNode(
            op='>',
            left=ColumnNode('age'),
            right=ValueNode(18, 'integer')
        ),
        right=BinaryOpNode(
            op='=',
            left=ColumnNode('status'),
            right=ValueNode('active', 'string')
        )
    )
)
```

**打印树**：
```python
def print_ast(node, indent=0):
    prefix = "  " * indent
    if isinstance(node, BinaryOpNode):
        print(f"{prefix}BinaryOp: {node.op}")
        print_ast(node.left, indent+1)
        print_ast(node.right, indent+1)
    elif isinstance(node, ColumnNode):
        print(f"{prefix}Column: {node.column_name}")
    elif isinstance(node, ValueNode):
        print(f"{prefix}Value: {node.value}")
    else:
        print(f"{prefix}{type(node).__name__}")
```

---

## 错误处理

### 错误类型

```python
class TokenizerError(Exception):
    """词法错误"""
    pass

class ParserError(Exception):
    """语法错误"""
    pass
```

### 错误信息格式

```
第 [行] 行, 列 [列]: [错误描述]
```

**示例**：
```
第 2 行, 列 15: 期望 IDENTIFIER 但得到 WHERE
第 1 行, 列 30: 未闭合的字符串字面量
```

### 实现技巧

```python
def expect(self, token_type, token_value=None):
    if self.current_token is None:
        raise ParserError(
            f"第 {self.line} 行, 列 {self.column}: "
            f"期望 {token_type} 但已到文件末尾"
        )
```

---

## SQL支持范围

### ✅ 已支持

**DDL**：
```sql
CREATE TABLE table_name (
    col1 TYPE [PRIMARY KEY],
    col2 TYPE,
    ...
);
-- 支持类型：INT, VARCHAR(n), BOOLEAN, FLOAT, DATE
-- 约束：PRIMARY KEY (单列)

DROP TABLE table_name;
```

**DML**：
```sql
SELECT col1, col2 FROM table_name [WHERE condition];
-- 支持通配符：SELECT *

INSERT INTO table_name [(col1, col2, ...)] VALUES (val1, val2, ...);

UPDATE table_name SET col=expr, ... [WHERE condition];

DELETE FROM table_name [WHERE condition];
```

**WHERE条件**：
- 比较运算符：`=, !=, <, <=, >, >=`
- 逻辑运算符：`AND, OR, NOT`
- 操作数：列名、常量（整数、浮点数、字符串、NULL）

**事务**：
```sql
BEGIN;
COMMIT;
ROLLBACK;
```

### ❌ 不支持（未来扩展）

- **聚合函数**：`COUNT()`, `SUM()`, `AVG()`
- **GROUP BY / HAVING**
- **ORDER BY**
- **子查询**（嵌套SELECT）
- **JOIN**（多表连接）
- **DISTINCT**
- **LIMIT / OFFSET**
- **复杂数据类型**（数组、JSON）
- **窗口函数**

---

## 实验项目

### 实验1：扩展类型系统

**目标**：添加`DATE`类型和日期字面量解析。

**步骤**：
1. 在`tokenizer.py`添加`DATE` token类型
2. 日期格式：`DATE '2024-01-15'` 或 `'2024-01-15'::DATE`
3. 在`parse_primary()`处理日期
4. 创建`DateNode`或扩展`ValueNode`

**测试**：
```python
ast = parse("SELECT * FROM events WHERE event_date > DATE '2024-01-01'")
assert isinstance(ast.where_clause.right, DateNode)
```

---

### 实验2：添加NOT运算符

**目标**：支持`NOT`取反。

**当前**：WHERE只支持AND/OR

**步骤**：
1. 修改BNF：
   ```
   and_expr → not_expr ('AND' not_expr)*
   not_expr → 'NOT' not_expr | cmp_expr
   ```
2. 在`Parser`添加`parse_not()`方法
3. 创建`NotNode(expression)`表达式节点

**测试**：
```sql
SELECT * FROM users WHERE NOT (age < 18 OR banned = true)
```

---

### 实验3：实现简单优化器

**目标**：在Parser和Executor之间添加优化阶段。

**优化规则**：
1. **谓词下推**：将WHERE条件下推到扫描层
2. **列裁剪**：只读取需要的列（而非`SELECT *`所有列）

**步骤**：
1. 创建`Optimizer`类，`optimize(ast) -> PlanNode`
2. 转换AST为逻辑计划：
   ```python
   LogicalPlanNode(Scan(table), Filter(condition), Project(columns))
   ```
3. 应用优化规则
4. 生成物理计划（SeqScan或IndexScan）

---

### 实验4：类型检查

**目标**：在解析后验证类型匹配性。

**步骤**：
1. 创建`SymbolTable`类，记录表结构
2. 解析`CREATE TABLE`时填充符号表
3. 解析`SELECT/WHERE`时验证：
   - 列是否存在
   - 运算符是否支持该类型（如`>`支持数字，不支持布尔）
   - 赋值类型匹配（INSERT的VALUES与表定义）

**示例**：
```sql
CREATE TABLE users (id INT, name VARCHAR(50), active BOOLEAN);
INSERT INTO users VALUES (1, 'Alice', 'yes');  -- 错误：'yes'应为布尔
```

---

## 常见问题

### Q1: 为什么不用解析器生成器（如PLY、ANTLR）？

**A**:
- **教学目的**：手写递归下降更直观，展示解析机制
- **控制力**：可精确控制错误处理和AST形状
- **依赖**：减少外部依赖，项目更独立
- **性能**：生成的代码可能更大更慢（对于小语言差别不大）

**缺点**：维护BNF和手写代码同步麻烦，复杂语法易出错。

---

### Q2: 如何处理SQL注入？

**A**: SQL注入是**应用层问题**，不是解析器问题。解析器只处理**正确的SQL字符串**。应用层应：
1. 使用参数化查询（预编译语句）
2. 验证和转义用户输入
3. 最小化数据库权限

ProjoDB作为教学DBMS，不负责SQL注入防护（那是前端/应用框架的事）。

---

### Q3: 如何支持多语句（分号分隔）？

**A**:
当前`Parser.parse()`只解析单条语句。扩展：
```python
def parse_multi(sql: str) -> List[ASTNode]:
    tokens = tokenizer.tokenize()
    statements = []
    # 按分号分割，但注意分号可能在字符串中
    # 简单方法：tokenize后，每次遇到SEMICOLON生成一个语句
    # 更可靠：累积tokens直到遇到未在引号内的分号
    return statements
```

---

### Q4: 错误恢复怎么办？

**A**: 当前遇到错误直接抛出异常（fail-fast）。教学DBMS不需要完善的错误恢复。高级做法：
1. **同步点**：遇到错误后跳过token直到下一个`KEYWORD`（如FROM、WHERE）
2. **默认AST**：用`ErrorNode`占位，继续解析
3. **错误收集**：一次报告多个错误

---

## 参考代码

- `src/parser/tokenizer.py`：完整词法分析器（约200行）
- `src/parser/parser.py`：完整语法分析器（约400行）
- `src/parser/ast.py`：所有AST节点定义
- `tests/parser/test_sql_parser.py`：测试用例

---

**下一步**：学习 [WAL日志系统](wal.md) 或继续 [实验4：WAL预写日志](docs/tutorials/exp4_wal.md)
