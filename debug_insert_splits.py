#!/usr/bin/env python
"""跟踪插入导致的分裂过程"""

from src.index.serializer import PersistentBPlusTree
from src.core.buffer import BufferPool
from src.core.storage_interface import InMemoryStorage

storage = InMemoryStorage(page_size=4096)
buffer = BufferPool(num_frames=100, storage_engine=storage)
tree = PersistentBPlusTree(buffer_pool=buffer, order=4)

# 插一个会分裂的序列
print('开始插入...')
for i in range(6):
    key = i
    tree.insert(key, (key*10, 0))
    print(f'\n插入 {key} 后:')
    for page_id, node in tree.node_cache.items():
        if node.is_leaf():
            print(f'  Leaf page_id={page_id}: keys={node.keys}')
            if node.next_leaf:
                nid = node.next_leaf.page_id if hasattr(node.next_leaf, 'page_id') else node.next_leaf
                print(f'    next_leaf: {nid}')

print(f'\n最终缓存节点数: {len(tree.node_cache)}')
for page_id, node in tree.node_cache.items():
    print(f'  page_id={page_id}: {type(node).__name__}, keys={node.keys}')
    if node.is_leaf():
        nxt = node.next_leaf
        if nxt:
            if isinstance(nxt, int):
                print(f'    next_leaf (int) = {nxt}')
            else:
                print(f'    next_leaf (obj) page_id={nxt.page_id}')
        else:
            print(f'    next_leaf = None')

tree.shutdown()
