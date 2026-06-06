#!/usr/bin/env python3
"""
执行引擎集成测试 - 快速验证版

目标：验证执行引擎核心功能（INSERT, SELECT, UPDATE, DELETE）
"""

import sys
sys.path.insert(0, '/home/claude/git/github/tmp/projo/src')

from core.storage_interface import InMemoryStorage
from executor.executor import Executor
from executor.simple_storage import SimpleStorageEngine
from parser.ast import (
    ColumnNode, ValueNode, BinaryOpNode,
    SelectNode, InsertNode, UpdateNode, DeleteNode,
    CreateTableNode
)


def test_crud():
    """基础CRUD测试"""
    print("=" * 60)
    print("执行引擎集成测试 - 快速验证")
    print("=" * 60)
    
    # 1. 创建存储和执行引擎
    raw_storage = InMemoryStorage(page_size=4096)
    storage = SimpleStorageEngine(raw_storage)
    executor = Executor(storage_engine=storage)
    
    # 2. 创建表
    create_ast = CreateTableNode(
        table_name='users',
        columns=[
            ('id', 'INTEGER', ['PRIMARY KEY']),
            ('name', 'TEXT', ['NOT NULL']),
            ('age', 'INTEGER', []),
            ('salary', 'FLOAT', [])
        ]
    )
    result = executor.execute(create_ast)
    print("✅ CREATE TABLE 'users' 成功")
    
    # 3. 插入记录
    print("\n--- INSERT ---")
    insert_ast = InsertNode(
        table_name='users',
        columns=['id', 'name', 'age', 'salary'],
        values=[
            ValueNode(1, 'integer'),
            ValueNode('Alice', 'string'),
            ValueNode(25, 'integer'),
            ValueNode(50000.0, 'float')
        ]
    )
    result = executor.execute(insert_ast)
    print(f"INSERT结果: {result.to_dict()}")
    assert result.success and result.rows_affected == 1
    print("✅ 第一条记录插入成功")
    
    # 更多插入
    inserts = [
        (2, 'Bob', 30, 60000.0),
        (3, 'Charlie', 35, 75000.0),
        (4, 'David', 28, 45000.0),
        (5, 'Eve', 22, 35000.0),
    ]
    for uid, name, age, salary in inserts:
        ast = InsertNode(
            table_name='users',
            columns=['id', 'name', 'age', 'salary'],
            values=[
                ValueNode(uid, 'integer'),
                ValueNode(name, 'string'),
                ValueNode(age, 'integer'),
                ValueNode(salary, 'float')
            ]
        )
        result = executor.execute(ast)
        assert result.success
    print(f"✅ 共插入 {len(inserts)+1} 条记录")
    
    # 4. SELECT *（全扫描）
    print("\n--- SELECT * ---")
    select_all = SelectNode(columns=['*'], table_name='users', where_clause=None)
    result = executor.execute(select_all)
    print(f"返回 {len(result.rows)} 行")
    assert len(result.rows) == 5
    print("✅ 全表扫描成功")
    
    # 5. SELECT投影
    print("\n--- SELECT name, salary ---")
    select_proj = SelectNode(columns=['name', 'salary'], table_name='users')
    result = executor.execute(select_proj)
    assert result.columns == ['name', 'salary']
    print(f"返回 {len(result.rows)} 行，列: {result.columns}")
    print("✅ 投影查询成功")
    
    # 6. SELECT WHERE (age > 25)
    print("\n--- WHERE age > 25 ---")
    where = BinaryOpNode(ColumnNode('age'), '>', ValueNode(25, 'integer'))
    select_where = SelectNode(columns=['*'], table_name='users', where_clause=where)
    result = executor.execute(select_where)
    assert len(result.rows) == 3
    for row in result.rows:
        assert row['age'] > 25
    print(f"返回 {len(result.rows)} 行")
    print("✅ 条件过滤成功")
    
    # 7. UPDATE
    print("\n--- UPDATE ---")
    update_ast = UpdateNode(
        table_name='users',
        set_clauses=[('salary', ValueNode(65000.0, 'float'))],
        where_clause=BinaryOpNode(ColumnNode('name'), '=', ValueNode('Bob', 'string'))
    )
    result = executor.execute(update_ast)
    print(f"UPDATE结果: {result.to_dict()}")
    assert result.success and result.rows_affected == 1, f"预期影响1行，实际{result.rows_affected}"
    print(f"UPDATE影响行数: {result.rows_affected}")
    print("✅ UPDATE成功")
    
    # 验证Bob的新工资
    result = executor.execute(SelectNode(
        columns=['name', 'salary'],
        table_name='users',
        where_clause=BinaryOpNode(ColumnNode('name'), '=', ValueNode('Bob', 'string'))
    ))
    assert result.rows[0]['salary'] == 65000.0
    print("✅ 更新数据正确")
    
    # 8. DELETE
    print("\n--- DELETE ---")
    delete_ast = DeleteNode(
        table_name='users',
        where_clause=BinaryOpNode(ColumnNode('age'), '<', ValueNode(25, 'integer'))
    )
    result = executor.execute(delete_ast)
    assert result.success and result.rows_affected == 1
    print(f"DELETE影响行数: {result.rows_affected}")
    print("✅ DELETE成功")
    
    # 验证剩余记录
    result = executor.execute(SelectNode(columns=['*'], table_name='users'))
    assert len(result.rows) == 4
    print(f"剩余 {len(result.rows)} 条记录")
    print("✅ 删除正确")
    
    # 9. 复杂条件 (AND)
    print("\n--- 复杂条件 AND ---")
    complex_cond = BinaryOpNode(
        BinaryOpNode(ColumnNode('age'), '>', ValueNode(25, 'integer')),
        'AND',
        BinaryOpNode(ColumnNode('salary'), '>=', ValueNode(60000.0, 'float'))
    )
    select_complex = SelectNode(columns=['name', 'age', 'salary'], table_name='users', where_clause=complex_cond)
    result = executor.execute(select_complex)
    for row in result.rows:
        assert row['age'] > 25 and row['salary'] >= 60000.0
    assert len(result.rows) == 2  # Bob(30,65000), Charlie(35,75000)
    print("✅ 复杂条件求值成功")
    
    # 清理
    storage.close()
    
    print("\n" + "=" * 60)
    print("🎉 所有测试通过！执行引擎核心功能正常")
    print("=" * 60)
    return True


if __name__ == '__main__':
    try:
        test_crud()
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
