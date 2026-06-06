#!/usr/bin/env python
"""调试shutdown和重建"""

from src.index.serializer import PersistentBPlusTree
from src.core.buffer import BufferPool
from src.core.storage_interface import InMemoryStorage

storage = InMemoryStorage(page_size=4096)
buffer = BufferPool(num_frames=100, storage_engine=storage)
tree = PersistentBPlusTree(buffer_pool=buffer, order=4)

# 插入少量数据
tree.insert(1, (10, 0))
tree.insert(2, (20, 0))
tree.insert(3, (30, 0))

print(f'插入后: root_page_id={tree.root_page_id}, size={tree.size}')
print(f'缓存节点: {list(tree.node_cache.keys())}')

# 写回所有节点但不shutdown
for pid, node in list(tree.node_cache.items()):
    tree._flush_node(node)
print(f'写回后缓存: {list(tree.node_cache.keys())}')

# 检查持久化存储中是否有数据
print(f'\nBufferPool page allocator最高ID: {buffer.storage.get_highest_page_id()}')
for pid in range(buffer.storage.get_highest_page_id() + 1):
    page = buffer.storage.read_page(pid)
    if page and any(page.data):
        print(f'  page {pid} 有数据')

root_pid = tree.root_page_id
tree.shutdown()
print(f'\nshutdown后: root_page_id={root_pid}, 缓存: {list(tree.node_cache.keys())}')

# 重建
tree2 = PersistentBPlusTree(buffer_pool=buffer, order=4, root_page_id=root_pid)
print(f'\n重建后: root_page_id={tree2.root_page_id}, size={tree2.size}')
print(f'重建缓存: {list(tree2.node_cache.keys())}')
print(f'node_cache中的节点:')
for pid, node in tree2.node_cache.items():
    print(f'  {pid}: type={type(node).__name__}, keys={node.keys}')
