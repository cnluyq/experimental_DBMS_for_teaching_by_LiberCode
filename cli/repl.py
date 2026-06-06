"""
REPL（Read-Eval-Print Loop）交互式命令行界面

提供交互式SQL输入、结果展示和元命令支持。
"""

import sys
import signal
import os
from typing import Optional

# 添加src目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
src_path = os.path.join(project_root, 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from integration.coordinator import Database, create_database
from integration.config import DatabaseConfig


class REPL:
    """REPL交互界面"""
    
    PROMPT = "projo> "
    CONTINUE_PROMPT = "......> "
    
    # 元命令（以\开头的命令）
    META_COMMANDS = {
        '\\q': '退出',
        '\\h': '帮助',
        '\\t': '显示所有表',
        '\\d': '描述表结构',
        '\\st': '显示统计信息',
        '\\c': '清除屏幕',
    }
    
    def __init__(self, database: Database):
        """
        初始化REPL
        
        Args:
            database: 数据库实例
        """
        self.db = database
        self.running = False
        self.buffer = ''
        
        # 设置信号处理（Ctrl+C）
        signal.signal(signal.SIGINT, self._handle_sigint)
    
    def _handle_sigint(self, signum, frame):
        """处理Ctrl+C"""
        print("\n[Interrupted]")
        self.buffer = ''
        print(self.PROMPT, end='', flush=True)
    
    def start(self):
        """启动REPL循环"""
        self.running = True
        print("=" * 60)
        print("ProjoDB REPL - 实验性教学数据库")
        print("输入SQL语句或元命令（\\h查看帮助）")
        print("=" * 60)
        
        while self.running:
            try:
                # 读取用户输入
                if self.buffer:
                    line = input(self.CONTINUE_PROMPT)
                else:
                    line = input(self.PROMPT)
                
                # 合并多行（直到遇到分号）
                self.buffer += line + '\n'
                
                # 检查是否语句结束
                if ';' in self.buffer:
                    # 提取完整语句（以分号分隔）
                    statements = self.buffer.split(';')
                    # 最后一个元素可能不完整（如果分号在行尾，则最后一个为空）
                    complete_statements = statements[:-1]
                    self.buffer = statements[-1].strip()
                    
                    for stmt in complete_statements:
                        stmt = stmt.strip()
                        if stmt:
                            self._process_statement(stmt)
                
                # 处理元命令（不以分号结尾的立即执行）
                if not self.buffer:
                    line = line.strip()
                    if line.startswith('\\'):
                        self._process_meta_command(line)
                    elif line:
                        # 单行语句无分号
                        self._process_statement(line)
                        
            except EOFError:
                print("\n")
                self._process_meta_command('\\q')
            except KeyboardInterrupt:
                self.buffer = ''
                print("\n[Interrupted]")
            except Exception as e:
                print(f"Error: {e}")
                self.buffer = ''
    
    def _process_statement(self, sql: str):
        """处理SQL语句"""
        try:
            self.db.logger.info(f"Executing: {sql[:50]}{'...' if len(sql)>50 else ''}")
            
            result = self.db.execute(sql)
            
            # 打印结果
            self._print_result(result)
            
        except Exception as e:
            print(f"Error: {e}")
    
    def _print_result(self, result):
        """打印执行结果"""
        # 尝试识别ResultSet对象
        if hasattr(result, 'rows'):
            # ResultSet格式
            rows = result.rows or []
            columns = result.columns or []
            
            if rows:
                # 打印列头
                col_names = [str(col) for col in columns]
                print(' | '.join(col_names))
                print('-' * (len(col_names) * 10))
                
                # 打印行（限制数量避免刷屏）
                for i, row in enumerate(rows):
                    if i >= 100:  # 限制显示100行
                        print(f"... ({len(rows)-100} more rows)")
                        break
                    values = [str(row.get(col, '')) for col in columns]
                    print(' | '.join(values))
                
                print(f"[{len(rows)} row(s) returned]")
            else:
                print("[No rows returned]")
                
            if hasattr(result, 'rows_affected') and result.rows_affected:
                print(f"[{result.rows_affected} row(s) affected]")
        else:
            # 简单结果（如事务命令）
            print(f"[OK] {result}")
    
    def _process_meta_command(self, command: str):
        """处理元命令"""
        if command == '\\q':
            print("Goodbye!")
            self.running = False
            self.db.shutdown()
        elif command == '\\h':
            self._show_help()
        elif command == '\\t':
            self._show_tables()
        elif command == '\\d':
            print("Usage: \\d <table_name>")
            print("  或: \\d (显示所有表结构)")
        elif command.startswith('\\d ') and len(command) > 3:
            table_name = command[3:].strip()
            self._describe_table(table_name)
        elif command == '\\st':
            self._show_stats()
        elif command == '\\c':
            print("\n" * 50)
        else:
            print(f"Unknown command: {command}")
    
    def _show_help(self):
        """显示帮助信息"""
        print("Available commands:")
        print("  SQL statements:  SELECT, INSERT, UPDATE, DELETE, CREATE TABLE, DROP TABLE, BEGIN, COMMIT, ROLLBACK")
        print("  Meta commands:")
        for cmd, desc in self.META_COMMANDS.items():
            print(f"    {cmd:6} - {desc}")
        print("\nExamples:")
        print("  CREATE TABLE t1 (id INTEGER PRIMARY KEY, name TEXT);")
        print("  INSERT INTO t1 VALUES (1, 'Alice');")
        print("  SELECT * FROM t1;")
        print("  BEGIN; UPDATE t1 SET name='Bob' WHERE id=1; COMMIT;")
    
    def _show_tables(self):
        """显示所有表"""
        try:
            # 尝试从executor的表元数据缓存获取
            executor = self.db.executor
            if hasattr(executor, 'table_metadata'):
                tables = list(executor.table_metadata.keys())
                if tables:
                    print("Tables:")
                    for table in tables:
                        print(f"  {table}")
                else:
                    print("No tables found.")
            else:
                print("No tables metadata available.")
        except Exception as e:
            print(f"Error listing tables: {e}")
    
    def _describe_table(self, table_name: str):
        """描述表结构"""
        try:
            executor = self.db.executor
            if hasattr(executor, 'table_metadata'):
                table_meta = executor.table_metadata.get(table_name)
                if table_meta:
                    print(f"Table: {table_name}")
                    print("Columns:")
                    for col in table_meta.columns:
                        pk = " (PRIMARY KEY)" if col.get('primary_key') else ""
                        null = "NULL" if col.get('nullable', True) else "NOT NULL"
                        print(f"  {col['name']} {col['type']} {null}{pk}")
                else:
                    print(f"Table '{table_name}' not found.")
            else:
                print("No table metadata available.")
        except Exception as e:
            print(f"Error describing table: {e}")
    
    def _show_stats(self):
        """显示统计信息"""
        try:
            stats = self.db.get_stats()
            print("Database Statistics:")
            
            if stats.get('buffer'):
                buf_stats = stats['buffer']
                print(f"  Buffer Pool: {buf_stats.get('used_frames', 0)}/{buf_stats.get('total_frames', 0)} frames used")
                print(f"    Hits: {buf_stats.get('hits', 0)}, Misses: {buf_stats.get('misses', 0)}")
                print(f"    Hit rate: {buf_stats.get('hit_rate', 0):.2%}")
                print(f"    Dirty pages: {buf_stats.get('dirty_frames', 0)}")
            
            if stats.get('wal'):
                wal_stats = stats['wal']
                print(f"  WAL: {wal_stats.get('logs_written', 0)} logs written")
                print(f"    Checkpoints: {wal_stats.get('checkpoints', 0)}")
                print(f"    Active transactions: {wal_stats.get('active_transactions', 0)}")
            
            if stats.get('executor'):
                print(f"  Executor stats: (implementation-dependent)")
            
        except Exception as e:
            print(f"Error getting stats: {e}")


def main():
    """REPL主入口"""
    # 加载配置
    config = DatabaseConfig()
    
    # 可以检查环境变量或命令行参数覆盖配置
    # ...
    
    try:
        # 创建数据库
        from integration.coordinator import create_database
        db = create_database(config)
        
        # 启动REPL
        repl = REPL(db)
        repl.start()
        
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()