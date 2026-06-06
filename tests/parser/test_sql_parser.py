"""
SQL解析器测试套件
测试词法分析和语法分析功能
"""

import sys
sys.path.insert(0, '/home/claude/git/github/tmp/projo/src')

from parser import Tokenizer, TokenizerError, Parser, ParserError, parse
from parser.ast import (
    CreateTableNode, DropTableNode,
    SelectNode, InsertNode, UpdateNode, DeleteNode,
    BeginNode, CommitNode, RollbackNode,
    BinaryOpNode, ColumnNode, ValueNode, NullNode
)


def test_tokenizer():
    """测试词法分析器"""
    print("测试词法分析器...")

    # 测试基本标记
    sql = "SELECT * FROM users WHERE id = 10;"
    tokens = Tokenizer(sql).tokenize()
    assert len(tokens) >= 6
    assert tokens[0].type == 'SELECT'
    assert tokens[1].type == 'STAR'
    assert tokens[2].type == 'FROM'
    # 标识符保持原大小写（SQL标识符大小写不敏感，这里保持原样）
    assert tokens[3].type == 'IDENTIFIER' and tokens[3].value == 'users'
    print("✓ 基本标记识别正确")

    # 测试字符串
    sql = "INSERT INTO t VALUES ('hello', 'world');"
    tokens = Tokenizer(sql).tokenize()
    string_tokens = [t for t in tokens if t.type == 'STRING']
    assert len(string_tokens) == 2
    assert string_tokens[0].value == 'hello'
    assert string_tokens[1].value == 'world'
    print("✓ 字符串字面量正确")

    # 测试数字
    sql = "SELECT price FROM products WHERE price > 19.99;"
    tokens = Tokenizer(sql).tokenize()
    float_tokens = [t for t in tokens if t.type == 'FLOAT']
    assert len(float_tokens) == 1 and float_tokens[0].value == 19.99
    print("✓ 浮点数字面量正确")

    # 测试整数
    sql2 = "SELECT * FROM users WHERE id > 100;"
    tokens2 = Tokenizer(sql2).tokenize()
    int_tokens = [t for t in tokens2 if t.type == 'INTEGER']
    assert len(int_tokens) == 1 and int_tokens[0].value == 100
    print("✓ 整数字面量正确")

    # 测试运算符
    sql = "UPDATE t SET a=5, b=10 WHERE x >= 100 AND y <= 200;"
    tokens = Tokenizer(sql).tokenize()
    token_types = [t.type for t in tokens]
    assert 'GE' in token_types
    assert 'LE' in token_types
    assert 'EQ' in token_types
    print("✓ 运算符识别正确（包括 >=, <=, =）")

    print()


