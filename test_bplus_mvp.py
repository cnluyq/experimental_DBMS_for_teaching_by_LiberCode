#!/usr/bin/env python
"""
B+树MVP功能验证测试
验证：持久化insert、search、range查询
"""

from src.index.serializer import PersistentBPlusTree
from src.core.buffer import BufferPool
from src.core.storage_interface import InMemoryStorage


def test_mvp_functionality():
    """测试B+树MVP核心功能"""
    print('=== B+树MVP功能验证 ===\n')
    
    # 初始化存储引擎和缓冲区
    storage = InMemoryStorage(page_size=4096)
    buffer = BufferPool(num_frames=100, storage_engine=storage)
    
    # 创建持久化B+树
    tree = PersistentBPlusTree(buffer_pool=buffer, order=4)
    print(f'✅ 创建B+树成功 (order=4)')
    
    # 1. 测试持久化insert
    print('\n--- 1. 持久化insert测试 ---')
    test_data = [
        (10, (10, 0)),
        (20, (20, 0)),
        (5, (5, 0)),
        (15, (15, 0)),
        (25, (25, 0)),
        (8, (8, 0)),
        (12, (12, 0)),
        (18, (18, 0)),
        (30, (30, 0)),
        (1, (1, 0)),
        (3, (3, 0)),
    ]
    
    for key, value in test_data:
        result = tree.insert(key, value)
        assert result == True, f'插入{key}失败'
    
    print(f'✅ 插入{len(test_data)}个键值对成功')
    print(f'   索引大小: {tree.size}')
    # print(f'   树高度: {tree.get_height()}')  # PersistentBPlusTree没有此方法
    
    # 2. 测试search
    print('\n--- 2. search测试 ---')
    search_tests = [
        (10, (10, 0)),
        (15, (15, 0)),
        (1, (1, 0)),
        (30, (30, 0)),
        (99, None),  # 不存在的键
    ]
    
    for key, expected in search_tests:
        result = tree.search(key)
        assert result == expected, f'search({key})期望{expected}，实际{result}'
        status = '✅' if result == expected else '❌'
        print(f'   {status} search({key}) = {result}')
    
    print(f'✅ 所有search测试通过')
    
    # 3. 测试range_search
    print('\n--- 3. range_search测试 ---')
    range_tests = [
        ((5, 15), [5, 8, 10, 12, 15]),
        ((1, 10), [1, 3, 5, 8, 10]),
        ((20, 30), [20, 25, 30]),
        ((0, 100), [1, 3, 5, 8, 10, 12, 15, 18, 20, 25, 30]),
        ((50, 100), []),  # 空范围
    ]
    
    for (start, end), expected_keys in range_tests:
        results = tree.range_search(start, end)
        actual_keys = [k for k, v in results]
        assert actual_keys == expected_keys, f'range_search({start},{end})期望{expected_keys}，实际{actual_keys}'
        print(f'   ✅ range_search({start:3}, {end:3}) -> {len(results)}个结果: {actual_keys}')
    
    print(f'✅ 所有range_search测试通过')
    
    # 4. 测试持久化（shutdown重建）
    print('\n--- 4. 持久化测试（shutdown重建） ---')
    # 获取根节点page_id
    root_page_id_before = tree.root_page_id
    tree.shutdown()
    print(f'   ✅ shutdown完成')
    
    # 重建B+树（使用相同的root_page_id）
    new_tree = PersistentBPlusTree(
        buffer_pool=buffer,
        order=4,
        root_page_id=root_page_id_before
    )
    print(f'   ✅ 从持久化重建B+树成功')
    
    # 验证rebuilt tree的数据
    assert new_tree.size == tree.size, f'size不匹配: rebuild={new_tree.size}, before={tree.size}'
    print(f'   重建后大小: {new_tree.size}')
    
    # 验证search在重建树上的结果
    for key, expected in search_tests:
        result = new_tree.search(key)
        assert result == expected, f'重建后search({key})失败'
    print(f'   ✅ 重建后所有search测试通过')
    
    # 验证range_search在重建树上的结果
    for (start, end), expected_keys in range_tests:
        results = new_tree.range_search(start, end)
        actual_keys = [k for k, v in results]
        assert actual_keys == expected_keys, f'重建后range_search失败'
    print(f'   ✅ 重建后所有range_search测试通过')
    
    # 5. 测试新插入（重建后继续使用）
    print('\n--- 5. 重建后继续插入测试 ---')
    new_tree.insert(35, (35, 0))
    new_tree.insert(7, (7, 0))
    new_tree.insert(2, (2, 0))
    
    assert new_tree.search(35) == (35, 0)
    assert new_tree.search(7) == (7, 0)
    assert new_tree.search(2) == (2, 0)
    print(f'   ✅ 重建后插入新键并验证成功')
    
    # 清理
    new_tree.shutdown()
    
    print('\n' + '='*50)
    print('✅✅✅ B+树MVP功能全面验证通过！ ✅✅✅')
    print('='*50)
    print('\n结论：')
    print('  - 持久化insert: 正常工作，数据正确写入存储')
    print('  - search: 正常工作，精确查找准确')
    print('  - range_search: 正常工作，范围查询准确')
    print('  - 持久化恢复: shutdown后重建可恢复所有数据')
    print('\nMVP目标达成：insert/search/range完整功能已验证！')


if __name__ == '__main__':
    test_mvp_functionality()
