"""
抽象语法树（AST）节点定义
用于表示SQL语句的语法结构
"""

class ASTNode:
    """AST节点基类"""
    pass


# DDL节点

class CreateTableNode(ASTNode):
    """CREATE TABLE语句的AST节点"""
    def __init__(self, table_name, columns):
        self.table_name = table_name  # 表名
        self.columns = columns        # 列定义列表 [(name, type, constraints), ...]

    def __repr__(self):
        return f"CreateTable(table={self.table_name}, columns={self.columns})"


class DropTableNode(ASTNode):
    """DROP TABLE语句的AST节点"""
    def __init__(self, table_name):
        self.table_name = table_name

    def __repr__(self):
        return f"DropTable(table={self.table_name})"


# DML节点

class SelectNode(ASTNode):
    """SELECT语句的AST节点"""
    def __init__(self, columns, table_name, where_clause=None):
        self.columns = columns      # 选择的列列表 ['*' 或列名]
        self.table_name = table_name # 表名
        self.where_clause = where_clause # WHERE条件表达式（可选）

    def __repr__(self):
        return f"Select(columns={self.columns}, table={self.table_name}, where={self.where_clause})"


class InsertNode(ASTNode):
    """INSERT语句的AST节点（单表，指定列值）"""
    def __init__(self, table_name, columns, values):
        self.table_name = table_name # 表名
        self.columns = columns       # 列名列表（可选，可为空表示所有列）
        self.values = values         # 值列表

    def __repr__(self):
        return f"Insert(table={self.table_name}, columns={self.columns}, values={self.values})"


class UpdateNode(ASTNode):
    """UPDATE语句的AST节点（单表，简单SET）"""
    def __init__(self, table_name, set_clauses, where_clause=None):
        self.table_name = table_name     # 表名
        self.set_clauses = set_clauses   # SET子句 [(column, value), ...]
        self.where_clause = where_clause # WHERE条件表达式（可选）

    def __repr__(self):
        return f"Update(table={self.table_name}, set={self.set_clauses}, where={self.where_clause})"


class DeleteNode(ASTNode):
    """DELETE语句的AST节点（单表）"""
    def __init__(self, table_name, where_clause=None):
        self.table_name = table_name     # 表名
        self.where_clause = where_clause # WHERE条件表达式（可选）

    def __repr__(self):
        return f"Delete(table={self.table_name}, where={self.where_clause})"


# 事务节点

class BeginNode(ASTNode):
    """BEGIN语句的AST节点"""
    def __repr__(self):
        return "Begin()"


class CommitNode(ASTNode):
    """COMMIT语句的AST节点"""
    def __repr__(self):
        return "Commit()"


class RollbackNode(ASTNode):
    """ROLLBACK语句的AST节点"""
    def __repr__(self):
        return "Rollback()"


# 表达式节点（用于WHERE子句）

class BinaryOpNode(ASTNode):
    """二元操作符表达式节点（如 a = 5, x > 10）"""
    def __init__(self, left, op, right):
        self.left = left    # 左操作数
        self.op = op        # 操作符（'=', '>', '<', '>=', '<=', '!=', 'AND', 'OR'）
        self.right = right  # 右操作数

    def __repr__(self):
        return f"BinaryOp({self.left} {self.op} {self.right})"


class ColumnNode(ASTNode):
    """列引用节点"""
    def __init__(self, column_name):
        self.column_name = column_name

    def __repr__(self):
        return f"Column('{self.column_name}')"


class ValueNode(ASTNode):
    """值节点（字面量）"""
    def __init__(self, value, value_type):
        self.value = value      # 实际值
        self.value_type = value_type  # 'integer', 'float', 'string', 'null'

    def __repr__(self):
        return f"Value({self.value}::{self.value_type})"


class NullNode(ASTNode):
    """NULL值节点"""
    def __repr__(self):
        return "NULL"
