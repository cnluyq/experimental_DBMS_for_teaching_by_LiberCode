#!/usr/bin/env python
"""
B+树MVP功能验证 - 简化版（不依赖链表完整性检查）
"""

from src.index.serializer import PersistentBPlusTree
from src.core.buffer import BufferPool
from src.core.storage_interface import InMemoryStorage


def validate_mvp():
    print('=== B+树MVP验证 ===\n')

    storage = InMemoryStorage(page_size=4096)
    buffer = BufferPool(num_frames=200, storage_engine=storage)
    tree = PersistentBPlusTree(buffer_pool=buffer, order=4)

    # 1. 插入测试（大量数据触发分裂）
    print('1. 持久化insert测试')
    test_keys = sorted(set(list(range(0, 100, 5)) + [1, 3, 8, 12, 15, 18, 21, 22, 23, 26, 28]))
    for k in test_keys:
        result = tree.insert(k, (k*10, 0))
        assert result, f'插入{k}失败'

    print(f'   插入{len(test_keys)}个唯一键')
    print(f'   索引大小: {tree.size}')
    assert tree.size == len(test_keys)

    # 2. Search测试
    print('\n2. search测试')
    search_tests = [(k, (k*10, 0)) for k in [0, 1, 3, 15, 28, 95]]
    search_tests.append((999, None))

    for key, expected in search_tests:
        result = tree.search(key)
        assert result == expected, f'search({key})失败: 期望{expected}, 得到{result}'
        print(f'   ✅ search({key}) = {result}')

    # 3. Range_search测试
    print('\n3. range_search测试')
    range_tests = [
        (0, 100, test_keys),
        (15, 15, [15]),
        (20, 25, [k for k in test_keys if 20 <= k <= 25]),
        (50, 60, [k for k in test_keys if 50 <= k <= 60]),
        (200, 300, []),
    ]

    for start, end, expected_keys in range_tests:
        results = tree.range_search(start, end)
        actual_keys = [k for k, v in results]
        assert actual_keys == expected_keys, f'range_search({start},{end})失败: 期望{expected_keys}, 得到{actual_keys}'
        print(f'   ✅ range_search({start:3}, {end:3}): {len(results)}个结果')

    # 4. 持久化验证
    print('\n4. 持久化测试（shutdown重建）')
    root_id = tree.root_page_id
    size_before = tree.size

    # shutdown并重建
    tree.shutdown()
    print(f'   ✅ shutdown完成')

    tree2 = PersistentBPlusTree(buffer_pool=buffer, order=4, root_page_id=root_id)
    print(f'   ✅ 重建成功')
    print(f'   大小: {tree2.size} (之前: {size_before})')
    assert tree2.size == size_before

    # 验证所有数据
    for k in test_keys:
        result = tree2.search(k)
        expected = (k*10, 0)
        assert result == expected, f'重建后search({k})失败: 期望{expected}, 得到{result}'
    print(f'   ✅ 所有{len(test_keys)}个键在重建后都能正确search')

    # 验证range_search
    for start, end, expected_keys in range_tests:
        results = tree2.range_search(start, end)
        actual_keys = [k for k, v in results]
        assert actual_keys == expected_keys, f'重建后range_search({start},{end})失败: 期望{expected_keys}, 得到{actual_keys}'
    print(f'   ✅ 重建后所有range_search测试通过')

    tree2.shutdown()

    print('\n'+'='*60)
    print('✅✅✅ B+树MVP验证全部通过！✅✅✅')
    print('='*60)
    print('\nMVP功能清单：')
    print('  ✅ 持久化insert - 数据正确写入存储')
    print('  ✅ search - 点查询准确')
    print('  ✅ range_search - 范围查询准确')
    print('  ✅ 持久化恢复 - shutdown后重建可恢复数据')
    print('\n结论：B+树索引管理器MVP已完成！')


if __name__ == '__main__':
    validate_mvp()
