"""
B+树节点序列化/反序列化

将内存中的B+树节点转换为字节流，以便持久化存储
"""

import struct
from typing import BinaryIO, List, Any, Optional
from .bplus_node import BPlusNode, NodeType, InternalNode, LeafNode


# 页面布局常量
PAGE_SIZE = 4096
MAGIC_NUMBER = 0x424C5553  # 'BLUS' or simpler: use 0xB455 (or just choose 0x12345678)
# 使用一个简单的整数作为标识
MAGIC_NUMBER = 0xBADF00D  # "BAD F00D" - a fun magic number

# 头部格式（固定编码）：
# magic: I (4 bytes)
# node_type: B (1 byte) - 1=INTERNAL, 2=LEAF
# key_count: H (2 bytes) - 键数量
# parent_id: I (4 bytes) - 父节点page_id，0表示无
# reserved: I (4 bytes) - 保留字段
HEADER_FORMAT = 'IBHII'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

# 键和值采用固定长度编码（简化教学）
KEY_SIZE = 8  # 8字节整数或短字符串
VALUE_SIZE = 8  # record_id: (page_id, slot_id) → 4+4字节


class BPlusTreeSerializer:
    """B+树序列化器（固定格式）"""
    
    def __init__(self, order: int = 4):
        self.order = order
    
    def serialize_node(self, node: BPlusNode, page_id: int) -> bytes:
        """
        序列化节点为页面大小的字节流
        
        Args:
            node: B+树节点
            page_id: 节点所属页面ID
            
        Returns:
            填充到PAGE_SIZE的字节数据
        """
        data = bytearray(PAGE_SIZE)
        offset = 0
        
        # 写入头部
        node_type_val = 1 if node.node_type == NodeType.INTERNAL else 2
        parent_id = getattr(node.parent, 'page_id', 0) if node.parent else 0
        
        struct.pack_into(HEADER_FORMAT, data, offset,
                         MAGIC_NUMBER,
                         node_type_val,
                         len(node.keys),
                         parent_id,
                         0)  # reserved
        offset += HEADER_SIZE
        
        # 序列化键（固定8字节）
        for key in node.keys:
            key_bytes = self._encode_key(key)
            assert len(key_bytes) == KEY_SIZE
            data[offset:offset+KEY_SIZE] = key_bytes
            offset += KEY_SIZE
        
        # 根据节点类型序列化
        if node.is_leaf():
            leaf = node  # type: LeafNode
            # 序列化值（record_id）
            for value in leaf.values:
                value_bytes = self._encode_value(value)
                assert len(value_bytes) == VALUE_SIZE
                data[offset:offset+VALUE_SIZE] = value_bytes
                offset += VALUE_SIZE
            
            # 保存next_leaf的page_id（如果有）
            next_page_id = getattr(leaf.next_leaf, 'page_id', 0) if leaf.next_leaf else 0
            struct.pack_into('I', data, offset, next_page_id)
            offset += 4
        else:
            internal = node  # type: InternalNode
            # 序列化子节点page_id（num_keys + 1个）
            for child in internal.children:
                child_page_id = getattr(child, 'page_id', 0)
                struct.pack_into('I', data, offset, child_page_id)
                offset += 4
        
        # 填充剩余空间
        # offset 应该是 <= PAGE_SIZE
        return bytes(data)
    
    def deserialize_node(self, data: bytes, page_id: int) -> Optional[BPlusNode]:
        """
        从字节流反序列化节点
        
        Args:
            data: 页面数据
            page_id: 页面ID（用于设置node.page_id）
            
        Returns:
            反序列化后的节点，失败返回None
        """
        if len(data) < HEADER_SIZE:
            return None
        
        offset = 0
        magic, node_type_val, num_keys, parent_id, reserved = struct.unpack_from(
            HEADER_FORMAT, data, offset)
        offset += HEADER_SIZE
        
        if magic != MAGIC_NUMBER:
            return None
        
        # 确定节点类型
        if node_type_val == 1:  # INTERNAL
            node = InternalNode(self.order)
        elif node_type_val == 2:  # LEAF
            node = LeafNode(self.order)
        else:
            return None
        
        node.page_id = page_id
        node.parent = None  # 稍后重建
        
        # 反序列化键
        node.keys = []
        for _ in range(num_keys):
            if offset + KEY_SIZE > len(data):
                return None
            key_bytes = data[offset:offset+KEY_SIZE]
            key = self._decode_key(key_bytes)
            node.keys.append(key)
            offset += KEY_SIZE
        
        # 根据类型反序列化
        if node.is_leaf():
            leaf = node
            leaf.values = []
            
            # 读取record_id（8字节）
            for _ in range(num_keys):
                if offset + VALUE_SIZE > len(data):
                    return None
                value_bytes = data[offset:offset+VALUE_SIZE]
                value = self._decode_value(value_bytes)
                leaf.values.append(value)
                offset += VALUE_SIZE
            
            # 读取next_leaf page_id
            if offset + 4 <= len(data):
                next_page_id = struct.unpack_from('I', data, offset)[0]
                leaf.next_leaf = next_page_id if next_page_id != 0 else None
                offset += 4
        else:
            internal = node
            internal.children = []
            
            # 读取子节点page_id（num_keys + 1个）
            num_children = num_keys + 1
            for _ in range(num_children):
                if offset + 4 > len(data):
                    return None
                child_page_id = struct.unpack_from('I', data, offset)[0]
                offset += 4
                internal.children.append(child_page_id)  # 存储page_id而非对象
        
        return node
    
    def _encode_key(self, key: Any) -> bytes:
        """编码键为8字节"""
        if isinstance(key, int):
            return struct.pack('q', key)  # signed long long
        elif isinstance(key, str):
            encoded = key.encode('utf-8')[:4]
            length = len(encoded)
            return struct.pack('I', length) + encoded.ljust(4, b'\x00')
        else:
            raise TypeError(f"Unsupported key type: {type(key)}")
    
    def _decode_key(self, data: bytes) -> Any:
        """从8字节解码键"""
        # 尝试整数
        try:
            return struct.unpack('q', data[:8])[0]
        except:
            pass
        
        # 尝试字符串（前4字节是长度）
        try:
            length = struct.unpack('I', data[:4])[0]
            if 0 < length <= 4:
                return data[4:4+length].decode('utf-8', errors='ignore')
        except:
            pass
        
        return 0
    
    def _encode_value(self, value: Any) -> bytes:
        """编码值为8字节"""
        if isinstance(value, tuple) and len(value) == 2:
            page_id, slot_id = value
            return struct.pack('II', page_id, slot_id)
        elif isinstance(value, int):
            return struct.pack('Q', value)
        elif isinstance(value, str):
            # 支持短字符串（最多8字节）
            encoded = value.encode('utf-8')[:8]
            length = len(encoded)
            return struct.pack('I', length) + encoded.ljust(4, b'\x00')[:4]
        else:
            raise TypeError(f"Unsupported value type: {type(value)}")
    
    def _decode_value(self, data: bytes) -> Any:
        """从8字节解码值"""
        # 尝试 record_id 格式 (page_id, slot_id)
        if len(data) >= 8:
            try:
                page_id, slot_id = struct.unpack('II', data[:8])
                return (page_id, slot_id)
            except:
                try:
                    # 尝试大整数
                    return struct.unpack('Q', data[:8])[0]
                except:
                    pass
        
        # 尝试字符串（前4字节是长度）
        if len(data) >= 4:
            try:
                length = struct.unpack('I', data[:4])[0]
                if 0 < length <= 4:
                    return data[4:4+length].decode('utf-8', errors='ignore')
            except:
                pass
        
        return 0


