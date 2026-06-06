"""
SQL语法分析器（Parser）
使用递归下降解析方法
将标记列表转换为抽象语法树（AST）
"""

from .tokenizer import Token, Tokenizer
from .ast import (
    CreateTableNode, DropTableNode,
    SelectNode, InsertNode, UpdateNode, DeleteNode,
    BeginNode, CommitNode, RollbackNode,
    BinaryOpNode, ColumnNode, ValueNode, NullNode
)


class ParserError(Exception):
    """语法分析错误"""
    pass


class Parser:
    """递归下降SQL解析器"""

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = -1  # 从-1开始，这样第一次advance会设置到索引0
        self.current_token = None
        self.advance()  # 初始化第一个token

    def advance(self):
        """移动到下一个标记"""
        self.pos += 1
        if self.pos < len(self.tokens):
            self.current_token = self.tokens[self.pos]
        else:
            self.current_token = None

    def expect(self, token_type, token_value=None):
        """期望并消耗特定类型的标记"""
        if self.current_token is None:
            raise ParserError(f"期望 {token_type} 但已到文件末尾")

        if self.current_token.type != token_type:
            raise ParserError(f"第 {self.current_token.line} 行, 列 {self.current_token.column}: "
                            f"期望 {token_type} 但得到 {self.current_token.type} ('{self.current_token.value}')")

        if token_value is not None and self.current_token.value.upper() != token_value:
            raise ParserError(f"第 {self.current_token.line} 行, 列 {self.current_token.column}: "
                            f"期望值 '{token_value}' 但得到 '{self.current_token.value}'")

        token = self.current_token
        self.advance()
        return token

    def parse(self):
        """解析SQL语句（入口点）"""
        if self.current_token is None:
            raise ParserError("空输入")

        token_type = self.current_token.type

        # 根据第一个标记决定语句类型
        if token_type == 'CREATE':
            return self.parse_create_table()
        elif token_type == 'DROP':
            return self.parse_drop_table()
        elif token_type == 'SELECT':
            return self.parse_select()
        elif token_type == 'INSERT':
            return self.parse_insert()
        elif token_type == 'UPDATE':
            return self.parse_update()
        elif token_type == 'DELETE':
            return self.parse_delete()
        elif token_type == 'BEGIN':
            return self.parse_begin()
        elif token_type == 'COMMIT':
            return self.parse_commit()
        elif token_type == 'ROLLBACK':
            return self.parse_rollback()
        else:
            raise ParserError(f"第 {self.current_token.line} 行, 列 {self.current_token.column}: "
                            f"未预期的语句开始: {self.current_token}")

    # DDL解析

    def parse_create_table(self):
        """解析 CREATE TABLE table_name (col1 type1, col2 type2, ...)"""
        self.expect('CREATE')
        self.expect('TABLE')

        # 表名（标识符）
        table_name = self.expect('IDENTIFIER').value

        # 左括号
        self.expect('LPAREN', '(')

        # 列定义列表
        columns = []
        while True:
            col_name = self.expect('IDENTIFIER').value
            col_type = self.parse_data_type()

            # 约束（简化版，只处理 NOT NULL, PRIMARY KEY, UNIQUE）
            constraints = []
            while self.current_token:
                token_type = self.current_token.type
                token_value = self.current_token.value.upper()

                if token_type == 'NOT':
                    self.expect('NOT')
                    self.expect('NULL')
                    constraints.append('NOT NULL')
                elif token_type == 'PRIMARY':
                    self.expect('PRIMARY')
                    # 检查是否有 KEY
                    if self.current_token and self.current_token.type == 'KEY':
                        self.expect('KEY')
                        constraints.append('PRIMARY KEY')
                    else:
                        constraints.append('PRIMARY')
                elif token_type == 'UNIQUE':
                    self.expect('UNIQUE')
                    constraints.append('UNIQUE')
                else:
                    # 未知约束，跳出循环
                    break

            columns.append((col_name, col_type, constraints))

            # 看下一个标记是否是逗号
            if self.current_token and self.current_token.type == 'COMMA':
                self.advance()
            else:
                break

        # 右括号
        self.expect('RPAREN', ')')

        # 语句结束
        self.expect('SEMICOLON', ';')

        return CreateTableNode(table_name, columns)

    def parse_data_type(self):
        """解析数据类型（INT, INTEGER, FLOAT, VARCHAR(n), TEXT, BOOLEAN）"""
        if self.current_token is None:
            raise ParserError("期望数据类型")

        type_token = self.current_token
        type_name = type_token.value.upper()

        if type_name in ('INT', 'INTEGER'):
            self.advance()
            return 'INT'
        elif type_name in ('FLOAT', 'DOUBLE', 'REAL'):
            self.advance()
            return 'FLOAT'
        elif type_name in ('TEXT', 'VARCHAR', 'CHAR', 'STRING'):
            type_name = 'TEXT'  # 统一为TEXT
            self.advance()
            # VARCHAR可能有长度参数，但简化处理忽略
            if self.current_token and self.current_token.type == 'LPAREN':
                self.advance()  # (
                if self.current_token and self.current_token.type == 'INTEGER':
                    self.advance()  # length
                if self.current_token and self.current_token.type == 'RPAREN':
                    self.advance()  # )
            return 'TEXT'
        elif type_name == 'BOOLEAN':
            self.advance()
            return 'BOOLEAN'
        elif type_name == 'VARCHAR':
            self.advance()
            self.expect('LPAREN', '(')
            length_token = self.expect('INTEGER')
            length = length_token.value
            self.expect('RPAREN', ')')
            return 'TEXT'  # VARCHAR转为TEXT
        else:
            raise ParserError(f"第 {type_token.line} 行, 列 {type_token.column}: "
                            f"不支持的数据类型: {type_token.value}")

    def parse_drop_table(self):
        """解析 DROP TABLE table_name"""
        self.expect('DROP')
        self.expect('TABLE')

        table_name = self.expect('IDENTIFIER').value
        self.expect('SEMICOLON', ';')

        return DropTableNode(table_name)

    def parse_select(self):
        """解析 SELECT cols FROM table [WHERE condition]"""
        self.expect('SELECT')

        # 选择的列
        columns = []
        while True:
            if self.current_token.value == '*':
                columns.append('*')
                self.advance()
            else:
                col = self.expect('IDENTIFIER').value
                columns.append(col)

            if self.current_token and self.current_token.type == 'COMMA':
                self.advance()
            else:
                break

        self.expect('FROM')
        table_name = self.expect('IDENTIFIER').value

        # WHERE子句（可选）
        where_clause = None
        if self.current_token and self.current_token.type == 'WHERE':
            self.advance()
            where_clause = self.parse_expression()

        self.expect('SEMICOLON', ';')

        return SelectNode(columns, table_name, where_clause)

    def parse_insert(self):
        """解析 INSERT INTO table [(cols)] VALUES (vals)"""
        self.expect('INSERT')
        self.expect('INTO')

        table_name = self.expect('IDENTIFIER').value

        # 可选列名列表
        columns = []
        if self.current_token and self.current_token.type == 'LPAREN':
            self.advance()
            while True:
                col = self.expect('IDENTIFIER').value
                columns.append(col)
                if self.current_token and self.current_token.type == 'COMMA':
                    self.advance()
                else:
                    break
            self.expect('RPAREN', ')')

        self.expect('VALUES')
        self.expect('LPAREN', '(')

        # 值列表
        values = []
        while True:
            value = self.parse_value()
            values.append(value)
            if self.current_token and self.current_token.type == 'COMMA':
                self.advance()
            else:
                break

        self.expect('RPAREN', ')')
        self.expect('SEMICOLON', ';')

        return InsertNode(table_name, columns, values)

    def parse_update(self):
        """解析 UPDATE table SET col=val, col=val, ... [WHERE condition]"""
        self.expect('UPDATE')

        table_name = self.expect('IDENTIFIER').value
        self.expect('SET')

        # SET子句列表
        set_clauses = []
        while True:
            column = self.expect('IDENTIFIER').value
            self.expect('EQ', '=')
            value = self.parse_value()
            set_clauses.append((column, value))

            if self.current_token and self.current_token.type == 'COMMA':
                self.advance()
            else:
                break

        # WHERE子句（可选）
        where_clause = None
        if self.current_token and self.current_token.type == 'WHERE':
            self.advance()
            where_clause = self.parse_expression()

        self.expect('SEMICOLON', ';')

        return UpdateNode(table_name, set_clauses, where_clause)

    def parse_delete(self):
        """解析 DELETE FROM table [WHERE condition]"""
        self.expect('DELETE')
        self.expect('FROM')

        table_name = self.expect('IDENTIFIER').value

        # WHERE子句（可选）
        where_clause = None
        if self.current_token and self.current_token.type == 'WHERE':
            self.advance()
            where_clause = self.parse_expression()

        self.expect('SEMICOLON', ';')

        return DeleteNode(table_name, where_clause)

    # 事务解析

    def parse_begin(self):
        """解析 BEGIN"""
        self.expect('BEGIN')
        self.expect('SEMICOLON', ';')
        return BeginNode()

    def parse_commit(self):
        """解析 COMMIT"""
        self.expect('COMMIT')
        self.expect('SEMICOLON', ';')
        return CommitNode()

    def parse_rollback(self):
        """解析 ROLLBACK"""
        self.expect('ROLLBACK')
        self.expect('SEMICOLON', ';')
        return RollbackNode()

    # 表达式解析（用于WHERE子句）

    def parse_expression(self):
        """解析表达式（支持AND, OR优先级）"""
        return self.parse_or_expression()

    def parse_or_expression(self):
        """解析OR表达式"""
        left = self.parse_and_expression()
        while self.current_token and self.current_token.type == 'OR':
            self.advance()
            right = self.parse_and_expression()
            left = BinaryOpNode(left, 'OR', right)
        return left

    def parse_and_expression(self):
        """解析AND表达式"""
        left = self.parse_comparison()
        while self.current_token and self.current_token.type == 'AND':
            self.advance()
            right = self.parse_comparison()
            left = BinaryOpNode(left, 'AND', right)
        return left

    def parse_comparison(self):
        """解析比较表达式"""
        left = self.parse_primary()

        # 处理 IS NULL / IS NOT NULL
        if self.current_token and self.current_token.type == 'IS':
            self.advance()
            is_not = False
            if self.current_token and self.current_token.type == 'NOT':
                self.advance()
                is_not = True
            self.expect('NULL')
            if is_not:
                return BinaryOpNode(left, 'IS NOT', NullNode())
            else:
                return BinaryOpNode(left, 'IS', NullNode())

        # 如果没有比较运算符，直接返回
        if not self.current_token or self.current_token.type not in ('EQ', 'NE', 'GT', 'LT', 'GE', 'LE'):
            return left

        # 获取运算符（使用标记类型映射）
        op_map = {
            'EQ': '=',
            'NE': '!=',
            'GT': '>',
            'LT': '<',
            'GE': '>=',
            'LE': '<='
        }
        op = op_map[self.current_token.type]
        self.advance()

        right = self.parse_primary()
        return BinaryOpNode(left, op, right)

    def parse_primary(self):
        """解析基本表达式（列引用、值、括号表达式）"""
        token = self.current_token

        if token is None:
            raise ParserError("意外的表达式结束")

        # 括号表达式
        if token.type == 'LPAREN':
            self.advance()
            expr = self.parse_expression()
            self.expect('RPAREN', ')')
            return expr

        # 列引用
        if token.type == 'IDENTIFIER':
            self.advance()
            return ColumnNode(token.value)

        # 值字面量
        if token.type in ('INTEGER', 'FLOAT', 'STRING'):
            value_type = 'integer' if token.type == 'INTEGER' else \
                         'float' if token.type == 'FLOAT' else 'string'
            self.advance()
            return ValueNode(token.value, value_type)

        # NULL
        if token.type == 'NULL':
            self.advance()
            return NullNode()

        raise ParserError(f"第 {token.line} 行, 列 {token.column}: "
                        f"意外的标记在表达式中: {token}")

    def parse_value(self):
        """解析值（字面量或NULL）"""
        token = self.current_token

        if token.type == 'NULL':
            self.advance()
            return NullNode()
        elif token.type == 'TRUE':
            self.advance()
            return ValueNode(True, 'boolean')
        elif token.type == 'FALSE':
            self.advance()
            return ValueNode(False, 'boolean')
        elif token.type in ('INTEGER', 'FLOAT', 'STRING'):
            value_type = 'integer' if token.type == 'INTEGER' else \
                         'float' if token.type == 'FLOAT' else 'string'
            self.advance()
            return ValueNode(token.value, value_type)
        else:
            raise ParserError(f"第 {token.line} 行, 列 {token.column}: "
                            f"期望值但得到 {token}")


def parse(sql):
    """便利函数：解析SQL字符串并返回AST"""
    tokenizer = Tokenizer(sql)
    tokens = tokenizer.tokenize()
    parser = Parser(tokens)
    return parser.parse()
