"""
B+树叶子节点迭代器

支持高效的范围查询遍历
"""

from typing import Iterator, Optional, Any, Tuple
from .bplus_node import LeafNode


class LeafIterator(Iterator):
    """叶子节点链表迭代器（用于范围查询）"""
    
    def __init__(self, start_leaf: LeafNode, start_key: Optional[Any] = None):
        """
        初始化迭代器
        
        Args:
            start_leaf: 起始叶子节点
            start_key: 起始键（如果提供，则从大于等于该键的位置开始）
        """
        self.current_leaf = start_leaf
        self.current_index = 0
        
        # 如果指定了起始键，定位到第一个>=start_key的位置
        if start_key is not None and start_leaf is not None:
            self._seek_to_key(start_key)
    
    def _seek_to_key(self, key: Any):
        """定位到第一个大于等于key的位置"""
        if self.current_leaf is None:
            return
        
        # 在当前叶子节点查找
        for i, k in enumerate(self.current_leaf.keys):
            if k >= key:
                self.current_index = i
                return
        
        # 如果当前叶子节点没有，移动到下一个叶子节点
        self.current_leaf = self.current_leaf.next_leaf
        self.current_index = 0
        if self.current_leaf is not None:
            self._seek_to_key(key)
    
    def __iter__(self) -> 'LeafIterator':
        return self
    
    def __next__(self) -> Tuple[Any, Any]:
        """返回下一个键值对"""
        while self.current_leaf is not None:
            # 检查当前叶子节点是否有更多条目
            if self.current_index < len(self.current_leaf.keys):
                key = self.current_leaf.keys[self.current_index]
                value = self.current_leaf.values[self.current_index]
                self.current_index += 1
                return (key, value)
            
            # 移动到下一个叶子节点
            self.current_leaf = self.current_leaf.next_leaf
            self.current_index = 0
        
        raise StopIteration
    
    def has_next(self) -> bool:
        """检查是否还有下一个元素"""
        return self.current_leaf is not None
    
    def peek(self) -> Optional[Tuple[Any, Any]]:
        """
        查看下一个元素但不移动
        
        Returns:
            下一个键值对或None
        """
        if self.current_leaf is None:
            return None
        
        if self.current_index < len(self.current_leaf.keys):
            return (self.current_leaf.keys[self.current_index],
                    self.current_leaf.values[self.current_index])
        
        return None