def test_parser():
    """测试语法分析器"""
    print("测试语法分析器...")

    # 测试CREATE TABLE
    ast = parse("""
        CREATE TABLE users (
            id INT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            age INT,
            active BOOLEAN
        );
    """)
    assert isinstance(ast, CreateTableNode)
    assert ast.table_name == 'users'
    assert len(ast.columns) == 4
    assert ast.columns[0] == ('id', 'INT', ['PRIMARY KEY'])
    assert ast.columns[1] == ('name', 'VARCHAR(100)', ['NOT NULL'])
    print("✓ CREATE TABLE解析正确")

    # 测试DROP TABLE
    ast = parse("DROP TABLE users;")
    assert isinstance(ast, DropTableNode)
    assert ast.table_name == 'users'
    print("✓ DROP TABLE解析正确")

    # 测试SELECT（简单）
    ast = parse("SELECT * FROM users;")
    assert isinstance(ast, SelectNode)
    assert ast.columns == ['*']
    assert ast.table_name == 'users'
    assert ast.where_clause is None
    print("✓ 简单SELECT解析正确")

    # 测试SELECT（多列）
    ast = parse("SELECT id, name, email FROM users;")
    assert isinstance(ast, SelectNode)
    assert ast.columns == ['id', 'name', 'email']
    print("✓ 多列SELECT解析正确")

    # 测试SELECT（带WHERE）
    ast = parse("SELECT * FROM products WHERE price > 100;")
    assert isinstance(ast, SelectNode)
    assert ast.where_clause is not None
    assert isinstance(ast.where_clause, BinaryOpNode)
    assert ast.where_clause.op == '>'
    print("✓ 带WHERE的SELECT解析正确")

    # 测试SELECT（复杂WHERE）
    ast = parse("SELECT * FROM orders WHERE status = 'pending' AND amount >= 50 OR priority = 1;")
    assert ast.where_clause is not None
    # 检查是OR包含AND结构
    assert isinstance(ast.where_clause, BinaryOpNode) and ast.where_clause.op == 'OR'
    print("✓ 复杂WHERE条件（AND/OR优先级）解析正确")

    # 测试INSERT（所有列）
    ast = parse("INSERT INTO users VALUES (1, 'Alice', 25, true);")
    assert isinstance(ast, InsertNode)
    assert ast.table_name == 'users'
    assert ast.columns == []  # 空列表表示所有列
    assert len(ast.values) == 4
    assert isinstance(ast.values[0], ValueNode) and ast.values[0].value == 1
    assert isinstance(ast.values[1], ValueNode) and ast.values[1].value == 'Alice'
    print("✓ INSERT（所有列）解析正确")

    # 测试INSERT（指定列）
    ast = parse("INSERT INTO users (id, name) VALUES (2, 'Bob');")
    assert isinstance(ast, InsertNode)
    assert ast.columns == ['id', 'name']
    assert len(ast.values) == 2
    print("✓ INSERT（指定列）解析正确")

    # 测试UPDATE
    ast = parse("UPDATE products SET price = 99.99, stock = 100 WHERE id = 5;")
    assert isinstance(ast, UpdateNode)
    assert ast.table_name == 'products'
    assert len(ast.set_clauses) == 2
    col1, val1 = ast.set_clauses[0]
    col2, val2 = ast.set_clauses[1]
    assert col1 == 'price'
    assert isinstance(val1, ValueNode) and val1.value == 99.99 and val1.value_type == 'float'
    assert col2 == 'stock'
    assert isinstance(val2, ValueNode) and val2.value == 100 and val2.value_type == 'integer'
    assert ast.where_clause is not None
    print("✓ UPDATE解析正确")

    # 测试UPDATE（不带WHERE）
    ast = parse("UPDATE products SET status = 'archived';")
    assert isinstance(ast, UpdateNode)
    assert ast.where_clause is None
    print("✓ UPDATE（不带WHERE）解析正确")

    # 测试DELETE
    ast = parse("DELETE FROM users WHERE id = 10;")
    assert isinstance(ast, DeleteNode)
    assert ast.table_name == 'users'
    assert ast.where_clause is not None
    print("✓ DELETE（带WHERE）解析正确")

    # 测试DELETE（不带WHERE）
    ast = parse("DELETE FROM temp_table;")
    assert isinstance(ast, DeleteNode)
    assert ast.where_clause is None
    print("✓ DELETE（不带WHERE）解析正确")

    # 测试事务语句
    ast = parse("BEGIN;")
    assert isinstance(ast, BeginNode)
    print("✓ BEGIN语句解析正确")

    ast = parse("COMMIT;")
    assert isinstance(ast, CommitNode)
    print("✓ COMMIT语句解析正确")

    ast = parse("ROLLBACK;")
    assert isinstance(ast, RollbackNode)
    print("✓ ROLLBACK语句解析正确")

    print()


