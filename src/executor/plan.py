"""
执行计划节点定义

执行计划由一系列节点组成，每个节点完成特定的操作：
- SeqScanNode: 顺序扫描表数据
- FilterNode: 根据条件过滤行
- ProjectNode: 投影（选择/计算列）
- InsertNode: 插入新记录
- UpdateNode: 更新记录
- DeleteNode: 删除记录

节点之间通过迭代器模式传递行数据。
"""

from typing import Optional, Any, Dict, List, Iterator, Tuple
from parser.ast import ASTNode, ColumnNode
from .evaluator import ExpressionEvaluator


class ExecNode:
    """执行计划节点基类"""
    
    def __init__(self):
        self.children: List['ExecNode'] = []
        self.evaluator = ExpressionEvaluator()
    
    def add_child(self, child: 'ExecNode'):
        """添加子节点"""
        self.children.append(child)
    
    def execute(self, context) -> Iterator[Dict[str, Any]]:
        """
        执行节点并返回行迭代器
        
        Args:
            context: 执行上下文
            
        Returns:
            行字典的迭代器，每行是一个列名到值的映射
        """
        raise NotImplementedError("子类必须实现execute方法")
    
    def close(self):
        """清理资源"""
        for child in self.children:
            child.close()


class SeqScanNode(ExecNode):
    """顺序扫描节点：从表中读取所有行"""
    
    def __init__(self, table_name: str, columns: Optional[List[str]] = None):
        """
        初始化顺序扫描节点
        
        Args:
            table_name: 要扫描的表名
            columns: 要读取的列列表，None表示读取所有列
        """
        super().__init__()
        self.table_name = table_name
        self.columns = columns
    
    def execute(self, context) -> Iterator[Dict[str, Any]]:
        """
        顺序扫描表数据
        """
        # 使用执行上下文的表管理器扫描
        for record in context.scan_table(self.table_name):
            row = record.values
            # 如果指定了列，进行投影
            if self.columns is not None:
                row = {col: row.get(col) for col in self.columns}
            yield row


class FilterNode(ExecNode):
    """过滤节点：根据WHERE条件过滤输入行"""
    
    def __init__(self, condition: Optional[ASTNode] = None):
        """
        初始化过滤节点
        
        Args:
            condition: WHERE条件表达式（AST节点）
        """
        super().__init__()
        self.condition = condition
    
    def execute(self, context) -> Iterator[Dict[str, Any]]:
        """
        过滤输入行的条件
        
        从第一个子节点获取输入行，检查条件，只返回满足条件的行
        """
        if not self.children:
            return iter([])
        
        child_iter = self.children[0].execute(context)
        
        if self.condition is None:
            # 无条件，直接传递所有行
            for row in child_iter:
                context.increment_stats(rows_read=1)
                yield row
        else:
            # 有条件，求值过滤
            for row in child_iter:
                context.increment_stats(rows_read=1)
                try:
                    if self.evaluator.evaluate_condition(self.condition, row):
                        yield row
                except Exception:
                    # 条件求值错误，视为不满足
                    continue


class ProjectNode(ExecNode):
    """投影节点：选择列和计算表达式"""
    
    def __init__(self, columns: List[ASTNode]):
        """
        初始化投影节点
        
        Args:
            columns: 列表达式列表，ColumnNode表示直接选择列，
                    其他AST节点表示计算表达式（如值、函数等）
        """
        super().__init__()
        self.columns = columns  # 列表中的元素可能是ColumnNode或其他表达式节点
    
    def execute(self, context) -> Iterator[Dict[str, Any]]:
        """
        投影输入行
        
        对每个输入行，按columns指定的表达式计算新行的值
        """
        if not self.children:
            return iter([])
        
        child_iter = self.children[0].execute(context)
        
        for row in child_iter:
            projected_row = {}
            
            for i, col_expr in enumerate(self.columns):
                # 确定输出列名
                if isinstance(col_expr, ColumnNode):
                    col_name = col_expr.column_name
                else:
                    # 对于表达式，生成一个默认列名如 expr_0, expr_1
                    col_name = f"expr_{i}"
                
                # 求值
                try:
                    value = self.evaluator.evaluate(col_expr, 
                                                  type('EvalContext', (), {'get_column_value': lambda self, name: row.get(name)})())
                    projected_row[col_name] = value
                except Exception:
                    projected_row[col_name] = None
            
            yield projected_row