# 元数据页面格式
METADATA_MAGIC = 0x42545245  # 'BTRE' for B+Tree Root Entry
METADATA_FORMAT = 'III'  # magic, size, root_page_id
METADATA_SIZE = struct.calcsize(METADATA_FORMAT)


class PersistentBPlusTree:
    """
    持久化B+树（集成缓冲区管理器）
    
    功能：
    - 使用缓冲区管理器读写页面
    - 节点page_id管理
    - 分裂/合并时页面分配/释放
    - 保持所有节点的page_id和parent指针同步
    - 元数据持久化（size, root_page_id）
    """
    
    # 元数据页面ID（固定的第一个页面）
    METADATA_PAGE_ID = 0
    
    def __init__(self, buffer_pool, order: int = 4, root_page_id: int = 0):
        """
        初始化持久化B+树
        
        Args:
            buffer_pool: 缓冲区管理器实例（提供read_page, create_page, allocate_page等）
            order: B+树阶数
            root_page_id: 根节点页面ID，0表示新建树
        """
        self.buffer = buffer_pool
        self.order = order
        self.serializer = BPlusTreeSerializer(order)
        self.size = 0
        self.min_keys = (order // 2) - 1 if order % 2 == 0 else (order // 2)
        
        # 节点缓存：page_id -> BPlusNode（内存中）
        self.node_cache = {}
        
        if root_page_id == 0:
            # 尝试从元数据页面加载（可能已有持久化的树）
            if self._load_metadata():
                # 成功加载了元数据，size和root_page_id已恢复
                pass
            else:
                # 创建新的空树
                self.root_page_id = self._create_new_root()
                self._save_metadata()
        else:
            self.root_page_id = root_page_id
            # 加载元数据（恢复size）
            self._load_metadata()
            # 加载根节点
            self._load_node(self.root_page_id)
    
    def _save_metadata(self):
        """保存元数据到固定页面（root_page_id + size）"""
        data = bytearray(PAGE_SIZE)
        struct.pack_into(METADATA_FORMAT, data, 0,
                         METADATA_MAGIC, self.size, self.root_page_id)
        
        # 写入元数据页面
        frame = self.buffer.read_page(self.METADATA_PAGE_ID, pin=True)
        if frame is None:
            # 元数据页面不存在，创建
            self.buffer.create_page(self.METADATA_PAGE_ID, bytes(data), pin=False)
        else:
            frame.data[:] = data
            frame.dirty = True
            self.buffer.unpin_page(self.METADATA_PAGE_ID)
    
    def _load_metadata(self) -> bool:
        """
        从固定页面加载元数据
        
        Returns:
            是否成功加载（如果元数据页面不存在返回False）
        """
        try:
            frame = self.buffer.read_page(self.METADATA_PAGE_ID, pin=True)
            if frame is None:
                return False
            
            data = bytes(frame.data)
            magic, size, root_page_id = struct.unpack_from(METADATA_FORMAT, data, 0)
            
            if magic != METADATA_MAGIC:
                self.buffer.unpin_page(self.METADATA_PAGE_ID)
                return False
            
            self.size = size
            self.root_page_id = root_page_id
            
            self.buffer.unpin_page(self.METADATA_PAGE_ID)
            return True
        except:
            return False
    
    def _create_new_root(self) -> int:
        """创建新的根节点（叶子节点）"""
        # 分配页面ID（通过缓冲区管理器的存储引擎）
        page_id = self.buffer.storage.allocate_page()
        
        # 创建空叶子节点
        root = LeafNode(self.order)
        root.page_id = page_id
        
        # 缓存节点
        self.node_cache[page_id] = root
        
        # 序列化并写入页面
        self._flush_node(root)
        
        return page_id
    
    def _load_node(self, page_id: int) -> Optional[BPlusNode]:
        """从持久化加载节点"""
        if page_id in self.node_cache:
            return self.node_cache[page_id]
        
        frame = self.buffer.read_page(page_id, pin=True)
        if frame is None:
            return None
        
        node = self.serializer.deserialize_node(bytes(frame.data), page_id)
        if node is None:
            self.buffer.unpin_page(page_id)
            return None
        
        self.node_cache[page_id] = node
        return node
    
    def _unload_node(self, page_id: int):
        """从缓存移除节点（并写回如果脏）"""
        if page_id in self.node_cache:
            # 标记页面脏（如果需要持久化）
            self.buffer.mark_dirty(page_id)
            self.buffer.unpin_page(page_id)
            del self.node_cache[page_id]
    
    def _flush_node(self, node: BPlusNode):
        """将节点写回持久化存储"""
        if not hasattr(node, 'page_id') or node.page_id is None:
            raise ValueError("Node has no page_id")
        
        # 序列化前，确保父子关系正确（用于parent_id字段）
        # 注意：serializer会读取 node.parent.page_id
        data = self.serializer.serialize_node(node, node.page_id)
        
        # 获取或创建页面
        frame = self.buffer.read_page(node.page_id, pin=True)
        if frame is None:
            # 页面不存在，创建新页面
            frame = self.buffer.create_page(node.page_id, data, pin=True)
            if frame is None:
                raise RuntimeError(f"Failed to create page {node.page_id}")
        else:
            # 更新现有页面
            frame.data[:] = data
            frame.dirty = True
        
        self.buffer.unpin_page(node.page_id)
    
    def _allocate_page_for_node(self) -> int:
        """分配新页面用于存储节点"""
        page_id = self.buffer.storage.allocate_page()
        return page_id
    
    def _free_page(self, page_id: int):
        """释放页面（从树中移除）"""
        # 从缓存移除
        self._unload_node(page_id)
        # TODO: 更完善的页面回收机制（需要维护空闲列表）
        # 这里简化：不实际删除文件页面，只是从树中移除引用
    
    def _set_parent_pointer(self, child: BPlusNode, parent: BPlusNode):
        """设置父子关系"""
        child.parent = parent
        # 如果是内部节点，还需要设置所有子节点的父指针
        if child.is_leaf():
            return
        internal = child  # type: InternalNode
        for ch in internal.children:
            if isinstance(ch, BPlusNode):
                ch.parent = child
    
    def _reconnect_children(self, parent: InternalNode):
        """重新连接内部节点的子节点（通过page_id）"""
        new_children = []
        for child_ref in parent.children:
            if isinstance(child_ref, int):
                # child_ref是page_id，需要加载
                child_node = self._load_node(child_ref)
                if child_node:
                    child_node.parent = parent
                    new_children.append(child_node)
                else:
                    raise RuntimeError(f"Failed to load child page {child_ref}")
            else:
                # 已经是节点对象，确保parent正确
                child_ref.parent = parent
                new_children.append(child_ref)
        
        parent.children = new_children
    
    def _ensure_page_id(self, node: BPlusNode, page_id: int = None) -> int:
        """确保节点有page_id，如果没有则分配"""
        if page_id is not None:
            node.page_id = page_id
        elif not hasattr(node, 'page_id') or node.page_id is None:
            node.page_id = self._allocate_page_for_node()
        return node.page_id
    
    def _set_parent_page_id(self, child: BPlusNode, parent_page_id: int):
        """设置子节点的父节点page_id（在序列化中保存）"""
        # 实际父节点对象由parent指针维护，这里只用于序列化时的parent_id字段
        # 在序列化时，我们使用 child.parent.page_id
        pass
    
    def search(self, key: Any) -> Optional[Any]:
        """查找键对应的值"""
        # 从根节点开始向下遍历
        node = self._load_node(self.root_page_id)
        if node is None:
            return None
        
        while not node.is_leaf():
            internal = node  # type: InternalNode
            # 确保子节点已加载
            self._reconnect_children(internal)
            
            child_idx = internal.find_child_index(key)
            child = internal.children[child_idx]
            
            # child 应该是 BPlusNode 对象
            if isinstance(child, int):
                # 如果还是整数，加载（理论上不应发生）
                child = self._load_node(child)
                if child is None:
                    return None
                internal.children[child_idx] = child
                child.parent = internal
            
            node = child
        
        # 到达叶子节点
        leaf = node  # type: LeafNode
        try:
            idx = leaf.keys.index(key)
            return leaf.values[idx]
        except ValueError:
            return None
    
    def range_search(self, start_key: Any, end_key: Any) -> List[tuple]:
        """范围查询"""
        results = []
        
        # 找到起始叶子节点
        leaf = self._find_leaf(start_key)
        if leaf is None:
            return results
        
        current = leaf
        while current is not None:
            for i, k in enumerate(current.keys):
                if k < start_key:
                    continue
                if k > end_key:
                    break
                results.append((k, current.values[i]))
            
            # 移动到下一个叶子节点
            # next_leaf可能是LeafNode对象或page_id整数
            if current.next_leaf:
                if isinstance(current.next_leaf, int):
                    # next_leaf存储的是page_id
                    next_page_id = current.next_leaf
                    if next_page_id and next_page_id != 0:
                        current = self._load_node(next_page_id)
                    else:
                        current = None
                else:
                    # next_leaf是LeafNode对象
                    next_page_id = getattr(current.next_leaf, 'page_id', None)
                    if next_page_id:
                        current = self._load_node(next_page_id)
                    else:
                        current = None
            else:
                current = None
        
        return results
    
    def _find_leaf(self, key: Any) -> Optional[LeafNode]:
        """查找应该包含key的叶子节点"""
        node = self._load_node(self.root_page_id)
        if node is None:
            return None
        
        while not node.is_leaf():
            internal = node  # type: InternalNode
            # 确保子节点已加载为节点对象
            self._reconnect_children(internal)
            
            child_idx = internal.find_child_index(key)
            child_ref = internal.children[child_idx]
            
            # child_ref 应该是 BPlusNode 对象
            if isinstance(child_ref, int):
                # 如果还是整数，说明_reconnect_children没有完全处理？应该不会
                child = self._load_node(child_ref)
                if child is None:
                    return None
                # 更新 children 数组
                internal.children[child_idx] = child
                child.parent = internal
            else:
                child = child_ref
            
            node = child
        
        return node  # type: LeafNode
    
    def insert(self, key: Any, value: Any) -> bool:
        """
        插入键值对（持久化）
        
        Returns:
            成功返回True，失败返回False（如键已存在）
        """
        # 1. 加载根节点
        if self.root_page_id is None or self.root_page_id == 0:
            self.root_page_id = self._create_new_root()
        
        root = self._load_node(self.root_page_id)
        if root is None:
            return False
        
        # 2. 找到目标叶子节点
        leaf = self._find_leaf(key)
        if leaf is None:
            return False
        
        # 3. 检查键是否已存在
        try:
            index = leaf.keys.index(key)
            # 键已存在，更新值
            leaf.values[index] = value
            self._flush_node(leaf)
            return True
        except ValueError:
            # 键不存在，继续插入
            pass
        
        # 4. 插入到叶子节点
        leaf.insert_entry(key, value)
        self.size += 1
        
        # 5. 检查是否需要分裂（叶子节点满）
        if leaf.is_full():
            self._split_and_propagate(leaf)
        else:
            # 节点未满，直接写回
            self._flush_node(leaf)
        
        # 6. 保存元数据（持久化size）
        self._save_metadata()
        
        return True
    
    def _split_and_propagate(self, leaf: LeafNode):
        """
        从叶子节点开始分裂并递归向上处理
        
        Args:
            leaf: 需要分裂的叶子节点
        """
        # 分裂叶子节点
        middle_key, new_leaf = leaf.split()
        
        # 确保新叶子节点有页面ID并写回
        new_leaf_page_id = self._allocate_page_for_node()
        new_leaf.page_id = new_leaf_page_id
        new_leaf.parent = leaf.parent  # 将在父节点设置
        
        # 写回两个叶子节点
        self._flush_node(leaf)
        self._flush_node(new_leaf)
        
        # 如果叶子节点是根（无父节点），创建新的内部根节点
        if leaf.parent is None:
            new_root = InternalNode(self.order)
            new_root_page_id = self._allocate_page_for_node()
            new_root.page_id = new_root_page_id
            
            new_root.keys = [middle_key]
            new_root.children = [leaf, new_leaf]
            
            leaf.parent = new_root
            new_leaf.parent = new_root
            
            self.root_page_id = new_root_page_id
            self.node_cache[new_root_page_id] = new_root
            
            self._flush_node(new_root)
        else:
            # 将中间键和新叶子节点插入父节点
            parent = leaf.parent  # type: InternalNode
            # 确保父节点的子节点已加载（重新连接）
            self._reconnect_children(parent)
            self._insert_into_internal(parent, middle_key, new_leaf)
    
    def _insert_into_internal(self, parent: InternalNode, key: Any, right_child: BPlusNode):
        """
        向内部节点插入键和新子节点
        
        Args:
            parent: 父内部节点
            key: 要插入的键（来自分裂）
            right_child: 新的右侧子节点
        """
        # 确保父节点的子节点已加载
        self._reconnect_children(parent)
        
        # 找到插入位置
        index = parent.find_child_index(key)
        
        # 插入键和子节点
        parent.keys.insert(index, key)
        parent.children.insert(index + 1, right_child)
        right_child.parent = parent
        
        # 写回父节点
        self._flush_node(parent)
        
        # 检查父节点是否溢出
        if parent.is_full():
            self._split_internal_and_propagate(parent)
    
    def _split_internal_and_propagate(self, internal: InternalNode):
        """
        分裂内部节点并递归向上
        
        Args:
            internal: 需要分裂的内部节点
        """
        # 确保当前内部节点的子节点已连接
        self._reconnect_children(internal)
        
        # 分裂内部节点
        middle_key, new_internal = internal.split()
        
        # 确保新内部节点有页面ID
        new_internal_page_id = self._allocate_page_for_node()
        new_internal.page_id = new_internal_page_id
        new_internal.parent = internal.parent
        
        # 写回两个内部节点
        self._flush_node(internal)
        self._flush_node(new_internal)
        
        # 处理父节点
        if internal.parent is None:
            # 创建新的根内部节点
            new_root = InternalNode(self.order)
            new_root_page_id = self._allocate_page_for_node()
            new_root.page_id = new_root_page_id
            
            new_root.keys = [middle_key]
            new_root.children = [internal, new_internal]
            
            internal.parent = new_root
            new_internal.parent = new_root
            
            self.root = new_root
            self.root_page_id = new_root_page_id
            
            self._flush_node(new_root)
        else:
            # 将中间键和新内部节点插入到父内部节点
            parent = internal.parent
            self._insert_into_internal(parent, middle_key, new_internal)
    
    def delete(self, key: Any) -> bool:
        """
        删除键（持久化）
        
        Returns:
            成功返回True，失败返回False（如键不存在）
        """
        # 1. 检查根节点
        if self.root_page_id is None:
            return False
        
        # 2. 查找包含key的叶子节点
        leaf = self._find_leaf(key)
        if leaf is None:
            return False
        
        # 3. 删除键值对
        deleted_value = leaf.delete_entry(key)
        if deleted_value is None:
            return False  # 键不存在
        
        self.size -= 1
        
        # 4. 写回叶子节点（已修改）
        self._flush_node(leaf)
        
        # 5. 检查是否需要下溢处理
        if leaf.is_underflow():
            self._handle_leaf_underflow(leaf)
        
        # 6. 检查根节点是否需要调整
        self._adjust_root()
        
        return True
    
    def _handle_leaf_underflow(self, leaf: LeafNode):
        """处理叶子节点下溢（持久化）"""
        parent = leaf.parent
        if parent is None:
            return  # 根节点特殊处理
        
        # 确保父节点的子节点已加载
        self._reconnect_children(parent)
        
        # 找到leaf在父节点中的索引
        index = parent.children.index(leaf)
        
        # 尝试向兄弟借条目
        # 1. 尝试向左兄弟借（如果存在且有多余键）
        if index > 0:
            left_sibling = parent.children[index - 1]  # type: LeafNode
            if len(left_sibling.keys) > self.min_keys:
                self._borrow_from_left_leaf(leaf, left_sibling, parent, index)
                # 借调后需要更新父节点的分隔键
                parent.keys[index - 1] = left_sibling.keys[-1]
                self._flush_node(parent)
                return
        
        # 2. 尝试向右兄弟借（如果存在且有多余键）
        if index < len(parent.children) - 1:
            right_sibling = parent.children[index + 1]  # type: LeafNode
            if len(right_sibling.keys) > self.min_keys:
                self._borrow_from_right_leaf(leaf, right_sibling, parent, index)
                # 借调后需要更新父节点的分隔键
                parent.keys[index] = right_sibling.keys[0]
                self._flush_node(parent)
                return
        
        # 3. 与兄弟合并
        # 如果右兄弟存在，与右兄弟合并；否则与左兄弟合并
        if index < len(parent.children) - 1:
            right_sibling = parent.children[index + 1]  # type: LeafNode
            self._merge_leaf_nodes(leaf, right_sibling, parent, index)
        else:
            left_sibling = parent.children[index - 1]  # type: LeafNode
            self._merge_leaf_nodes(left_sibling, leaf, parent, index - 1)
    
    def _borrow_from_left_leaf(self, deficient: LeafNode, left_sibling: LeafNode,
                               parent: InternalNode, index: int):
        """从左兄弟叶子借一个条目"""
        # 将左兄弟的最大键值对移动到 deficient 的开头
        borrowed_key = left_sibling.keys.pop()
        borrowed_value = left_sibling.values.pop()
        
        deficient.keys.insert(0, borrowed_key)
        deficient.values.insert(0, borrowed_value)
        
        # 写回左右兄弟
        self._flush_node(left_sibling)
        self._flush_node(deficient)
        
        # 父节点分隔键更新在调用方处理
    
    def _borrow_from_right_leaf(self, deficient: LeafNode, right_sibling: LeafNode,
                                parent: InternalNode, index: int):
        """从右兄弟叶子借一个条目"""
        # 将右兄弟的最小键值对移动到 deficient 的末尾
        borrowed_key = right_sibling.keys.pop(0)
        borrowed_value = right_sibling.values.pop(0)
        
        deficient.keys.append(borrowed_key)
        deficient.values.append(borrowed_value)
        
        # 写回左右兄弟
        self._flush_node(deficient)
        self._flush_node(right_sibling)
        
        # 父节点分隔键更新在调用方处理
    
    def _merge_leaf_nodes(self, left: LeafNode, right: LeafNode,
                          parent: InternalNode, index: int):
        """
        合并两个叶子节点
        
        Args:
            left: 左叶子节点（保留）
            right: 右叶子节点（合并到左节点后删除）
            parent: 父节点
            index: right在parent.children中的索引
        """
        # 合并右节点到左节点
        left.keys.extend(right.keys)
        left.values.extend(right.values)
        
        # 更新兄弟指针
        left.next_leaf = right.next_leaf
        if right.next_leaf:
            right.next_leaf.prev_leaf = left
        
        # 写回左节点
        self._flush_node(left)
        
        # 从父节点删除分隔键和右节点
        parent.keys.pop(index)
        parent.children.pop(index + 1)
        
        # 释放右节点的页面
        self._free_page(right.page_id)
        
        # 更新父节点分隔键（如果还有右侧子节点）
        if index < len(parent.keys):
            parent.keys[index] = left.keys[-1]
        
        self._flush_node(parent)
        
        # 递归检查父节点是否下溢
        if parent.is_underflow():
            if parent.parent is None:
                self._handle_internal_root_underflow(parent)
            else:
                self._handle_internal_underflow(parent)
    
    def _handle_internal_underflow(self, internal: InternalNode):
        """处理内部节点下溢（持久化）"""
        parent = internal.parent
        if parent is None:
            return
        
        # 确保父节点的子节点已加载
        self._reconnect_children(parent)
        
        index = parent.children.index(internal)
        
        # 尝试向兄弟借
        if index > 0:
            left_sibling = parent.children[index - 1]  # type: InternalNode
            if len(left_sibling.keys) > self.min_keys:
                self._borrow_from_left_internal(internal, left_sibling, parent, index)
                return
        
        if index < len(parent.children) - 1:
            right_sibling = parent.children[index + 1]  # type: InternalNode
            if len(right_sibling.keys) > self.min_keys:
                self._borrow_from_right_internal(internal, right_sibling, parent, index)
                return
        
        # 合并
        if index < len(parent.children) - 1:
            right_sibling = parent.children[index + 1]  # type: InternalNode
            self._merge_internal_nodes(internal, right_sibling, parent, index)
        else:
            left_sibling = parent.children[index - 1]  # type: InternalNode
            self._merge_internal_nodes(left_sibling, internal, parent, index - 1)
    
    def _borrow_from_left_internal(self, deficient: InternalNode, left_sibling: InternalNode,
                                    parent: InternalNode, index: int):
        """从左内部节点借键"""
        # 父节点中对应的分隔键
        separator = parent.keys[index - 1]
        
        # 将左兄弟的最后一个子节点移到 deficient 的开头
        borrowed_key = left_sibling.keys.pop()
        borrowed_child_page_id = left_sibling.children.pop()  # 可能是 page_id 或 node
        # 加载子节点（如果是 page_id）
        if isinstance(borrowed_child_page_id, int):
            borrowed_child = self._load_node(borrowed_child_page_id)
            if borrowed_child is None:
                raise RuntimeError(f"Failed to load child page {borrowed_child_page_id}")
            borrowed_child_page_id = borrowed_child
        else:
            borrowed_child = borrowed_child_page_id
        
        deficient.keys.insert(0, separator)
        deficient.children.insert(0, borrowed_child)
        borrowed_child.parent = deficient
        
        # 更新父节点分隔键：变为左兄弟新的最后一个键（如果还有）或borrowed_key
        if left_sibling.keys:
            parent.keys[index - 1] = left_sibling.keys[-1]
        else:
            parent.keys[index - 1] = borrowed_key
        
        # 写回
        self._flush_node(left_sibling)
        self._flush_node(deficient)
        self._flush_node(parent)
    
    def _borrow_from_right_internal(self, deficient: InternalNode, right_sibling: InternalNode,
                                     parent: InternalNode, index: int):
        """从右内部节点借键"""
        # 父节点中对应的分隔键
        separator = parent.keys[index]
        
        # 将右兄弟的第一个子节点移到 deficient 的末尾
        borrowed_key = right_sibling.keys.pop(0)
        borrowed_child_page_id = right_sibling.children.pop(0)
        # 加载子节点（如果是 page_id）
        if isinstance(borrowed_child_page_id, int):
            borrowed_child = self._load_node(borrowed_child_page_id)
            if borrowed_child is None:
                raise RuntimeError(f"Failed to load child page {borrowed_child_page_id}")
            borrowed_child_page_id = borrowed_child
        else:
            borrowed_child = borrowed_child_page_id
        
        deficient.keys.append(separator)
        deficient.children.append(borrowed_child)
        borrowed_child.parent = deficient
        
        # 更新父节点分隔键：变为右兄弟新的第一个键（如果还有）或borrowed_key
        if right_sibling.keys:
            parent.keys[index] = right_sibling.keys[0]
        else:
            parent.keys[index] = borrowed_key
        
        # 写回
        self._flush_node(deficient)
        self._flush_node(right_sibling)
        self._flush_node(parent)
    
    def _merge_internal_nodes(self, left: InternalNode, right: InternalNode,
                              parent: InternalNode, index: int):
        """合并两个内部节点"""
        # 合并右节点到左节点，需要插入父节点分隔键
        separator = parent.keys.pop(index)
        
        left.keys.append(separator)
        left.keys.extend(right.keys)
        left.children.extend(right.children)
        
        # 更新所有子节点的父指针
        for child in right.children:
            if isinstance(child, BPlusNode):
                child.parent = left
        
        # 写回左节点
        self._flush_node(left)
        
        # 从父节点删除右节点
        parent.children.pop(index + 1)
        
        # 释放右节点的页面
        self._free_page(right.page_id)
        
        # 更新父节点分隔键（如果还有右侧子节点）
        if index < len(parent.keys):
            parent.keys[index] = left.keys[-1]
        
        self._flush_node(parent)
        
        # 递归检查父节点
        if parent.is_underflow():
            if parent.parent is None:
                self._handle_internal_root_underflow(parent)
            else:
                self._handle_internal_underflow(parent)
    
    def _handle_internal_root_underflow(self, root: InternalNode):
        """处理内部根节点下溢（降低树高）"""
        if len(root.children) == 1:
            # 降低树高：将唯一子节点提升为新的根
            new_root = root.children[0]
            new_root.parent = None
            new_root_page_id = new_root.page_id
            
            # 旧根页面释放（如果它不是新的根）
            if root.page_id != new_root_page_id:
                self._free_page(root.page_id)
            
            self.root = new_root
            self.root_page_id = new_root_page_id
            
            self._flush_node(new_root)
        elif len(root.children) == 0:
            # 根没有子节点，变成空树
            self.root = None
            self.root_page_id = None
    
    def _adjust_root(self):
        """调整根节点（在删除后调用）"""
        # 加载当前根节点
        root = self._load_node(self.root_page_id)
        if root is None:
            # 根节点不存在，树为空
            self.root_page_id = None
            return
        
        # 如果根是内部节点且只有一个子节点，降低树高
        if not root.is_leaf() and len(root.children) == 1:
            new_root = root.children[0]
            if isinstance(new_root, int):
                new_root = self._load_node(new_root)
                if new_root is None:
                    return
            new_root.parent = None
            new_root_page_id = new_root.page_id
            
            # 旧根页面释放（如果它不是新的根）
            if root.page_id != new_root_page_id:
                self._free_page(root.page_id)
            
            self.root_page_id = new_root_page_id
            # 写回新根
            self._flush_node(new_root)
        # 如果根是叶子节点且为空，树变成空树
        elif root.is_leaf() and len(root.keys) == 0:
            self.root_page_id = None
            self.node_cache.pop(root.page_id, None)
    
    def _free_page(self, page_id: int):
        """释放页面（从树中移除）"""
        if page_id is None:
            return
        
        # 从缓存移除并取消钉住
        self._unload_node(page_id)
        
        # 更完善的页面回收：
        # 理论上应该将页面标记为空闲并可能添加到空闲列表
        # 这里简化：不实际删除文件页面，因为BufferPool还在管理它
        # 但在更完善的实现中，应该调用 buffer 或 storage 的空闲机制
        pass
    
    def shutdown(self):
        """关闭索引（写回所有缓存节点）"""
        for page_id, node in list(self.node_cache.items()):
            self._flush_node(node)
        self.node_cache.clear()


if __name__ == "__main__":
    # 测试序列化器
    print("Testing B+Tree Serializer...")
    
    # 创建内存叶子节点
    from bplus_node import LeafNode
    leaf = LeafNode(order=4)
    leaf.keys = [1, 2, 3, 4]
    leaf.values = [(100, 0), (101, 1), (102, 2), (103, 3)]
    
    serializer = BPlusTreeSerializer(4)
    data = serializer.serialize_node(leaf, page_id=1)
    print(f"Serialized node: {len(data)} bytes")
    
    # 反序列化
    restored = serializer.deserialize_node(data, page_id=1)
    print(f"Restored node: {restored}")
    print(f"Keys: {restored.keys}, Values: {restored.values}")
    
    print("Test passed!")
