#!/usr/bin/env python
"""详细跟踪分裂过程"""

from src.index.serializer import PersistentBPlusTree
from src.core.buffer import BufferPool
from src.core.storage_interface import InMemoryStorage

storage = InMemoryStorage(page_size=4096)
buffer = BufferPool(num_frames=50, storage_engine=storage)
tree = PersistentBPlusTree(buffer_pool=buffer, order=4)

print('根节点起始page_id:', tree.root_page_id)

# 批量插入到分裂
def log_state(tag):
    print(f'\n=== {tag} ===')
    print('缓存叶子节点:')
    for pid, node in tree.node_cache.items():
        if node.is_leaf():
            nxt = node.next_leaf
            nxt_info = 'None'
            if nxt is not None:
                if isinstance(nxt, int):
                    nxt_info = f'int({nxt})'
                else:
                    nxt_info = f'obj(page_id={nxt.page_id})'
            print(f'  Leaf pid={pid}: keys={node.keys}, next_leaf={nxt_info}')

    # 打印根节点
    root = tree._load_node(tree.root_page_id)
    if root and not root.is_leaf():
        print(f'根Internal: page_id={root.page_id}, keys={root.keys}')
        for i, child in enumerate(root.children):
            if isinstance(child, int):
                print(f'  child[{i}]: page_id={child}')
            else:
                print(f'  child[{i}]: node(page_id={child.page_id}, type={type(child).__name__})')

log_state('初始状态')

# 插入0 1 2 3触发第一次分裂
keys_to_insert = [0, 1, 2, 3]
for k in keys_to_insert:
    print(f'\n>>> 插入 {k}')
    tree.insert(k, (k*10, 0))
    log_state(f'插入{k}后')

tree.shutdown()
