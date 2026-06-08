"""
B+树节点数据结构

定义了InternalNode和LeafNode的实现
"""

from enum import Enum
from typing import List, Optional, Any, Tuple


class NodeType(Enum):
    """节点类型"""
    INTERNAL = "internal"  # 内部节点（非叶子）
    LEAF = "leaf"          # 叶子节点


class BPlusNode:
    """B+树节点基类（内存表示）"""
    
    def __init__(self, node_type: NodeType, order: int = 4):
        """
        初始化节点
        
        Args:
            node_type: 节点类型（内部节点或叶子节点）
            order: B+树的阶数（每个节点的最大键数）
        """
        self.node_type = node_type
        self.order = order
        self.parent: Optional['BPlusNode'] = None  # 父节点指针
        self.keys: List[Any] = []  # 键数组（已排序）
    
    def is_leaf(self) -> bool:
        """是否叶子节点"""
        return self.node_type == NodeType.LEAF
    
    def is_full(self) -> bool:
        """节点是否已满"""
        return len(self.keys) >= self.order
    
    def is_underflow(self) -> bool:
        """节点是否下溢（键数少于最小要求）"""
        # 根节点可以少于最小键数
        if self.parent is None:
            return False
        # 非根内部节点：至少 ceil(order/2) - 1 个键
        # 叶子节点：至少 ceil(order/2) - 1 个键
        min_keys = (self.order // 2) - 1 if self.order % 2 == 0 else (self.order // 2)
        return len(self.keys) < min_keys
    
    def __repr__(self) -> str:
        return f"{self.node_type.value}(keys={self.keys})"


class InternalNode(BPlusNode):
    """B+树内部节点
    
    结构：
    - keys: [k1, k2, ..., kn]
    - children: [ptr0, ptr1, ..., ptrn]  (n+1个子节点)
    
    查找时：找到 keys[i] <= key < keys[i+1] 对应的 children[i+1]
    """
    
    def __init__(self, order: int = 4):
        super().__init__(NodeType.INTERNAL, order)
        self.children: List[BPlusNode] = []  # 子节点指针数组
    
    def set_children(self, children: List[BPlusNode]):
        """设置子节点"""
        self.children = children
        # 为每个子节点设置父指针
        for child in children:
            child.parent = self
    
    def find_child_index(self, key: Any) -> int:
        """
        查找key应该在哪个子节点中
        
        Args:
            key: 要查找的键
            
        Returns:
            子节点索引，使得 key <= keys[index] < key
        """
        # 二分查找
        left, right = 0, len(self.keys) - 1
        while left <= right:
            mid = (left + right) // 2
            if key == self.keys[mid]:
                return mid + 1  # 相等时走右边
            elif key < self.keys[mid]:
                right = mid - 1
            else:
                left = mid + 1
        return left
    
    def insert_child(self, index: int, key: Any, right_child: Optional[BPlusNode] = None):
        """
        在指定位置插入键和子节点
        
        Args:
            index: 插入位置的索引
            key: 要插入的键
            right_child: 右侧子节点（如果需要插入两个子节点）
        """
        # 插入键
        self.keys.insert(index, key)
        
        # 插入子节点
        if right_child is not None:
            # 分裂时：需要在 index 位置插入两个子节点
            self.children.insert(index, right_child)
            right_child.parent = self
        else:
            # 普通插入：调整 children 数组（因为多了一个键，需要多一个子节点）
            # 此时 children 应该已经有 index+1 个元素，我们需要更新它们之间的关系
            # 实际上，插入一个键意味着children也需要调整
            pass  # 由调用者负责children的插入
    
    def split(self) -> Tuple[Any, 'InternalNode']:
        """
        分裂内部节点
        
        策略：
        - 取中间键（向上提父节点）
        - 右侧部分形成新节点
        
        Returns:
            (middle_key, new_node) 中间键和新的右兄弟节点
        """
        mid = len(self.keys) // 2
        middle_key = self.keys[mid]
        
        # 创建新节点（右侧）
        new_node = InternalNode(self.order)
        new_node.keys = self.keys[mid + 1:]
        new_node.children = self.children[mid + 1:]
        
        # 更新新节点的父指针
        for child in new_node.children:
            child.parent = new_node
        
        # 保留左侧部分
        self.keys = self.keys[:mid]
        self.children = self.children[:mid + 1]
        
        # 父节点（会由BPlusTree.insert处理）
        
        return middle_key, new_node
    
    def __repr__(self) -> str:
        return f"Internal(keys={self.keys}, children={len(self.children)})"


class LeafNode(BPlusNode):
    """B+树叶子节点
    
    结构：
    - keys: [k1, k2, ..., kn]
    - values: [(record_id1, ...), ...] 与 keys 一一对应
    - next_leaf: 指向下一个叶子节点（用于范围查询）
    - prev_leaf: 指向前一个叶子节点（可选，用于双向遍历）
    """
    
    def __init__(self, order: int = 4):
        super().__init__(NodeType.LEAF, order)
        self.values: List[Any] = []  # 与keys对应的值（record_id等）
        self.next_leaf: Optional['LeafNode'] = None  # 下一个叶子节点
        self.prev_leaf: Optional['LeafNode'] = None  # 前一个叶子节点
    
    def insert_entry(self, key: Any, value: Any):
        """插入键值对（保持有序）"""
        # 二分查找插入位置
        left, right = 0, len(self.keys) - 1
        insert_pos = len(self.keys)
        while left <= right:
            mid = (left + right) // 2
            if key <= self.keys[mid]:
                insert_pos = mid
                right = mid - 1
            else:
                left = mid + 1
        
        self.keys.insert(insert_pos, key)
        self.values.insert(insert_pos, value)
    
    def delete_entry(self, key: Any) -> Optional[Any]:
        """
        删除指定键
        
        Returns:
            删除的值，如果键不存在则返回None
        """
        try:
            index = self.keys.index(key)
            self.keys.pop(index)
            return self.values.pop(index)
        except ValueError:
            return None
    
    def split(self) -> Tuple[Any, 'LeafNode']:
        """
        分裂叶子节点
        
        策略：
        - 取中间键（保留在左节点，向上提父节点）
        - 右侧部分形成新节点
        
        Returns:
            (middle_key, new_node) 中间键和新的右兄弟节点
        """
        mid = len(self.keys) // 2
        
        # 中间键（用于父节点）
        middle_key = self.keys[mid]
        
        # 创建新节点（右侧）
        new_node = LeafNode(self.order)
        new_node.keys = self.keys[mid:]
        new_node.values = self.values[mid:]
        
        # 设置兄弟指针
        # 注意：next_leaf可能是LeafNode对象或page_id整数（从磁盘加载时）
        new_node.next_leaf = self.next_leaf
        new_node.prev_leaf = self
        if self.next_leaf and isinstance(self.next_leaf, LeafNode):
            self.next_leaf.prev_leaf = new_node
        self.next_leaf = new_node
        
        # 保留左侧部分（不包含中间键？其实是保留左侧）
        # 标准B+树分裂：左节点保留一半（包括中间键？主要取决于实现）
        # 这里采用：左节点保留keys[:mid]，右节点keys[mid:]
        # 父节点插入middle_key，左节点keys[:mid]，右节点keys[mid:]
        self.keys = self.keys[:mid]
        self.values = self.values[:mid:]
        
        return middle_key, new_node
    
    def find_index(self, key: Any) -> int:
        """查找key在节点中的索引（精确匹配）"""
        try:
            return self.keys.index(key)
        except ValueError:
            return -1
    
    def get_max_key(self) -> Any:
        """获取最大键（用于父节点索引）"""
        if self.keys:
            return self.keys[-1]
        return None
    
    def __repr__(self) -> str:
        next_id = id(self.next_leaf) if self.next_leaf else None
        return f"Leaf(keys={self.keys}, values={self.values}, next={next_id})"
