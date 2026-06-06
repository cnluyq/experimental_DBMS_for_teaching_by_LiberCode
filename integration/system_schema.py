"""
系统表管理器

管理数据库系统表的持久化（表定义、列定义）。
提供表的创建、删除、查询的持久化支持。
"""

import json
import os
from typing import Dict, List, Any, Optional
from pathlib import Path


class SystemSchema:
    """系统表模式管理器"""
    
    SYSTEM_TABLES = {
        '__tables__': [
            {'name': 'table_id', 'type': 'INTEGER', 'nullable': False, 'primary_key': True},
            {'name': 'table_name', 'type': 'TEXT', 'nullable': False, 'unique': True},
            {'name': 'root_page', 'type': 'INTEGER', 'nullable': False},  # 数据页起始ID
            {'name': 'created_at', 'type': 'TEXT', 'nullable': False},
        ],
        '__columns__': [
            {'name': 'column_id', 'type': 'INTEGER', 'nullable': False, 'primary_key': True},
            {'name': 'table_id', 'type': 'INTEGER', 'nullable': False},
            {'name': 'column_name', 'type': 'TEXT', 'nullable': False},
            {'name': 'data_type', 'type': 'TEXT', 'nullable': False},
            {'name': 'nullable', 'type': 'INTEGER', 'nullable': False},  # 0 or 1
            {'name': 'primary_key', 'type': 'INTEGER', 'nullable': False},  # 0 or 1
            {'name': 'position', 'type': 'INTEGER', 'nullable': False},
        ]
    }
    
    def __init__(self, data_dir: str):
        """
        初始化系统表管理器
        
        Args:
            data_dir: 数据目录路径
        """
        self.data_dir = Path(data_dir)
        # 确保目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.schema_file = self.data_dir / 'system_schema.json'
        self.tables: Dict[str, Dict[str, Any]] = {}  # table_name -> table_metadata
        self.next_table_id = 1
        self.next_column_id = 1
        
        # 加载现有schema（如果存在）
        self._load_schema()
    
    def _load_schema(self):
        """从文件加载系统表模式"""
        if self.schema_file.exists():
            try:
                with open(self.schema_file, 'r') as f:
                    data = json.load(f)
                
                self.tables = data.get('tables', {})
                
                # 计算下一个ID
                if self.tables:
                    self.next_table_id = max(t.get('table_id', 0) for t in self.tables.values()) + 1
                    
                    # 收集所有列以计算下一个column_id
                    all_columns = []
                    for table in self.tables.values():
                        all_columns.extend(table.get('columns', []))
                    if all_columns:
                        self.next_column_id = max(c.get('column_id', 0) for c in all_columns) + 1
                
                print(f"SystemSchema loaded: {len(self.tables)} tables")
            except Exception as e:
                print(f"Failed to load system schema: {e}")
                self.tables = {}
        else:
            # 文件不存在，初始化系统表结构（但不创建实际表数据）
            self._initialize_system_tables()
    
    def _initialize_system_tables(self):
        """初始化系统表定义（在schema文件中，但不创建数据页）"""
        # 系统表定义将在第一次创建时实际创建数据页
        # 这里只准备元数据
        pass
    
    def _save_schema(self):
        """保存系统表模式到文件"""
        # 构建可序列化的数据
        save_data = {
            'next_table_id': self.next_table_id,
            'next_column_id': self.next_column_id,
            'tables': {}
        }
        
        for table_name, table_meta in self.tables.items():
            save_data['tables'][table_name] = {
                'table_id': table_meta['table_id'],
                'table_name': table_meta['table_name'],
                'root_page': table_meta.get('root_page'),
                'created_at': table_meta['created_at'],
                'columns': table_meta.get('columns', [])
            }
        
        try:
            with open(self.schema_file, 'w') as f:
                json.dump(save_data, f, indent=2)
        except Exception as e:
            print(f"Failed to save system schema: {e}")
    
    def create_table(self, table_name: str, columns: List[Dict[str, Any]], root_page: int) -> Dict[str, Any]:
        """
        创建表定义（在系统表中注册）
        
        Args:
            table_name: 表名
            columns: 列定义列表
            root_page: 数据页起始ID
            
        Returns:
            表元数据字典
        """
        if table_name in self.tables:
            raise ValueError(f"Table '{table_name}' already exists")
        
        table_id = self.next_table_id
        self.next_table_id += 1
        
        import time
        created_at = time.strftime('%Y-%m-%d %H:%M:%S')
        
        # 构建列定义（包含column_id）
        column_defs = []
        for i, col in enumerate(columns):
            col_def = col.copy()
            col_def['column_id'] = self.next_column_id
            self.next_column_id += 1
            col_def['table_id'] = table_id
            col_def['position'] = i
            column_defs.append(col_def)
        
        table_meta = {
            'table_id': table_id,
            'table_name': table_name,
            'root_page': root_page,
            'created_at': created_at,
            'columns': column_defs
        }
        
        self.tables[table_name] = table_meta
        self._save_schema()
        
        return table_meta
    
    def drop_table(self, table_name: str):
        """删除表定义"""
        if table_name not in self.tables:
            raise ValueError(f"Table '{table_name}' does not exist")
        
        del self.tables[table_name]
        self._save_schema()
    
    def get_table_metadata(self, table_name: str) -> Optional[Dict[str, Any]]:
        """获取表元数据"""
        return self.tables.get(table_name)
    
    def list_tables(self) -> List[str]:
        """列出所有表名"""
        return list(self.tables.keys())
    
    def get_all_metadata(self) -> Dict[str, Dict[str, Any]]:
        """获取所有表元数据"""
        return self.tables.copy()
    
    def is_system_table(self, table_name: str) -> bool:
        """判断是否为系统表"""
        return table_name in self.SYSTEM_TABLES
    
    def close(self):
        """关闭并保存系统表（如果需要）"""
        # SystemSchema使用文件持久化，close是空操作
        # 如果有内存缓存需要持久化，可以在这里调用_save_schema()
        pass