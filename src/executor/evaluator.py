"""
表达式求值器

支持：
- 列引用
- 字面量（整数、浮点数、字符串、NULL）
- 二元操作符：=, !=, >, <, >=, <=, AND, OR
- 短路求值
"""

from typing import Any, Optional, Dict, List
from parser.ast import (
    ASTNode, ColumnNode, ValueNode, NullNode, BinaryOpNode
)


class EvaluationContext:
    """表达式求值上下文：提供列值查找"""
    
    def __init__(self, row: Dict[str, Any]):
        self.row = row
    
    def get_column_value(self, column_name: str) -> Any:
        """获取列值"""
        return self.row.get(column_name)


class ExpressionEvaluator:
    """表达式求值器"""
    
    def __init__(self):
        pass
    
    def evaluate(self, expr: ASTNode, context: EvaluationContext) -> Any:
        """求值表达式"""
        if isinstance(expr, ColumnNode):
            return context.get_column_value(expr.column_name)
        
        elif isinstance(expr, ValueNode):
            return self._convert_value(expr)
        
        elif isinstance(expr, NullNode):
            return None
        
        elif isinstance(expr, BinaryOpNode):
            return self._evaluate_binary(expr, context)
        
        else:
            raise ValueError(f"不支持的表达式节点类型: {type(expr).__name__}")
    
    def _convert_value(self, value_node: ValueNode) -> Any:
        """转换字面量值"""
        if value_node.value_type == 'integer':
            return int(value_node.value)
        elif value_node.value_type == 'float':
            return float(value_node.value)
        elif value_node.value_type == 'string':
            return str(value_node.value)
        else:
            return value_node.value
    
    def _type_align(self, val: Any, other: Any) -> Any:
        """类型对齐：如果一个是数字一个是数字字符串，转换为数字"""
        if val is None:
            return val
        
        # 如果另一个是int/ float，转换当前值
        if isinstance(other, int) and isinstance(val, str):
            try:
                return int(val)
            except ValueError:
                pass
        elif isinstance(other, float) and isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                pass
        
        return val
    
    def _evaluate_binary(self, node: BinaryOpNode, context: EvaluationContext) -> Any:
        """求值二元操作"""
        left_val = self.evaluate(node.left, context)
        right_val = self.evaluate(node.right, context)
        
        # 类型对齐：如果一边是数字字符串，尝试转换
        left_val = self._type_align(left_val, right_val)
        right_val = self._type_align(right_val, left_val)
        
        op = node.op.upper()
        
        # 处理 IS NULL / IS NOT NULL
        if op in ('IS', 'IS NOT'):
            left_is_null = left_val is None
            right_is_null = isinstance(node.right, NullNode) or right_val is None
            if op == 'IS':
                return left_is_null == right_is_null  # 都为NULL或都不为NULL时为True
            else:  # IS NOT
                return left_is_null != right_is_null
        
        # 处理NULL在其他比较中
        if left_val is None or right_val is None:
            if op in ('=', '!='):
                return left_val is right_val  # NULL == NULL为True（简化）
            return None  # 任何涉及NULL的比较返回NULL
        
        # 逻辑操作符
        if op == 'AND':
            return self._eval_and(left_val, right_val)
        elif op == 'OR':
            return self._eval_or(left_val, right_val)
        
        # 比较操作符（确保类型一致）
        try:
            if op == '=':
                return left_val == right_val
            elif op == '!=':
                return left_val != right_val
            elif op == '>':
                return left_val > right_val
            elif op == '<':
                return left_val < right_val
            elif op == '>=':
                return left_val >= right_val
            elif op == '<=':
                return left_val <= right_val
            else:
                raise ValueError(f"不支持的操作符: {op}")
        except TypeError as e:
            raise ValueError(f"类型错误在比较 {left_val} {op} {right_val}: {e}")
    
    def _eval_and(self, left_val: Any, right_val: Any) -> bool:
        """短路求值的AND"""
        # 转换为布尔值
        left_bool = self._to_boolean(left_val)
        if not left_bool:
            return False
        return self._to_boolean(right_val)
    
    def _eval_or(self, left_val: Any, right_val: Any) -> bool:
        """短路求值的OR"""
        left_bool = self._to_boolean(left_val)
        if left_bool:
            return True
        return self._to_boolean(right_val)
    
    def _to_boolean(self, value: Any) -> bool:
        """转换为布尔值"""
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return len(value) > 0
        return bool(value)
    
    def evaluate_condition(self, condition: ASTNode, row: Dict[str, Any]) -> bool:
        """便捷方法：求值WHERE条件，返回布尔值"""
        result = self.evaluate(condition, EvaluationContext(row))
        
        # 如果结果为None（NULL），视为False
        if result is None:
            return False
        
        # 转换为布尔值
        return self._to_boolean(result)


# 测试
if __name__ == "__main__":
    from parser.ast import ColumnNode, ValueNode, BinaryOpNode
    
    evaluator = ExpressionEvaluator()
    
    # 测试简单条件
    row = {'id': 5, 'name': 'Alice', 'age': 25, 'salary': 50000.0}
    
    # 测试列引用
    col_expr = ColumnNode('age')
    print(f"age: {evaluator.evaluate(col_expr, row)}")  # 25
    
    # 测试字面量
    val_expr = ValueNode(100, 'integer')
    print(f"literal: {evaluator.evaluate(val_expr, row)}")  # 100
    
    # 测试比较
    comp_expr = BinaryOpNode(ColumnNode('age'), '>', ValueNode(20, 'integer'))
    print(f"age > 20: {evaluator.evaluate_condition(comp_expr, row)}")  # True
    
    # 测试AND
    and_expr = BinaryOpNode(
        BinaryOpNode(ColumnNode('age'), '>', ValueNode(20, 'integer')),
        'AND',
        BinaryOpNode(ColumnNode('salary'), '>=', ValueNode(40000, 'integer'))
    )
    print(f"complex AND: {evaluator.evaluate_condition(and_expr, row)}")  # True
    
    # 测试NULL
    row_with_null = {'id': 1, 'name': None}
    null_cond = BinaryOpNode(ColumnNode('name'), '=', ValueNode(None, 'null'))
    print(f"NULL = NULL: {evaluator.evaluate_condition(null_cond, row_with_null)}")  # True
    
    print("All tests passed!")