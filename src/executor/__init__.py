"""
查询执行引擎模块

主要组件：
- Executor: 执行引擎主类
- ExecutionContext: 执行上下文（事务、存储、WAL等）
- ExpressionEvaluator: 表达式求值器
- ExecNode: 执行计划节点基类及子类
- ResultSet: 查询结果集
"""

from .executor import Executor
from .context import ExecutionContext
from .evaluator import ExpressionEvaluator
from .plan import (
    ExecNode,
    SeqScanNode,
    FilterNode,
    ProjectNode,
    InsertNode,
    UpdateNode,
    DeleteNode
)
from .result import ResultSet

__all__ = [
    'Executor',
    'ExecutionContext',
    'ExpressionEvaluator',
    'ExecNode',
    'SeqScanNode',
    'FilterNode',
    'ProjectNode',
    'InsertNode',
    'UpdateNode',
    'DeleteNode',
    'ResultSet'
]