def test_expressions():
    """测试表达式解析"""
    print("测试表达式解析...")

    # 测试列引用
    ast = parse("SELECT id FROM users WHERE name = 'test';")
    col = ast.where_clause.left
    assert isinstance(col, ColumnNode)
    assert col.column_name == 'name'
    print("✓ 列引用解析正确")

    # 测试值节点
    ast = parse("SELECT * FROM t WHERE x = 42;")
    value = ast.where_clause.right
    assert isinstance(value, ValueNode)
    assert value.value == 42
    assert value.value_type == 'integer'
    print("✓ 整数值节点正确")

    # 测试NULL
    ast = parse("SELECT * FROM t WHERE deleted IS NULL;")
    assert ast.where_clause.right is not None
    assert isinstance(ast.where_clause.right, NullNode) or \
           (hasattr(ast.where_clause.right, '__class__') and ast.where_clause.right.__class__.__name__ == 'NullNode')
    print("✓ NULL值正确")

    # 测试运算优先级：AND优先于OR
    ast = parse("SELECT * FROM t WHERE a = 1 AND b = 2 OR c = 3;")
    # 应该是 (a=1 AND b=2) OR c=3
    root = ast.where_clause
    assert root.op == 'OR'
    assert isinstance(root.left, BinaryOpNode) and root.left.op == 'AND'
    print("✓ AND/OR优先级正确（AND优先）")

    # 测试括号
    ast = parse("SELECT * FROM t WHERE (a = 1 OR b = 2) AND c = 3;")
    root = ast.where_clause
    assert root.op == 'AND'
    # 左边应该是括号内的OR表达式
    assert isinstance(root.left, BinaryOpNode) and root.left.op == 'OR'
    print("✓ 括号表达式优先级正确")

    # 测试复杂比较运算符
    for op_sql, op in [('>=', '>='), ('<=', '<='), ('!=', '!='), ('>', '>'), ('<', '<')]:
        ast = parse(f"SELECT * FROM t WHERE x {op} 5;")
        assert ast.where_clause.op == op
    print("✓ 所有比较运算符解析正确")

    print()


def test_error_handling():
    """测试错误处理"""
    print("测试错误处理...")

    # 词法错误
    try:
        Tokenizer("SELECT @ FROM t;").tokenize()
        assert False, "应该抛出TokenizerError"
    except TokenizerError as e:
        assert "意外字符" in str(e)
        print("✓ 词法错误正确抛出")

    # 语法错误
    try:
        parse("CREATE TABLE (id INT);")
        assert False, "应该抛出ParserError（缺少表名）"
    except ParserError as e:
        assert "期望" in str(e)
        print("✓ 语法错误（缺失表名）正确抛出")

    try:
        parse("SELECT FROM users;")
        assert False, "应该抛出ParserError（选择列表错误）"
    except ParserError as e:
        print("✓ 语法错误（选择列表错误）正确抛出")

    try:
        parse("INSERT INTO users VALUES ();")
        assert False, "应该抛出ParserError（缺失值）"
    except ParserError as e:
        print("✓ 语法错误（缺失值）正确抛出")

    try:
        parse("SELECT * FROM WHERE id = 1;")
        assert False, "应该抛出ParserError（缺失表名）"
    except ParserError as e:
        print("✓ 语法错误（缺失表名）正确抛出")

    print()


def test_edge_cases():
    """测试边界情况"""
    print("测试边界情况...")

    # 大小写
    ast1 = parse("select * from users;")
    ast2 = parse("SELECT * FROM USERS;")
    assert ast1.table_name == 'users' or ast1.table_name == 'USERS'
    print("✓ 大小写正确处理")

    # 空白字符
    ast = parse("  SELECT   *   FROM   users   WHERE   id=1  ;  ")
    assert ast.table_name.strip() == 'users'
    print("✓ 多余空白字符正确处理")

    # 注释（简化）
    sql = "SELECT * FROM users -- 这是注释\nWHERE id = 1;"
    tokens = Tokenizer(sql).tokenize()
    # 应该跳过注释
    comment_tokens = [t for t in tokens if '注释' in str(t)]
    assert len(comment_tokens) == 0
    print("✓ 单行注释跳过正确")

    # 转义字符串
    sql = "INSERT INTO t VALUES ('It''s test');"
    tokens = Tokenizer(sql).tokenize()
    string_tokens = [t for t in tokens if t.type == 'STRING']
    assert len(string_tokens) == 1
    assert string_tokens[0].value == "It's test"
    print("✓ 转义字符串正确")

    print()


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("SQL解析器测试套件")
    print("=" * 60)
    print()

    try:
        test_tokenizer()
        test_parser()
        test_expressions()
        test_error_handling()
        test_edge_cases()

        print("=" * 60)
        print("所有测试通过！✓")
        print("=" * 60)
        return True
    except AssertionError as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"测试异常: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
