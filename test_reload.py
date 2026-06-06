from src.index.serializer import PersistentBPlusTree
from src.core.buffer import BufferPool
from src.core.storage_interface import InMemoryStorage

storage = InMemoryStorage(page_size=4096)
buffer = BufferPool(num_frames=100, storage_engine=storage)
tree = PersistentBPlusTree(buffer_pool=buffer, order=4)

tree.insert(1, (10, 0))
tree.insert(2, (20, 0))
tree.insert(3, (30, 0))

print(f'插入后: root_page_id={tree.root_page_id}, size={tree.size}')
print(f'缓存节点: {list(tree.node_cache.keys())}')

for pid, node in list(tree.node_cache.items()):
    tree._flush_node(node)

root_pid = tree.root_page_id
tree.shutdown()

print(f'shutdown后 root_page_id={root_pid}')

tree2 = PersistentBPlusTree(buffer_pool=buffer, order=4, root_page_id=root_pid)
print(f'重建后: root_page_id={tree2.root_page_id}, size={tree2.size}')
print(f'重建缓存: {list(tree2.node_cache.keys())}')
for pid, node in tree2.node_cache.items():
    print(f'  {pid}: type={type(node).__name__}, keys={node.keys}')
    if hasattr(node, 'parent'):
        print(f'      parent: {node.parent}')
