"""
SQL解析器包
支持简化的SQL子集：
- DDL: CREATE TABLE, DROP TABLE
- DML: SELECT, INSERT, UPDATE, DELETE（单表，简单WHERE条件）
- 事务: BEGIN, COMMIT, ROLLBACK
"""

from .tokenizer import Token, Tokenizer, TokenizerError
from .parser import Parser, ParserError, parse
from .ast import (
    ASTNode,
    CreateTableNode, DropTableNode,
    SelectNode, InsertNode, UpdateNode, DeleteNode,
    BeginNode, CommitNode, RollbackNode,
    BinaryOpNode, ColumnNode, ValueNode, NullNode
)

__all__ = [
    'Token', 'Tokenizer', 'TokenizerError',
    'Parser', 'ParserError', 'parse',
    'ASTNode',
    'CreateTableNode', 'DropTableNode',
    'SelectNode', 'InsertNode', 'UpdateNode', 'DeleteNode',
    'BeginNode', 'CommitNode', 'RollbackNode',
    'BinaryOpNode', 'ColumnNode', 'ValueNode', 'NullNode'
]
