#!/usr/bin/env python3
"""
实验性教学DBMS - REPL主程序
系统集成冲刺版本 - 阶段1

功能：
- REPL模式接收SQL命令
- 整合所有核心模块（通过coordinator）
- 优雅关闭和错误处理
"""

import sys
import os
import signal
import readline
from pathlib import Path

# 添加src和根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent))

from integration.coordinator import create_database, DatabaseConfig
from parser.parser import parse
from parser.tokenizer import TokenizerError
from parser.parser import ParserError


def _display_single_result(result, quiet=False):
    """显示单条命令结果"""
    if result.success:
        # 判断是否是真正的数据行
        has_data_rows = (
            result.rows and 
            len(result.rows) > 0 and
            isinstance(result.rows[0], dict) and
            not ('record_id' in result.rows[0] and 'rows_affected' in result.rows[0])
        )
        
        if has_data_rows:
            # 有真正数据行 - 以表格形式显示
            print()
            result.print_table()
        elif result.rows_affected:
            print(f"Rows affected: {result.rows_affected}")
        elif result.message and not quiet:
            print(result.message)
    else:
        print(f"Error: {result.error or result.message}")


class REPL:
    """交互式SQL执行环境"""
    
    def __init__(self, db):
        self.db = db
        self.running = False
    
    def run(self):
        """运行REPL主循环"""
        self.running = True
        
        # 设置信号处理
        def signal_handler(signum, frame):
            print("\n收到中断信号，正在退出...")
            self.running = False
        
        signal.signal(signal.SIGINT, signal_handler)
        
        print("\n" + "="*60)
        print("  实验性教学DBMS - REPL")
        print("="*60)
        print("  输入SQL语句执行")
        print("  .help - 显示帮助")
        print("  .tables - 列出所有表")
        print("  .schema <表名> - 显示表结构")
        print("  .quit / .exit - 退出")
        print("="*60 + "\n")
        
        # 设置历史记录
        self._setup_history()
        
        while self.running:
            try:
                sql = input("db> ").strip()
                
                if not sql:
                    continue
                
                # 处理元命令
                if sql.startswith('.'):
                    self._handle_meta_command(sql)
                    continue
                
                # 执行SQL
                self._execute_sql(sql)
                
            except KeyboardInterrupt:
                print("\n(按 Ctrl+C 或输入 .quit 退出)")
            except EOFError:
                print("\n再见!")
                break
                
        # 关闭数据库
        self.db.shutdown()
        self._save_history()
    
    def _execute_sql(self, sql: str):
        """执行单条SQL"""
        try:
            # 解析SQL
            ast = parse(sql)
            
            # 执行
            result = self.db.executor.execute(ast)
            
            # 显示结果
            if result.success:
                self._display_result(result)
            else:
                print(f"执行错误: {result.error or result.message}")
                
        except TokenizerError as e:
            print(f"词法错误: {e}")
        except ParserError as e:
            print(f"语法错误: {e}")
        except Exception as e:
            print(f"执行异常: {e}")
    
    def _display_result(self, result):
        """显示查询结果"""
        # 检查是否有特殊的统计行（可能是DML返回的元数据）
        # 例如 INSERT 可能返回 {'record_id': 1, 'rows_affected': 1}
        # 这种情况下我们只显示成功消息
        
        if result.rows and len(result.rows) == 1:
            row = result.rows[0]
            if isinstance(row, dict):
                # 检查是否是统计信息行
                if 'record_id' in row or 'rows_affected' in row:
                    affected = row.get('rows_affected', row.get('record_id', 1))
                    print(f"成功: {affected} 行受影响")
                    if result.message:
                        print(f"  {result.message}")
                    return
        
        # SELECT结果 - 表格形式显示
        if result.rows:
            self._print_table(result)
            return
        
        # INSERT/UPDATE/DELETE - 显示影响行数
        if result.rows_affected:
            print(f"成功: {result.rows_affected} 行受影响")
            if result.message:
                print(f"  {result.message}")
        elif result.message:
            print(result.message)
        else:
            print("查询成功")
    
    def _print_table(self, result):
        """以表格形式打印结果"""
        rows = result.rows
        columns = result.columns or (list(rows[0].keys()) if rows else [])
        
        if not columns:
            print("Empty result")
            return
        
        # 计算列宽
        col_widths = {col: len(str(col)) for col in columns}
        for row in rows:
            if isinstance(row, dict):
                for col in columns:
                    col_widths[col] = max(col_widths[col], len(str(row.get(col, ''))))
        
        # 打印表头
        header = " | ".join(str(col).ljust(col_widths[col]) for col in columns)
        print(header)
        print("-" * len(header))
        
        # 打印数据行
        for row in rows:
            if isinstance(row, dict):
                line = " | ".join(str(row.get(col, '')).ljust(col_widths[col]) for col in columns)
            else:
                line = " | ".join(str(v).ljust(col_widths[columns[i]]) for i, v in enumerate(row))
            print(line)
        
        print(f"\n({len(rows)} 行)")
    
    def _handle_meta_command(self, cmd: str):
        """处理元命令"""
        cmd = cmd[1:].strip()  # 去掉前导 '.'
        parts = cmd.split(maxsplit=1)
        command = parts[0].lower() if parts else ''
        arg = parts[1] if len(parts) > 1 else ''
        
        if command == 'quit' or command == 'exit':
            self.running = False
        elif command == 'help':
            print("""
可用命令:
  .help          显示此帮助
  .tables        列出所有表
  .schema <表>   显示表结构
  .quit          退出
  
支持的SQL:
  CREATE TABLE, DROP TABLE
  SELECT, INSERT, UPDATE, DELETE
  BEGIN, COMMIT, ROLLBACK
""")
        elif command == 'tables':
            self._list_tables()
        elif command == 'schema' and arg:
            self._show_schema(arg)
        elif command == 'schema':
            print("用法: .schema <表名>")
        else:
            print(f"未知命令: .{command}")
    
    def _list_tables(self):
        """列出所有表"""
        tables = self.db.db_storage.tables
        if not tables:
            print("暂无表")
            return
        
        print("表列表:")
        for name in tables:
            print(f"  - {name}")
    
    def _show_schema(self, table_name: str):
        """显示表结构"""
        tables = self.db.db_storage.tables
        if table_name not in tables:
            print(f"表 '{table_name}' 不存在")
            return
        
        meta = tables[table_name]
        print(f"\n表: {table_name}")
        print("-" * 40)
        print(f"{'列名':<20} {'类型':<10} {'约束'}")
        print("-" * 40)
        
        for col in meta.columns:
            name = col.get('name', '')
            ctype = col.get('type', 'TEXT')
            constraints = []
            if col.get('primary_key'):
                constraints.append('PK')
            if not col.get('nullable', True):
                constraints.append('NOT NULL')
            if col.get('unique'):
                constraints.append('UNIQUE')
            
            print(f"{name:<20} {ctype:<10} {' '.join(constraints)}")
        print()
    
    def _setup_history(self):
        """设置历史记录"""
        self.history_file = Path.home() / ".projo_history"
        try:
            if self.history_file.exists():
                readline.read_history_file(str(self.history_file))
        except:
            pass
    
    def _save_history(self):
        """保存历史记录"""
        try:
            readline.write_history_file(str(self.history_file))
        except:
            pass


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='ProjoDB - 实验性教学数据库')
    parser.add_argument('data_dir', nargs='?', default='./data', help='数据目录')
    parser.add_argument('-e', '--execute', help='执行单条SQL并退出')
    parser.add_argument('--no-wal', action='store_true', help='禁用WAL')
    parser.add_argument('-q', '--quiet', action='store_true', help='静默模式')
    parser.add_argument('--memory', action='store_true', help='使用内存存储')
    
    args = parser.parse_args()
    
    # 确定存储类型
    storage_type = 'memory' if args.memory else 'file'
    
    # 创建数据库配置
    config = DatabaseConfig(
        data_dir=args.data_dir,
        storage_type=storage_type,
        buffer_pool_size=64,
        wal_enabled=not args.no_wal,
        autocommit=True,
        log_level='WARNING' if args.quiet else 'INFO'
    )
    
    # 确保数据目录存在
    os.makedirs(args.data_dir, exist_ok=True)
    
    try:
        db = create_database(config)
        
        if args.execute:
            # 单命令模式
            if not args.quiet:
                print(f"Executing: {args.execute}")
            
            try:
                # 支持多语句（以;分隔）
                statements = args.execute.split(';')
                valid_stmts = [s.strip() for s in statements if s.strip()]
                
                for i, stmt in enumerate(valid_stmts):
                    ast = parse(stmt + ';')
                    result = db.executor.execute(ast)
                    
                    # 只对最后一个语句显示详细结果
                    if i == len(valid_stmts) - 1:
                        _display_single_result(result, args.quiet)
                    else:
                        # 静默显示中间结果
                        if result.rows_affected and not args.quiet:
                            print(f"  ↳ {result.rows_affected} rows affected")
                        elif result.message and not args.quiet:
                            print(f"  ↳ {result.message}")
                    
            except Exception as e:
                print(f"SQL Error: {e}")
                import traceback
                traceback.print_exc()
                sys.exit(1)
            finally:
                db.shutdown()
        else:
            # REPL模式
            if not args.quiet:
                print("正在初始化数据库...")
                print("数据库初始化成功！\n")
            
            repl = REPL(db)
            repl.run()
        
    except Exception as e:
        print(f"启动失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()