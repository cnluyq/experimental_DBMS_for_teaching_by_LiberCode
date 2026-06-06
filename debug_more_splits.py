#!/usr/bin/env python
"""跟踪多次分裂"""

from src.index.serializer import PersistentBPlusTree
from src.core.buffer import BufferPool
from src.core.storage_interface import InMemoryStorage

storage = InMemoryStorage(page_size=4096)
buffer = BufferPool(num_frames=100, storage_engine=storage)
tree = PersistentBPlusTree(buffer_pool=buffer, order=4)

def log_state(tag):
    print(f'\n=== {tag} ===')
    print('叶子节点链表:')
    leaf_order = []
    for pid, node in tree.node_cache.items():
        if node.is_leaf():
            nxt = node.next_leaf
            nxt_id = None
            if nxt is not None:
                if isinstance(nxt, int):
                    nxt_id = nxt
                else:
                    nxt_id = nxt.page_id if hasattr(nxt, 'page_id') else 'obj'
            print(f'  Leaf pid={pid}: keys={node.keys}, next_leaf={nxt_id}')
            leaf_order.append((pid, node.keys, nxt_id))

    # 尝试按next_leaf重建链表
    print('\n重建链表顺序:')
    if leaf_order:
        start_pid = leaf_order[0][0]
        visited = set()
        current_pid = start_pid
        while current_pid and current_pid not in visited:
            visited.add(current_pid)
            found = False
            for pid, keys, nxt_id in leaf_order:
                if pid == current_pid:
                    print(f'  pid={pid}: {keys}')
                    current_pid = nxt_id
                    found = True
                    break
            if not found:
                print(f'  pid={current_pid} 不在缓存中')
                break
            if len(visited) > 20:
                print('  太多叶子节点，停止')
                break

# 插入前7个键触发多次分裂
keys = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
for k in keys:
    tree.insert(k, (k*10, 0))
    log_state(f'插入{k}后')

tree.shutdown()
