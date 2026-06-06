#!/usr/bin/env python
"""调试range_search问题"""

from src.index.serializer import PersistentBPlusTree
from src.core.buffer import BufferPool
from src.core.storage_interface import InMemoryStorage

storage = InMemoryStorage(page_size=4096)
buffer = BufferPool(num_frames=150, storage_engine=storage)
tree = PersistentBPlusTree(buffer_pool=buffer, order=4)

# 插入测试数据
test_keys = sorted(set(list(range(0, 100, 5)) + [1, 3, 8, 12, 15, 18, 21, 22, 23, 26, 28]))
for k in test_keys:
    tree.insert(k, (k*10, 0))

print(f'插入完成，size={tree.size}')

# 手动遍历叶子节点链表
print('\n遍历叶子节点链表（模拟range_search）:')
start_key = 1
end_key = 30

leaf = tree._find_leaf(start_key)
print(f'起始叶子: page_id={leaf.page_id}, keys={leaf.keys}')

iteration = 0
while leaf:
    print(f'\n迭代 {iteration}:')
    print(f'  当前叶子 page_id={leaf.page_id}, keys={leaf.keys}')
    print(f'  leaf.next_leaf = {leaf.next_leaf}')
    print(f'  leaf.next_leaf 类型: {type(leaf.next_leaf).__name__}')

    # 检查next_leaf
    if leaf.next_leaf:
        if isinstance(leaf.next_leaf, int):
            print(f'    next_leaf 是整数: {leaf.next_leaf}')
        else:
            print(f'    next_leaf 是对象, page_id={getattr(leaf.next_leaf, "page_id", "无")}')
    else:
        print(f'    next_leaf 为 None')

    # 模拟range_search的过程
    for i, key in enumerate(leaf.keys):
        if key < start_key:
            print(f'    跳过 key={key} (< start_key)')
            continue
        if key > end_key:
            print(f'    跳出: key={key} > end_key={end_key}')
            break
        print(f'    收集 key={key}')

    # 移动到下一个
    old_page_id = getattr(leaf, 'page_id', None)
    if leaf.next_leaf:
        next_page_id = getattr(leaf.next_leaf, 'page_id', None)
        if next_page_id:
            leaf = tree._load_node(next_page_id)
        else:
            print(f'    next_leaf对象没有page_id属性！')
            leaf = None
    else:
        leaf = None

    iteration += 1
    if iteration > 10:
        print('警告：迭代超过10次')
        break

# 测试实际的range_search
print('\n\n实际调用 tree.range_search(1, 30):')
results = tree.range_search(1, 30)
print(f'结果: {[(k,v) for k,v in results]}')
print(f'keys: {[k for k,v in results]}')

tree.shutdown()
