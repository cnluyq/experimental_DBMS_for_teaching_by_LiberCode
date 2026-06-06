#!/usr/bin/env python3
"""
实验性教学DBMS - 主程序入口
系统集成冲刺版本

功能：
- REPL模式接收SQL命令
- 模块初始化和协调
- 优雅关闭和错误处理
"""

import sys
import os
import signal
import readline
from typing import Optional, Dict, Any
from pathlib import Path

# 添加src到Python路径
sys.path.insert(0, str(Path(__file__).parent))

from core.storage_interface import StorageEngine
from core.buffer import BufferPool
from core.wal import WALManager
from index.bplus_tree import BPlusTree
from parser.parser import SQLParser
from executor.executor import Executor
from transaction.manager import TransactionManager


class Database:
    """数据库主类 - 管理所有组件"""
    
    def __init__(self, data_dir: str = "./data", wal_dir: str = "./wal"):
        """
        初始化数据库系统
        
        Args:
            data_dir: 数据文件目录
            wal_dir: WAL日志目录
        """
        self.data_dir = Path(data_dir)
        self.wal_dir = Path(wal_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.wal_dir.mkdir(parents=True, exist_ok=True)
        
        # 核心组件
        self.storage_engine: Optional[StorageEngine] = None
        self.buffer_pool: Optional[BufferPool] = None
        self.wal_manager: Optional[WALManager] = None
        self.transaction_manager: Optional[TransactionManager] = None
        self.parser: Optional[SQLParser] = None
        self.executor: Optional[Executor] = None
        self.indexes: Dict[str, BPlusTree] = {}
        
        # 状态标志
        self.is_running = False
        self.is_initialized = False
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)
    
    def initialize(self) -> bool:
        """
        初始化所有模块
        
        Returns:
            bool: 初始化是否成功
        """
        try:
            print("正在初始化数据库系统...")
            
            # 1. 初始化存储引擎
            print("  1/6 初始化存储引擎...")
            self.storage_engine = StorageEngine(str(self.data_dir))
            
            # 2. 初始化缓冲区池
            print("  2/6 初始化缓冲区池...")
            self.buffer_pool = BufferPool(self.storage_engine, pool_size=64)
            
            # 3. 初始化WAL日志
            print("  3/6 初始化WAL日志...")
            self.wal_manager = WALManager(str(self.wal_dir), self.storage_engine)
            
            # 4. 初始化事务管理器
            print("  4/6 初始化事务管理器...")
            self.transaction_manager = TransactionManager(
                wal=self.wal_manager,
                buffer_pool=self.buffer_pool
            )
            
            # 5. 初始化SQL解析器
            print("  5/6 初始化SQL解析器...")
            self.parser = SQLParser()
            
            # 6. 初始化执行引擎
            print("  6/6 初始化执行引擎...")
            self.executor = Executor(
                storage_engine=self.storage_engine,
                buffer_pool=self.buffer_pool,
                wal=self.wal_manager
            )
            
            # 恢复WAL（如果存在未完成的事务）
            self._recover_from_wal()
            
            self.is_initialized = True
            print("数据库系统初始化完成！")
            return True
            
        except Exception as e:
            print(f"初始化失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _recover_from_wal(self):
        """从WAL恢复数据"""
        if self.wal_manager:
            try:
                print("  正在从WAL恢复...")
                self.wal_manager.replay()
                print("  WAL恢复完成")
            except Exception as e:
                print(f"  WAL恢复警告: {e}")
    
    def start_repl(self):
        """启动REPL交互式命令行"""
        if not self.is_initialized:
            print("错误: 数据库未初始化")
            return
        
        self.is_running = True
        print("\n" + "="*60)
        print("实验性教学DBMS REPL")
        print("输入SQL语句执行，输入 '.exit' 或 'quit' 退出")
        print("="*60 + "\n")
        
        # 设置readline历史
        history_file = Path.home() / ".dbms_history"
        try:
            if history_file.exists():
                readline.read_history_file(str(history_file))
        except:
            pass
        
        try:
            while self.is_running:
                try:
                    # 获取用户输入
                    sql = input("db> ").strip()
                    
                    if not sql:
                        continue
                    
                    if sql.lower() in ('.exit', 'quit', 'exit'):
                        break
                    
                    # 解析SQL
                    try:
                        ast = self.parser.parse(sql)
                    except Exception as e:
                        print(f"语法错误: {e}")
                        continue
                    
                    # 执行SQL
                    try:
                        result = self.executor.execute(ast)
                        
                        # 显示结果
                        if result.success:
                            self._display_result(result)
                        else:
                            print(f"执行错误: {result.error_message}")
                            
                    except Exception as e:
                        print(f"执行异常: {e}")
                        import traceback
                        traceback.print_exc()
                        
                except KeyboardInterrupt:
                    print("\n(中断 - 输入.exit退出)")
                    continue
                except EOFError:
                    break
                    
        finally:
            # 保存历史
            try:
                readline.write_history_file(str(history_file))
            except:
                pass
            self.shutdown()
    
    def _display_result(self, result):
        """显示查询结果"""
        if result.rows:
            # 获取列名
            if result.columns:
                print(" | ".join(f"{col:<15}" for col in result.columns))
                print("-" * (len(result.columns) * 17))
            
            # 显示行
            for row in result.rows:
                print(" | ".join(f"{str(value):<15}" for value in row))
            
            print(f"({len(result.rows)} 行)")
        elif result.rows_affected is not None:
            print(f"成功: {result.rows_affected} 行受影响")
        else:
            print("成功")
    
    def shutdown(self):
        """优雅关闭数据库"""
        if not self.is_running:
            return
        
        print("\n正在关闭数据库...")
        
        try:
            # 提交所有未完成的事务
            if self.transaction_manager:
                try:
                    self.transaction_manager.shutdown()
                except:
                    pass
            
            # 关闭所有组件
            if self.executor:
                try:
                    self.executor.shutdown()
                except:
                    pass
            
            if self.wal_manager:
                try:
                    self.wal_manager.close()
                except:
                    pass
            
            if self.buffer_pool:
                try:
                    self.buffer_pool.flush_all()
                    self.buffer_pool.close()
                except:
                    pass
            
            if self.storage_engine:
                try:
                    self.storage_engine.close()
                except:
                    pass
            
            print("数据库已关闭")
            
        except Exception as e:
            print(f"关闭时发生错误: {e}")
        finally:
            self.is_running = False
    
    def _handle_shutdown(self, signum, frame):
        """信号处理函数"""
        print(f"\n收到信号 {signum}, 正在关闭...")
        self.is_running = False


def main():
    """主函数"""
    # 解析命令行参数
    data_dir = "./data"
    wal_dir = "./wal"
    
    if len(sys.argv) > 1:
        data_dir = sys.argv[1]
    if len(sys.argv) > 2:
        wal_dir = sys.argv[2]
    
    # 创建并启动数据库
    db = Database(data_dir=data_dir, wal_dir=wal_dir)
    
    if db.initialize():
        db.start_repl()
    else:
        print("数据库启动失败")
        sys.exit(1)


if __name__ == "__main__":
    main()