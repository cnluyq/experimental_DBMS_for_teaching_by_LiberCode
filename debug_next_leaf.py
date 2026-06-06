#!/usr/bin/env python
"""调试叶子节点链表连接问题"""

from src.index.serializer import PersistentBPlusTree
from src.core.buffer import BufferPool
from src.core.storage_interface import InMemoryStorage

storage = InMemoryStorage(page_size=4096)
buffer = BufferPool(num_frames=200, storage_engine=storage)
tree = PersistentBPlusTree(buffer_pool=buffer, order=4)

# 插入测试数据
test_keys = [0, 1, 3, 5, 8, 10]
for k in test_keys:
    tree.insert(k, (k*10, 0))

print(f'插入完成，size={tree.size}')

# 检查所有缓存中的节点
print('\n缓存节点:')
for page_id, node in tree.node_cache.items():
    if node.is_leaf():
        print(f'  Leaf page_id={page_id}: keys={node.keys}')
        if node.next_leaf:
            if isinstance(node.next_leaf, int):
                print(f'    next_leaf_page_id (int): {node.next_leaf}')
            else:
                print(f'    next_leaf.page_id={getattr(node.next_leaf, "page_id", "N/A")}')
        else:
            print(f'    next_leaf=None')

# 强制写回并重新加载查看
print('\n写回所有节点并检查持久化存储:')
for page_id, node in list(tree.node_cache.items()):
    tree._flush_node(node)

tree.shutdown()

# 重新打开看看
tree2 = PersistentBPlusTree(buffer_pool=buffer, order=4, root_page_id=tree.root_page_id)
print(f'\n重新打开后缓存节点:')
for page_id, node in tree2.node_cache.items():
    if node.is_leaf():
        print(f'  Leaf page_id={page_id}: keys={node.keys}')
        if node.next_leaf:
            if isinstance(node.next_leaf, int):
                print(f'    next_leaf_page_id (int): {node.next_leaf}')
            else:
                print(f'    next_leaf.page_id={getattr(node.next_leaf, "page_id", "N/A")}')
        else:
            print(f'    next_leaf=None')

tree2.shutdown()
