#!/usr/bin/env python3
"""
系统表持久化测试

验证：
1. 创建表后系统表记录存在
2. 重启存储引擎后能加载现有表
"""

import sys
sys.path.insert(0, '/home/claude/git/github/tmp/projo/src')

from core.storage_interface import SimpleFileStorage
from executor.simple_storage import SimpleStorageEngine
from executor.executor import Executor
from parser.ast import CreateTableNode, InsertNode, SelectNode, ValueNode, BinaryOpNode, ColumnNode


def test_system_table_persistence():
    print("=" * 60)
    print("系统表持久化测试")
    print("=" * 60)
    
    import tempfile
    import os
    
    # 创建临时文件用于持久化存储
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = tmp.name
    
    try:
        # 第一次：创建存储引擎并写入数据
        print("第一次：创建表并插入数据")
        file_storage = SimpleFileStorage(tmp_path, 4096)
        storage = SimpleStorageEngine(file_storage)
        executor = Executor(storage_engine=storage)
        
        # 创建表
        create_ast = CreateTableNode(
            table_name='users',
            columns=[
                ('id', 'INTEGER', ['PRIMARY KEY']),
                ('name', 'TEXT', ['NOT NULL']),
                ('age', 'INTEGER', []),
            ]
        )
        result = executor.execute(create_ast)
        print(f"CREATE TABLE: {result.message}")
        assert result.success
        
        # 插入数据
        insert_ast = InsertNode(
            table_name='users',
            columns=['id', 'name', 'age'],
            values=[
                ValueNode(1, 'integer'),
                ValueNode('Alice', 'string'),
                ValueNode(25, 'integer'),
            ]
        )
        result = executor.execute(insert_ast)
        print(f"INSERT: {result.to_dict()}")
        assert result.success and result.rows_affected == 1
        
        # 查询数据
        select_ast = SelectNode(columns=['*'], table_name='users')
        result = executor.execute(select_ast)
        print(f"SELECT: {result.rows}")
        assert len(result.rows) == 1
        assert result.rows[0]['name'] == 'Alice'
        
        # 验证系统表内容
        sys_tables = storage.table_storage.sys_mgr.list_all_tables()
        print(f"\n系统表 __tables__ 记录数: {len(sys_tables)}")
        users_entry = None
        for t in sys_tables:
            if t.get('table_name') == 'users':
                users_entry = t
                break
        assert users_entry is not None, "users表应在系统表中"
        print(f"users表系统表记录: {users_entry}")
        assert users_entry.get('root_page') is not None, "应有root_page"
        
        # 验证列系统表
        table_id = users_entry.get('table_id')
        cols = storage.table_storage.sys_mgr.get_columns_for_table(table_id)
        print(f"users表列定义: {cols}")
        assert len(cols) == 3, "应有3个列"
        
        # 关闭存储引擎
        storage.close()
        
        # 第二次：重新打开存储引擎，验证持久化
        print("\n--- 重新打开存储引擎 ---")
        file_storage2 = SimpleFileStorage(tmp_path, 4096)
        persistent_storage = SimpleStorageEngine(file_storage2)
        
        # 执行同样的操作
        executor2 = Executor(persistent_storage)
        
        # 检查users表是否已存在
        select_ast = SelectNode(columns=['*'], table_name='users')
        result2 = executor2.execute(select_ast)
        print(f"重启后SELECT users: {result2.rows}")
        assert len(result2.rows) == 1, "重启后应保留数据"
        assert result2.rows[0]['name'] == 'Alice'
        
        # 再插入一条，确保一切正常
        insert_ast2 = InsertNode(
            table_name='users',
            columns=['id', 'name', 'age'],
            values=[
                ValueNode(2, 'integer'),
                ValueNode('Bob', 'string'),
                ValueNode(30, 'integer'),
            ]
        )
        result3 = executor2.execute(insert_ast2)
        assert result3.success and result3.rows_affected == 1
        
        # 最终检查
        result4 = executor2.execute(SelectNode(columns=['*'], table_name='users'))
        assert len(result4.rows) == 2
        print(f"最终记录数: {len(result4.rows)}")
        
        persistent_storage.close()
    finally:
        import os
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    
    print("\n" + "=" * 60)
    print("✅ 系统表持久化测试通过")
    print("=" * 60)


if __name__ == '__main__':
    try:
        test_system_table_persistence()
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
