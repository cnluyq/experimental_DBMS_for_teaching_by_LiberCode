"""
执行引擎主类（Executor）

功能：
1. 解析AST查询，构建执行计划
2. 协调ExecutionContext执行计划
3. 返回ResultSet给调用者
"""

from typing import Optional, Any, Dict, List
from parser.ast import (
    ASTNode,
    SelectNode, InsertNode as ASTInsertNode, UpdateNode as ASTUpdateNode, DeleteNode as ASTDeleteNode,
    CreateTableNode, DropTableNode,
    BeginNode, CommitNode, RollbackNode
)
from .context import ExecutionContext
from .table_manager import TableMetadata
from core.wal import WALManager
from .plan import (
    ExecNode, SeqScanNode, FilterNode, ProjectNode,
    InsertNode, UpdateNode, DeleteNode
)
from .result import ResultSet


class Executor:
    """查询执行引擎"""
    
    def __init__(self, 
                 storage_engine,
                 buffer_pool=None,
                 wal=None,
                 txn_manager=None):
        """
        初始化执行引擎
        
        Args:
            storage_engine: 存储引擎实例
            buffer_pool: 缓冲区池实例（可选）
            wal: WAL日志实例（可选）
            txn_manager: 事务管理器实例（可选）
        """
        self.storage = storage_engine
        self.buffer_pool = buffer_pool
        self.wal = wal
        self.txn_manager = txn_manager
        
        # 事务状态
        self.current_transaction_id: Optional[int] = None
        self.transaction_depth = 0
        self._next_transaction_id = 1  # 用于生成小的、适合uint32的事务ID
        
        # 表元数据缓存（全局共享）
        self.table_metadata: Dict[str, Any] = {}
        
        # 如果存储引擎支持WAL恢复，在初始化时执行
        if self.wal and hasattr(self.storage, 'recover_from_wal'):
            self.storage.recover_from_wal(self.wal)
    
    def execute(self, ast: ASTNode) -> ResultSet:
        """
        执行SQL语句（AST形式）
        
        Args:
            ast: 抽象语法树节点
            
        Returns:
            ResultSet结果集
        """
        # 创建执行上下文
        context = ExecutionContext(
            storage_engine=self.storage,
            buffer_pool=self.buffer_pool,
            wal=self.wal,
            transaction_id=self.current_transaction_id
        )
        
        # 如果存储引擎集成了SimpleTableStorage，从其中获取共享缓存
        if hasattr(self.storage, 'table_storage'):
            table_storage = self.storage.table_storage
            # 共享表元数据和管理器缓存（只读）
            context.table_metadata = table_storage.tables
            context.table_managers = table_storage.table_managers
        else:
            # 旧方式：使用Executor自己的缓存
            context.table_metadata = self.table_metadata
            # table_managers不共享，每个context独立（事务隔离）
        
        # 根据AST类型分发
        # 对于需要操作表的DML语句，先检查表是否存在
        if isinstance(ast, (SelectNode, ASTInsertNode, ASTUpdateNode, ASTDeleteNode)):
            self._check_table_exists(ast.table_name, context)
        
        if isinstance(ast, SelectNode):
            plan = self._create_select_plan(ast)
        elif isinstance(ast, ASTInsertNode):
            plan = self._create_insert_plan(ast)
        elif isinstance(ast, ASTUpdateNode):
            plan = self._create_update_plan(ast)
        elif isinstance(ast, ASTDeleteNode):
            plan = self._create_delete_plan(ast)
        elif isinstance(ast, BeginNode):
            self._handle_begin()
            return ResultSet(success=True, rows_affected=0, 
                           message="Transaction started")
        elif isinstance(ast, CommitNode):
            self._handle_commit(context)
            return ResultSet(success=True, rows_affected=0,
                           message="Transaction committed")
        elif isinstance(ast, RollbackNode):
            self._handle_rollback(context)
            return ResultSet(success=True, rows_affected=0,
                           message="Transaction rolled back")
        elif isinstance(ast, CreateTableNode):
            # 在ExecutionContext中创建表
            # 需要将解析器的列定义转换为内部格式
            table_name = ast.table_name
            columns = []
            for col_name, col_type, constraints in ast.columns:
                col_def = {
                    'name': col_name,
                    'type': col_type,
                    'nullable': 'NOT NULL' not in constraints,
                    'primary_key': 'PRIMARY KEY' in constraints
                }
                columns.append(col_def)
            context.create_table(table_name, columns)
            return ResultSet(success=True, rows_affected=0, 
                           message=f"Table '{table_name}' created")
        
        elif isinstance(ast, DropTableNode):
            # 删除表
            context.drop_table(ast.table_name)
            return ResultSet(success=True, rows_affected=0,
                           message=f"Table '{ast.table_name}' dropped")
        else:
            raise ValueError(f"不支持的语句类型: {type(ast).__name__}")
        
        # 执行计划
        rows = []
        affected_rows = None  # SELECT默认None，DML语句覆盖
        try:
            for row in plan.execute(context):
                rows.append(row)
                # 对于DML，计划节点返回的行可能包含rows_affected字段
                if 'rows_affected' in row:
                    affected_rows = row['rows_affected']
            
            # 获取统计信息
            stats = context.get_stats()
            
            # 获取影响行数
            # 如果计划节点返回了affected_rows（通常DML会返回），使用它
            # 否则根据语句类型确定：
            # - SELECT: 返回查询结果的行数
            # - DML (INSERT/UPDATE/DELETE): 从stats获取
            if affected_rows is None:
                if isinstance(ast, SelectNode):
                    # SELECT语句，返回结果行数
                    affected_rows = len(rows)
                elif stats.get('rows_written', 0) > 0:
                    affected_rows = stats['rows_written']
                elif stats.get('rows_deleted', 0) > 0:
                    affected_rows = stats['rows_deleted']
                elif stats.get('rows_updated', 0) > 0:
                    affected_rows = stats['rows_updated']
                else:
                    affected_rows = 0
            
            return ResultSet(
                rows=rows,
                rows_affected=affected_rows,
                columns=list(rows[0].keys()) if rows else [],
                execution_time_ms=stats.get('execution_time_ms', 0)
            )
        finally:
            plan.close()
            context.close()
    
    def _create_select_plan(self, ast: SelectNode) -> ExecNode:
        """
        为SELECT语句创建执行计划
        
        计划树：
        ProjectNode
          -> FilterNode (如果where存在)
            -> SeqScanNode
        """
        # 顺序扫描
        scan = SeqScanNode(ast.table_name, columns=None)
        
        # 过滤
        if ast.where_clause:
            filter_node = FilterNode(ast.where_clause)
            filter_node.add_child(scan)
            current = filter_node
        else:
            current = scan
        
        # 投影
        if ast.columns == ['*']:
            # 选择所有列，简化：使用SeqScanNode返回所有列
            # 实际可能需要从表元数据获取列列表
            project = current  # 无投影节点，直接返回扫描或过滤的结果
        else:
            # 需要转换列名为ColumnNode
            from parser.ast import ColumnNode
            col_nodes = [ColumnNode(col) if isinstance(col, str) else col 
                        for col in ast.columns]
            project = ProjectNode(col_nodes)
            project.add_child(current)
        
        return project
    
    def _create_insert_plan(self, ast: ASTInsertNode) -> ExecNode:
        """为INSERT语句创建执行计划"""
        return InsertNode(ast.table_name, ast.columns, ast.values)
    
    def _create_update_plan(self, ast: ASTUpdateNode) -> ExecNode:
        """为UPDATE语句创建执行计划"""
        # 将set_clauses转换为(列名, 值AST节点)元组列表
        set_clauses = [(sc[0], sc[1]) for sc in ast.set_clauses]
        return UpdateNode(ast.table_name, set_clauses, ast.where_clause)
    
    def _create_delete_plan(self, ast: ASTDeleteNode) -> ExecNode:
        """为DELETE语句创建执行计划"""
        return DeleteNode(ast.table_name, ast.where_clause)
    
    def _check_table_exists(self, table_name: str, context: ExecutionContext):
        """
        检查表是否存在于系统表中
        
        Args:
            table_name: 表名
            context: 执行上下文
            
        Raises:
            ValueError: 如果表不存在
        """
        if table_name not in context.table_metadata:
            raise ValueError(f"Table '{table_name}' does not exist")
    
    def _handle_begin(self):
        """处理BEGIN语句"""
        if self.transaction_depth == 0:
            # 开始新事务
            if self.txn_manager:
                # 使用事务管理器分配事务ID
                self.current_transaction_id = self.txn_manager.begin()
            else:
                # 兼容旧模式：自己生成ID
                self.current_transaction_id = self._next_transaction_id
                self._next_transaction_id += 1
                # 如果有WAL，写入BEGIN记录
                if self.wal:
                    self.wal.log_begin(self.current_transaction_id)
                    self.wal.flush()  # 确保BEGIN记录持久化
        self.transaction_depth += 1
    
    def _handle_commit(self, context: ExecutionContext):
        """处理COMMIT语句"""
        if self.transaction_depth > 0:
            self.transaction_depth -= 1
            
            if self.transaction_depth == 0:
                # 真正提交
                if self.txn_manager and self.current_transaction_id:
                    # 使用事务管理器提交
                    success = self.txn_manager.commit(self.current_transaction_id)
                    if not success:
                        raise RuntimeError(f"Transaction {self.current_transaction_id} commit failed")
                else:
                    # 兼容旧模式：直接写WAL并刷盘
                    if self.wal and self.current_transaction_id:
                        self.wal.commit(self.current_transaction_id)
                        self.wal.flush()
                
                # 刷数据页
                context.flush_all()
                
                self.current_transaction_id = None
    
    def _handle_rollback(self, context: ExecutionContext):
        """处理ROLLBACK语句"""
        if self.transaction_depth > 0:
            self.transaction_depth -= 1
            
            if self.transaction_depth == 0:
                # 真正回滚
                if self.txn_manager and self.current_transaction_id:
                    # 使用事务管理器回滚
                    success = self.txn_manager.rollback(self.current_transaction_id)
                    if not success:
                        print(f"Warning: Transaction {self.current_transaction_id} rollback failed")
                else:
                    # 兼容旧模式：写ABORT日志
                    if self.wal and self.current_transaction_id:
                        self.wal.abort(self.current_transaction_id)
                        self.wal.flush()
                        # TODO: 可以通过WAL恢复机制实际回滚页面修改
                        # 目前简化：只记录abort，依赖重启恢复或手动回滚
                
                self.current_transaction_id = None
    
    def start_transaction(self):
        """显式开始事务（非SQL方式）"""
        self._handle_begin()
    
    def commit_transaction(self):
        """显式提交事务（非SQL方式）"""
        context = ExecutionContext(
            storage_engine=self.storage,
            buffer_pool=self.buffer_pool,
            wal=self.wal,
            transaction_id=self.current_transaction_id
        )
        self._handle_commit(context)
        context.close()
    
    def rollback_transaction(self):
        """显式回滚事务（非SQL方式）"""
        context = ExecutionContext(
            storage_engine=self.storage,
            buffer_pool=self.buffer_pool,
            wal=self.wal,
            transaction_id=self.current_transaction_id
        )
        self._handle_rollback(context)
        context.close()