class InsertNode(ExecNode):
    """插入节点：将数据插入表"""
    
    def __init__(self, table_name: str, columns: List[str], values: List[ASTNode]):
        """
        初始化插入节点
        
        Args:
            table_name: 目标表名
            columns: 列名列表（可能为空表示所有列）
            values: 值表达式列表
        """
        super().__init__()
        self.table_name = table_name
        self.columns = columns
        self.values = values
    
    def execute(self, context) -> Iterator[Dict[str, Any]]:
        """
        执行插入操作
        
        返回单行，包含插入的记录的ID和影响行数（通常为1）
        """
        # 获取表元数据（如果columns为空，从中推断列）
        table_columns = self.columns
        if not table_columns:
            # 从表元数据获取列名列表
            table_meta = context.table_metadata.get(self.table_name)
            if table_meta:
                table_columns = [col['name'] for col in table_meta.columns]
            else:
                raise ValueError(f"表 '{self.table_name}' 不存在且未指定列")
        
        if len(table_columns) != len(self.values):
            raise ValueError(f"列数({len(table_columns)})与值数({len(self.values)})不匹配")
        
        # 获取表元数据
        if self.table_name not in context.table_metadata:
            raise ValueError(f"表 '{self.table_name}' 不存在")
        
        # 求值所有值表达式
        column_values = {}
        for col_name, value_expr in zip(table_columns, self.values):
            # 求值
            value = self.evaluator.evaluate(value_expr, type('EvalContext', (), {'get_column_value': lambda self, name: None})())
            column_values[col_name] = value
        
        # 记录WAL：INSERT操作（在修改数据前）
        if hasattr(context, 'log_insert') and context.transaction_id:
            context.log_insert(self.table_name, column_values)
        
        # 使用表管理器插入
        manager = context.get_table_manager(self.table_name)
        record_id = manager.insert_record(column_values)
        
        context.increment_stats(rows_written=1)
        
        # 返回插入的记录信息
        yield {
            'record_id': record_id,
            'rows_affected': 1
        }


class UpdateNode(ExecNode):
    """更新节点：更新表中的记录"""
    
    def __init__(self, table_name: str, set_clauses: List[Tuple[str, ASTNode]], 
                 where_clause: Optional[ASTNode] = None):
        """
        初始化更新节点
        
        Args:
            table_name: 目标表名
            set_clauses: SET子句列表[(列名, 值表达式), ...]
            where_clause: WHERE条件（可选）
        """
        super().__init__()
        self.table_name = table_name
        self.set_clauses = set_clauses
        self.where_clause = where_clause
    
    def execute(self, context) -> Iterator[Dict[str, Any]]:
        """
        执行更新操作
        
        扫描表，对满足WHERE条件的行应用SET更新
        """
        # 获取表管理器
        manager = context.get_table_manager(self.table_name)
        
        # 先扫描所有记录
        total_updated = 0
        for record in manager.scan_all():
            row = record.values
            
            # 检查WHERE条件
            if self.where_clause:
                if not self.evaluator.evaluate_condition(self.where_clause, row):
                    continue
            
            # 保存旧值用于WAL
            old_values = row.copy()
            
            # 应用SET子句
            new_values = {}
            for col_name, value_expr in self.set_clauses:
                value = self.evaluator.evaluate(value_expr, type('EvalContext', (), {'get_column_value': lambda self, name: old_values.get(name)})())
                new_values[col_name] = value
            
            # 记录WAL：UPDATE操作（在修改数据前）
            if hasattr(context, 'log_update') and context.transaction_id:
                # 逻辑日志：记录旧值和新值
                context.log_update(
                    table_name=self.table_name,
                    record_id=record.record_id,
                    old_values=old_values,
                    new_values={**old_values, **new_values}
                )
            
            # 更新记录
            if manager.update_record(record.record_id, new_values):
                total_updated += 1
                context.increment_stats(rows_written=1)
        
        yield {
            'rows_affected': total_updated
        }


class DeleteNode(ExecNode):
    """删除节点：删除表中的记录"""
    
    def __init__(self, table_name: str, where_clause: Optional[ASTNode] = None):
        """
        初始化删除节点
        
        Args:
            table_name: 目标表名
            where_clause: WHERE条件（可选，None表示删除所有行）
        """
        super().__init__()
        self.table_name = table_name
        self.where_clause = where_clause
    
    def execute(self, context) -> Iterator[Dict[str, Any]]:
        """
        执行删除操作
        
        扫描表，删除满足WHERE条件的行
        """
        # 获取表管理器
        manager = context.get_table_manager(self.table_name)
        
        # 扫描并收集要删除的记录
        to_delete = []
        records_to_delete = []
        for record in manager.scan_all():
            row = record.values
            if self.where_clause:
                if self.evaluator.evaluate_condition(self.where_clause, row):
                    to_delete.append(record.record_id)
                    records_to_delete.append(record)
            else:
                to_delete.append(record.record_id)
                records_to_delete.append(record)
        
        # 记录WAL：DELETE操作
        if hasattr(context, 'log_delete') and context.transaction_id:
            for record in records_to_delete:
                context.log_delete(self.table_name, record.record_id, record.values)
        
        # 执行删除
        total_deleted = 0
        for record_id in to_delete:
            if manager.delete_record(record_id):
                total_deleted += 1
                context.increment_stats(rows_written=1)
        
        yield {
            'rows_affected': total_deleted
        }


# 为了方便使用，添加别名
ScanNode = SeqScanNode
