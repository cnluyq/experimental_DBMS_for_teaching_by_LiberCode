"""
查询结果集（ResultSet）

封装查询执行的结果，包括：
- 数据行列表
- 列名
- 影响行数
- 执行统计信息
"""

from typing import List, Dict, Any, Optional


class ResultSet:
    """查询结果集"""
    
    def __init__(self, 
                 rows: Optional[List[Dict[str, Any]]] = None,
                 columns: Optional[List[str]] = None,
                 rows_affected: int = 0,
                 execution_time_ms: float = 0.0,
                 success: bool = True,
                 message: Optional[str] = None,
                 error: Optional[Exception] = None):
        """
        初始化结果集
        
        Args:
            rows: 查询结果行列表
            columns: 列名列表（如果为None则从rows首行推断）
            rows_affected: 受影响的行数（用于INSERT/UPDATE/DELETE）
            execution_time_ms: 执行时间（毫秒）
            success: 是否执行成功
            message: 附加消息（如事务提示等）
            error: 异常对象（如果执行失败）
        """
        self.rows = rows or []
        self.columns = columns or (list(self.rows[0].keys()) if self.rows else [])
        self.rows_affected = rows_affected
        self.execution_time_ms = execution_time_ms
        self.success = success
        self.message = message
        self.error = error
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式，便于JSON序列化"""
        return {
            'success': self.success,
            'rows': self.rows,
            'columns': self.columns,
            'rows_affected': self.rows_affected,
            'execution_time_ms': self.execution_time_ms,
            'message': self.message,
            'error': str(self.error) if self.error else None
        }
    
    def __repr__(self) -> str:
        if not self.success:
            return f"ResultSet(success=False, error={self.error})"
        
        rows_info = f"{len(self.rows)} rows" if self.rows else f"{self.rows_affected} rows affected"
        return f"ResultSet(success=True, {rows_info}, columns={self.columns})"
    
    def print_table(self):
        """打印格式化表格"""
        if not self.rows:
            print("Empty result set")
            if self.message:
                print(f"Message: {self.message}")
            return
        
        # 计算列宽
        col_widths = {}
        for col in self.columns:
            col_widths[col] = len(str(col))
            for row in self.rows:
                col_widths[col] = max(col_widths[col], len(str(row.get(col, ''))))
        
        # 打印表头
        header = " | ".join(str(col).ljust(col_widths[col]) for col in self.columns)
        print(header)
        print("-" * len(header))
        
        # 打印数据行
        for row in self.rows:
            line = " | ".join(str(row.get(col, '')).ljust(col_widths[col]) 
                             for col in self.columns)
            print(line)
        
        # 打印统计信息
        print(f"\n({len(self.rows)} row(s) returned, {self.execution_time_ms:.3f} ms)")
