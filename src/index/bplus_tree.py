"""
B+树索引管理器

提供插入、删除、查找和范围查询功能
"""

from typing import Optional, List, Any, Tuple, Iterator
from .bplus_node import BPlusNode, NodeType, InternalNode, LeafNode


class IndexEntry:
    """索引条目：表示键到数据记录的映射"""
    
    def __init__(self, key: Any, value: Any):
        """
        初始化索引条目
        
        Args:
            key: 索引键
            value: 数据记录标识（如记录ID、指针等）
        """
        self.key = key
        self.value = value
    
    def __repr__(self) -> str:
        return f"IndexEntry(key={self.key}, value={self.value})"
    
    def __eq__(self, other) -> bool:
        if not isinstance(other, IndexEntry):
            return False
        return self.key == other.key and self.value == other.value
    
    def __hash__(self) -> int:
        return hash((self.key, self.value))


class BPlusTree:
    """B+树索引实现（内存版本）"""
    
    def __init__(self, order: int = 4):
        """
        初始化B+树
        
        Args:
            order: B+树的阶数（每个节点的最大键数）
        """
        if order < 3:
            raise ValueError("B+树阶数必须至少为3")
        
        self.order = order
        self.root: Optional[BPlusNode] = None
        self.min_keys = (order // 2) - 1 if order % 2 == 0 else (order // 2)
        self.size = 0  # 索引条目总数
    
    def search(self, key: Any) -> Optional[Any]:
        """
        查找键对应的值
        
        Args:
            key: 要查找的键
            
        Returns:
            对应的值，如果不存在则返回None
        """
        if self.root is None:
            return None
        
        # 从根节点开始查找
        node = self.root
        while not node.is_leaf():
            internal_node = node  # type: InternalNode
            child_index = internal_node.find_child_index(key)
            node = internal_node.children[child_index]
        
        # 现在在叶子节点
        leaf_node = node  # type: LeafNode
        try:
            index = leaf_node.keys.index(key)
            return leaf_node.values[index]
        except ValueError:
            return None
    
    def range_search(self, start_key: Any, end_key: Any) -> List[IndexEntry]:
        """
        范围查询
        
        Args:
            start_key: 起始键（包含）
            end_key: 结束键（包含）
            
        Returns:
            在范围内的索引条目列表
        """
        if self.root is None:
            return []
        
        # 找到起始位置
        leaf_node = self._find_leaf(start_key)
        if leaf_node is None:
            return []
        
        results = []
        current_leaf = leaf_node
        
        while current_leaf is not None:
            for i, key in enumerate(current_leaf.keys):
                if key < start_key:
                    continue
                if key > end_key:
                    break
                results.append(IndexEntry(key, current_leaf.values[i]))
            
            current_leaf = current_leaf.next_leaf
            # 如果当前叶子节点的最小键已经超过end_key，停止
            if current_leaf and current_leaf.keys and current_leaf.keys[0] > end_key:
                break
        
        return results
    
    def _find_leaf(self, key: Any) -> Optional[LeafNode]:
        """查找应该包含key的叶子节点"""
        if self.root is None:
            return None
        
        node = self.root
        while not node.is_leaf():
            internal_node = node  # type: InternalNode
            child_index = internal_node.find_child_index(key)
            node = internal_node.children[child_index]
        
        return node  # type: LeafNode
    
    def insert(self, key: Any, value: Any) -> bool:
        """
        插入键值对
        
        Args:
            key: 键
            value: 值
            
        Returns:
            成功返回True，失败返回False（例如键已存在）
        """
        if self.root is None:
            # 创建根节点（叶子节点）
            self.root = LeafNode(self.order)
            self.root.keys.append(key)
            self.root.values.append(value)
            self.size = 1
            return True
        
        # 查找应该插入的叶子节点
        leaf = self._find_leaf(key)
        if leaf is None:
            return False
        
        # 检查键是否已存在
        try:
            index = leaf.keys.index(key)
            # 键已存在，可以选择更新值或返回失败
            leaf.values[index] = value
            return True  # 或者返回False表示插入失败
        except ValueError:
            # 键不存在，继续插入
            pass
        
        # 插入到叶子节点
        leaf.insert_entry(key, value)
        self.size += 1
        
        # 检查是否需要分裂
        if leaf.is_full():
            self._split_leaf(leaf)
        
        return True
    
    def _split_leaf(self, leaf: LeafNode):
        """分裂叶子节点"""
        middle_key, new_leaf = leaf.split()
        
        # 如果分裂的是根节点
        if leaf.parent is None:
            new_root = InternalNode(self.order)
            new_root.keys = [middle_key]
            new_root.set_children([leaf, new_leaf])
            self.root = new_root
        else:
            # 将middle_key和新节点插入父节点
            parent = leaf.parent  # type: InternalNode
            index = parent.find_child_index(middle_key)
            parent.keys.insert(index, middle_key)
            parent.children.insert(index + 1, new_leaf)
            new_leaf.parent = parent
            
            # 检查父节点是否需要分裂
            if parent.is_full():
                self._split_internal(parent)
    
    def _split_internal(self, internal: InternalNode):
        """分裂内部节点"""
        middle_key, new_internal = internal.split()
        
        # 如果分裂的是根节点
        if internal.parent is None:
            new_root = InternalNode(self.order)
            new_root.keys = [middle_key]
            new_root.set_children([internal, new_internal])
            self.root = new_root
        else:
            # 将middle_key和新节点插入父节点
            parent = internal.parent  # type: InternalNode
            index = parent.find_child_index(middle_key)
            parent.keys.insert(index, middle_key)
            parent.children.insert(index + 1, new_internal)
            new_internal.parent = parent
            
            # 检查父节点是否需要继续分裂
            if parent.is_full():
                self._split_internal(parent)
    
    def delete(self, key: Any) -> bool:
        """
        删除键
        
        Args:
            key: 要删除的键
            
        Returns:
            成功返回True，失败返回False（例如键不存在）
        """
        if self.root is None:
            return False
        
        # 查找包含key的叶子节点
        leaf = self._find_leaf(key)
        if leaf is None:
            return False
        
        # 删除条目
        deleted_value = leaf.delete_entry(key)
        if deleted_value is None:
            return False  # 键不存在
        
        self.size -= 1
        
        # 检查是否需要下溢处理
        if leaf.is_underflow():
            self._handle_underflow(leaf)
        
        # 检查根节点是否需要调整
        self._adjust_root()
        
        return True
    
    def _handle_underflow(self, leaf: LeafNode):
        """处理节点下溢"""
        parent = leaf.parent  # type: InternalNode
        if parent is None:
            return  # 根节点特殊处理
        
        # 找到leaf在父节点中的索引
        index = parent.children.index(leaf)
        
        # 尝试向兄弟节点借条目
        # 1. 尝试向左兄弟借（如果存在且有多余键）
        if index > 0:
            left_sibling = parent.children[index - 1]  # type: LeafNode
            if len(left_sibling.keys) > self.min_keys:
                self._borrow_from_left(leaf, left_sibling, parent, index)
                # 借调后，deficient移到了左边，deficient的最小键更新了
                # parent.keys[index-1] = children[index].keys[0]
                # 这个更新在 _borrow_from_left 中完成
                return
        
        # 2. 尝试向右兄弟借（如果存在且有多余键）
        if index < len(parent.children) - 1:
            right_sibling = parent.children[index + 1]  # type: LeafNode
            if len(right_sibling.keys) > self.min_keys:
                self._borrow_from_right(leaf, right_sibling, parent, index)
                # 借调后，right_sibling的最小键变了
                # parent.keys[index] = children[index+1].keys[0]
                # 这个更新在 _borrow_from_right 中完成
                return
        
        # 3. 与兄弟合并
        # 如果右兄弟存在，与右兄弟合并；否则与左兄弟合并
        if index < len(parent.children) - 1:
            right_sibling = parent.children[index + 1]  # type: LeafNode
            self._merge_leaves(leaf, right_sibling, parent, index)
        else:
            left_sibling = parent.children[index - 1]  # type: LeafNode
            self._merge_leaves(left_sibling, leaf, parent, index - 1)
    
    def _borrow_from_left(self, deficient: LeafNode, left_sibling: LeafNode,
                          parent: InternalNode, index: int):
        """从左兄弟借一个条目"""
        # 将左兄弟的最大键值对移动到 deficient 的开头
        borrowed_key = left_sibling.keys.pop()
        borrowed_value = left_sibling.values.pop()
        
        deficient.keys.insert(0, borrowed_key)
        deficient.values.insert(0, borrowed_value)
        
        # 更新父节点分隔键：
        # 借调后，deficient (children[index]) 的最小键变为 borrowed_key
        # parent.keys[index-1] 分隔 left_sibling (children[index-1]) 和 deficient (children[index])
        # 因此它应该等于 deficient.keys[0]（deficient 新的最小键）
        parent.keys[index - 1] = deficient.keys[0]
    
    def _borrow_from_right(self, deficient: LeafNode, right_sibling: LeafNode,
                           parent: InternalNode, index: int):
        """从右兄弟借一个条目"""
        # 将右兄弟的最小键值对移动到 deficient 的末尾
        borrowed_key = right_sibling.keys.pop(0)
        borrowed_value = right_sibling.values.pop(0)
        
        deficient.keys.append(borrowed_key)
        deficient.values.append(borrowed_value)
        
        # 更新父节点分隔键：
        # parent.keys[index] 分隔 deficient 和 right_sibling
        # 借调后，right_sibling 的最小键变了，所以 parent.keys[index] 应该更新为 right_sibling.keys[0]
        if right_sibling.keys:
            parent.keys[index] = right_sibling.keys[0]
        else:
            # 理论上不会发生，因为借调前提是右兄弟有多余键
            parent.keys[index] = deficient.keys[-1]
    
    def _merge_leaves(self, left: LeafNode, right: LeafNode,
                      parent: InternalNode, index: int):
        """
        合并两个叶子节点
        
        Args:
            left: 左叶子节点（保留）
            right: 右叶子节点（合并到左节点后删除）
            parent: 父节点
            index: right在父节点children中的索引
        """
        # 合并右节点到左节点
        left.keys.extend(right.keys)
        left.values.extend(right.values)
        
        # 更新兄弟指针
        left.next_leaf = right.next_leaf
        if right.next_leaf:
            right.next_leaf.prev_leaf = left
        
        # 从父节点删除分隔键和右节点
        parent.keys.pop(index)       # 删除分隔 left 和 right 的键
        parent.children.pop(index + 1)  # 删除 right 子节点
        
        # 更新父节点分隔键：
        # 合并后，left 成为新的子节点，其最大键变为 left.keys[-1]
        # 如果 left 右边还有子节点（即 index < len(parent.keys)），则分隔那个子节点的键应更新为 left.keys[-1]
        if index < len(parent.keys):
            parent.keys[index] = left.keys[-1]
        
        # 检查父节点是否下溢
        if parent.is_underflow():
            if parent.parent is None:
                self._handle_internal_root_underflow(parent)
            else:
                self._handle_internal_underflow(parent)
    
    def _handle_internal_underflow(self, internal: InternalNode):
        """处理内部节点下溢"""
        parent = internal.parent  # type: InternalNode
        if parent is None:
            return
        
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
            self._merge_internal(internal, right_sibling, parent, index)
        else:
            left_sibling = parent.children[index - 1]  # type: InternalNode
            self._merge_internal(left_sibling, internal, parent, index - 1)
    
    def _borrow_from_left_internal(self, deficient: InternalNode, left_sibling: InternalNode,
                                   parent: InternalNode, index: int):
        """从左内部节点借键"""
        # 父节点中对应的分隔键
        separator = parent.keys[index - 1]
        
        # 将左兄弟的最后一个子节点移到 deficient 的开头
        borrowed_child = left_sibling.children.pop()
        borrowed_key = left_sibling.keys.pop()
        
        deficient.keys.insert(0, separator)
        deficient.children.insert(0, borrowed_child)
        borrowed_child.parent = deficient
        
        # 更新父节点分隔键：
        # parent.keys[index-1] 分隔 left_sibling 和 deficient
        # 借调后，deficient 的第一个孩子是 borrowed_child，其最小键为 borrowed_key
        # 所以 parent.keys[index-1] 应为 deficient.children[0] 的最小键（即 borrowed_key）
        parent.keys[index - 1] = borrowed_key
    
    def _borrow_from_right_internal(self, deficient: InternalNode, right_sibling: InternalNode,
                                    parent: InternalNode, index: int):
        """从右内部节点借键"""
        # 父节点中对应的分隔键
        separator = parent.keys[index]
        
        # 将右兄弟的第一个子节点移到 deficient 的末尾
        borrowed_key = right_sibling.keys.pop(0)
        borrowed_child = right_sibling.children.pop(0)
        
        deficient.keys.append(separator)
        deficient.children.append(borrowed_child)
        borrowed_child.parent = deficient
        
        # 更新父节点分隔键：变为右兄弟新的第一个键（如果还有）或borrowed_key
        if right_sibling.keys:
            parent.keys[index] = right_sibling.keys[0]
        else:
            parent.keys[index] = borrowed_key
    
    def _merge_internal(self, left: InternalNode, right: InternalNode,
                        parent: InternalNode, index: int):
        """合并两个内部节点"""
        # 合并右节点到左节点，需要插入父节点分隔键
        separator = parent.keys.pop(index)
        
        left.keys.append(separator)
        left.keys.extend(right.keys)
        left.children.extend(right.children)
        
        # 更新所有子节点的父指针
        for child in right.children:
            child.parent = left
        
        # 从父节点删除右节点
        parent.children.pop(index + 1)
        
        # 递归检查父节点
        if parent.is_underflow():
            if parent.parent is None:
                self._handle_internal_root_underflow(parent)
            else:
                self._handle_internal_underflow(parent)
    
    def _handle_internal_root_underflow(self, root: InternalNode):
        """处理内部根节点下溢"""
        if len(root.children) == 1:
            # 降低树高
            self.root = root.children[0]
            self.root.parent = None
        elif len(root.children) == 0:
            # 根没有子节点，变成空树
            self.root = None
    
    def _handle_root_underflow(self, root: InternalNode):
        """处理内部根节点下溢"""
        if len(root.children) == 1:
            # 降低树高：将唯一子节点提升为新的根
            self.root = root.children[0]
            self.root.parent = None
        elif len(root.children) == 0:
            # 这不应该发生，但确保安全
            self.root = None
    
    def _adjust_root(self):
        """调整根节点"""
        if self.root is None:
            return
        
        # 如果根是内部节点且只有一个子节点，降低树高
        if not self.root.is_leaf() and len(self.root.children) == 1:
            self.root = self.root.children[0]
            self.root.parent = None
        # 如果根是叶子节点且为空，树变成空树
        elif self.root.is_leaf() and len(self.root.keys) == 0:
            self.root = None
    
    def get_height(self) -> int:
        """获取树的高度"""
        if self.root is None:
            return 0
        
        height = 1
        node = self.root
        while not node.is_leaf():
            internal_node = node  # type: InternalNode
            node = internal_node.children[0]
            height += 1
        
        return height
    
    def get_stats(self) -> dict:
        """获取索引统计信息"""
        return {
            'size': self.size,
            'order': self.order,
            'height': self.get_height(),
            'min_keys': self.min_keys,
        }
