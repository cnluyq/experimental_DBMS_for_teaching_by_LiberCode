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

root_pid = tree.root_page_id
tree.shutdown()

tree2 = PersistentBPlusTree(buffer_pool=buffer, order=4, root_page_id=root_pid)
print(f'重建后: size={tree2.size}')

# 验证search
for k in [1,2,3]:
    v = tree2.search(k)
    print(f'  search({k}) = {v}')

# 验证range_search
results = tree2.range_search(1, 3)
print(f'  range_search(1,3) = {results}')

tree2.shutdown()
