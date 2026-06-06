#!/usr/bin/env python3
"""
预写式日志系统 (Write-Ahead Logging) - Python教学版本

本模块演示WAL的核心原理，包括：
1. 日志记录类型和格式
2. 日志写入和持久化（fsync模拟）
3. 检查点机制
4. 崩溃恢复流程（ARIES简化版）

代码简洁清晰，适合教学使用。
"""

import struct
import os
import json
from enum import IntEnum
from typing import Optional, List, Dict, Any, BinaryIO
from datetime import datetime


class LogType(IntEnum):
    """日志记录类型"""
    UPDATE = 1     # 更新操作
    INSERT = 2     # 插入操作
    DELETE = 3     # 删除操作
    COMMIT = 4     # 事务提交
    ABORT = 5      # 事务中止
    CHECKPOINT = 6 # 检查点


class LogRecord:
    """日志记录（通用格式）"""
    
    # 日志头格式: LSN(8), TID(4), Type(1), Size(4), PrevLSN(8)
    HEADER_FORMAT = 'QIIBQ'  # Q: uint64, I: uint32, B: uint8
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
    
    def __init__(self, log_type: LogType, tid: int, payload: bytes = b'', prev_lsn: int = 0):
        self.lsn: int = 0  # 稍后分配
        self.tid: int = tid
        self.type: LogType = log_type
        self.payload: bytes = payload
        self.prev_lsn: int = prev_lsn
        
    def serialize(self) -> bytes:
        """序列化日志记录"""
        # 构建头
        header = struct.pack(
            self.HEADER_FORMAT,
            self.lsn,
            self.tid,
            int(self.type),
            len(self.payload),
            self.prev_lsn
        )
        return header + self.payload
    
    @classmethod
    def deserialize(cls, data: bytes) -> 'LogRecord':
        """从字节流反序列化日志记录"""
        if len(data) < cls.HEADER_SIZE:
            raise ValueError("Data too short for log record")
        
        # 解析头
        lsn, tid, log_type_int, size, prev_lsn = struct.unpack(cls.HEADER_FORMAT, data[:cls.HEADER_SIZE])
        
        record = cls(
            log_type=LogType(log_type_int),
            tid=tid,
            payload=data[cls.HEADER_SIZE:cls.HEADER_SIZE+size],
            prev_lsn=prev_lsn
        )
        record.lsn = lsn
        return record
    
    def __repr__(self) -> str:
        return f"LogRecord(lsn={self.lsn}, tid={self.tid}, type={self.type.name}, size={len(self.payload)})"


class WALManager:
    """WAL管理器 - 简化版，用于教学演示"""
    
    def __init__(self, wal_file: str = 'wal.log', page_size: int = 4096):
        self.wal_file_path = wal_file
        self.page_size = page_size
        self.next_lsn: int = 1
        self.last_checkpoint_lsn: int = 0
        self.active_transactions: Dict[int, int] = {}  # tid -> last_lsn
        self.file: Optional[BinaryIO] = None
        self.dirty_page_table: Dict[int, int] = {}  # page_id -> rec_lsn
        
        # 统计
        self.stats = {
            'logs_written': 0,
            'fsync_calls': 0,
            'checkpoints': 0
        }
    
    def open(self) -> bool:
        """打开WAL文件（如果存在则追加，否则新建）"""
        mode = 'ab+' if os.path.exists(self.wal_file_path) else 'wb+'
        try:
            self.file = open(self.wal_file_path, mode)
            # 如果文件已存在，读取最后一条记录的LSN并统计日志数
            if mode == 'ab+':
                self._recover_lsn_from_file()
                # 统计文件中的日志数量（用于恢复统计）
                log_count = self._count_logs_in_file()
                self.stats['logs_written'] = log_count
            return True
        except Exception as e:
            print(f"Failed to open WAL file: {e}")
            return False
    
    def close(self):
        """关闭WAL文件"""
        if self.file:
            self.file.close()
            self.file = None
    
    def _recover_lsn_from_file(self):
        """从现有WAL文件恢复next_lsn"""
        # 简化：读取文件末尾，找到最大的LSN
        try:
            self.file.seek(0, os.SEEK_END)
            file_size = self.file.tell()
            
            # 从文件末尾向前扫描
            pos = file_size
            max_lsn = 0
            
            while pos > 0:
                # 向前跳一个日志记录（需要知道记录大小）
                # 简化：假设记录至少HEADER_SIZE，尝试读取头
                read_size = min(1024, pos)
                if pos - read_size < 0:
                    read_size = pos
                self.file.seek(pos - read_size)
                chunk = self.file.read(read_size)
                
                # 在chunk中搜索有效的日志头（从后向前）
                for i in range(len(chunk) - LogRecord.HEADER_SIZE, -1, -1):
                    try:
                        header_data = chunk[i:i+LogRecord.HEADER_SIZE]
                        lsn, tid, log_type, size, prev_lsn = struct.unpack(
                            LogRecord.HEADER_FORMAT, header_data)
                        # 基本验证：LSN应该递增且合理
                        if lsn > 0 and size <= 4096:  # 合理的日志大小
                            if lsn > max_lsn:
                                max_lsn = lsn
                            break
                    except:
                        continue
                
                if max_lsn > 0:
                    break
                pos -= read_size
            
            self.next_lsn = max_lsn + 1
            print(f"Recovered next_lsn = {self.next_lsn} from existing WAL")
        except Exception as e:
            print(f"Failed to recover LSN: {e}")
            self.next_lsn = 1
    
    def _count_logs_in_file(self) -> int:
        """统计WAL文件中的日志数量"""
        try:
            count = 0
            with open(self.wal_file_path, 'rb') as f:
                while True:
                    header = f.read(LogRecord.HEADER_SIZE)
                    if not header or len(header) < LogRecord.HEADER_SIZE:
                        break
                    lsn, tid, log_type, size, prev_lsn = struct.unpack(
                        LogRecord.HEADER_FORMAT, header)
                    f.read(size)  # 跳过数据
                    count += 1
            return count
        except Exception as e:
            print(f"Failed to count logs: {e}")
            return 0
    
    def allocate_lsn(self) -> int:
        lsn = self.next_lsn
        self.next_lsn += 1
        return lsn
    
    def append(self, tid: int, log_type: LogType, payload: bytes = b'', prev_lsn: int = 0) -> int:
        """追加日志记录（Write-Ahead核心）"""
        if not self.file:
            raise RuntimeError("WAL file not open")
        
        record = LogRecord(log_type, tid, payload, prev_lsn)
        record.lsn = self.allocate_lsn()
        
        # 序列化并写入
        data = record.serialize()
        self.file.write(data)
        self.file.flush()  # 刷新到操作系统缓冲区
        
        # 模拟fsync - 强制持久化到磁盘
        os.fsync(self.file.fileno())
        
        # 更新事务状态
        self.active_transactions[tid] = record.lsn
        
        # 对于数据修改操作，更新脏页表
        if log_type in (LogType.UPDATE, LogType.INSERT, LogType.DELETE):
            if payload:
                page_id = struct.unpack('I', payload[:4])[0]
                self.dirty_page_table[page_id] = record.lsn
        
        self.stats['logs_written'] += 1
        return record.lsn
    
    def force(self, lsn: Optional[int] = None):
        """强制持久化（fsync）"""
        if self.file:
            self.file.flush()
            os.fsync(self.file.fileno())
            self.stats['fsync_calls'] += 1
    
    # 适配Executor接口：保持与C++版本的命名一致
    def flush(self, lsn: Optional[int] = None):
        """刷新日志到磁盘（与force等价的适配方法）"""
        self.force(lsn)
    
    # 事务相关方法
    def begin_transaction(self, tid: int):
        """开始事务"""
        self.active_transactions[tid] = 0
    
    # 适配Executor接口：保持与C++版本的命名一致
    def log_begin(self, tid: int):
        """记录事务开始（BEGIN） - 适配层
        
        注意：在简化版ARIES中，BEGIN不单独写日志记录。
        事务的第一条更新日志隐含事务开始。
        这里只维护内存状态，不写入磁盘。
        """
        self.begin_transaction(tid)
    
    def commit(self, tid: int):
        """提交事务"""
        last_lsn = self.active_transactions.get(tid, 0)
        self.append(tid, LogType.COMMIT, b'', last_lsn)
        del self.active_transactions[tid]
    
    def abort(self, tid: int):
        """中止事务"""
        last_lsn = self.active_transactions.get(tid, 0)
        self.append(tid, LogType.ABORT, b'', last_lsn)
        del self.active_transactions[tid]
    
    # 检查点相关
    def create_checkpoint(self, active_transactions: Optional[List[int]] = None) -> int:
        """创建检查点"""
        if active_transactions is None:
            active_transactions = list(self.active_transactions.keys())
        
        # 构建检查点数据
        checkpoint_data = {
            'dirty_pages': list(self.dirty_page_table.items()),  # [(page_id, rec_lsn), ...]
            'active_transactions': active_transactions,
            'timestamp': datetime.now().isoformat(),
            'next_lsn': self.next_lsn
        }
        
        payload = json.dumps(checkpoint_data).encode('utf-8')
        
        # 写入CHECKPOINT记录
        lsn = self.append(0, LogType.CHECKPOINT, payload)
        self.last_checkpoint_lsn = lsn
        self.stats['checkpoints'] += 1
        
        print(f"Checkpoint created at LSN {lsn}, dirty pages: {len(self.dirty_page_table)}")
        return lsn
    
    # 崩溃恢复分析
    def analyze_recovery(self) -> Dict[str, Any]:
        """分析WAL文件，返回恢复所需的信息
        
        返回:
            dict with keys:
                - checkpoint_lsn: 最近的检查点LSN
                - dirty_page_table: {page_id: rec_lsn}
                - active_transactions: 未提交的事务ID列表
                - logs: 需要重放/撤销的日志记录列表（按LSN顺序）
                - redo_start_lsn: 重做开始LSN
                - next_lsn: 下一个可用的LSN
        """
        print("=" * 50)
        print("WAL Recovery Analysis...")
        print("=" * 50)
        
        if not os.path.exists(self.wal_file_path):
            print("No WAL file found")
            return {'status': 'fresh', 'logs': []}
        
        logs = []
        checkpoint_lsn = 0
        dirty_page_table = {}
        transaction_status = {}  # tid -> 'committed'/'uncommitted'
        
        with open(self.wal_file_path, 'rb') as f:
            while True:
                pos = f.tell()
                header_bytes = f.read(LogRecord.HEADER_SIZE)
                if not header_bytes or len(header_bytes) < LogRecord.HEADER_SIZE:
                    break
                
                try:
                    lsn, tid, log_type_int, size, prev_lsn = struct.unpack(
                        LogRecord.HEADER_FORMAT, header_bytes)
                    
                    payload = f.read(size) if size > 0 else b''
                    record = LogRecord(
                        LogType(log_type_int), tid, payload, prev_lsn
                    )
                    record.lsn = lsn
                    logs.append(record)
                    
                    # 跟踪检查点
                    if log_type_int == LogType.CHECKPOINT:
                        checkpoint_lsn = lsn
                        try:
                            data = json.loads(payload.decode('utf-8'))
                            dirty_page_table = {int(p): l for p, l in data.get('dirty_pages', [])}
                            next_lsn = data.get('next_lsn', lsn + 1)
                        except:
                            next_lsn = lsn + 1
                    
                    # 跟踪事务状态
                    if log_type_int == LogType.COMMIT:
                        transaction_status[tid] = 'committed'
                    elif log_type_int == LogType.ABORT:
                        transaction_status[tid] = 'aborted'
                    
                    # 更新脏页表（取最新的LSN）
                    if log_type_int in (LogType.UPDATE, LogType.INSERT, LogType.DELETE):
                        if payload:
                            page_id = struct.unpack('I', payload[:4])[0]
                            dirty_page_table[page_id] = lsn
                    
                except Exception as e:
                    print(f"Error parsing log at position {pos}: {e}")
                    break
        
        # 确定需要撤销的事务（没有COMMIT/ABORT的）
        active_transactions = set()
        for log in logs:
            if log.tid != 0:  # 忽略checkpoint的事务ID
                if log.tid not in transaction_status:
                    # 这个事务没有明确的COMMIT/ABORT，需要根据最后一条日志判断
                    pass
        
        # 获取每个事务的最后一条日志
        last_log_per_txn = {}
        for log in logs:
            if log.tid != 0:
                last_log_per_txn[log.tid] = log
        
        # 未提交的事务 = 没有COMMIT/ABORT且最后一条日志不是这些类型
        active_transactions = set()
        for tid, last_log in last_log_per_txn.items():
            if last_log.type not in (LogType.COMMIT, LogType.ABORT):
                active_transactions.add(tid)
        
        # 决定重做开始点：从检查点对应的脏页最小LSN开始
        redo_start_lsn = 0
        if dirty_page_table:
            redo_start_lsn = min(dirty_page_table.values())
        
        print(f"Analysis: checkpoint_lsn={checkpoint_lsn}, dirty_pages={len(dirty_page_table)}")
        print(f"  active_transactions={active_transactions}, redo_start_lsn={redo_start_lsn}")
        print(f"  total_logs={len(logs)}")
        
        return {
            'status': 'recovered' if checkpoint_lsn > 0 else 'no_checkpoint',
            'checkpoint_lsn': checkpoint_lsn,
            'dirty_page_table': dirty_page_table,
            'active_transactions': list(active_transactions),
            'logs': logs,
            'redo_start_lsn': redo_start_lsn,
            'next_lsn': next_lsn if 'next_lsn' in locals() else (logs[-1].lsn + 1 if logs else 1)
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = self.stats.copy()
        stats['next_lsn'] = self.next_lsn
        stats['active_transactions'] = len(self.active_transactions)
        stats['dirty_pages'] = len(self.dirty_page_table)
        return stats


# 辅助函数：构造UPDATE日志的payload
def build_update_payload(page_id: int, offset: int, old_value: bytes, new_value: bytes) -> bytes:
    """构建UPDATE操作的payload格式：
    page_id(4), offset(4), old_len(2), new_len(2), old_value, new_value
    """
    old_len = len(old_value)
    new_len = len(new_value)
    fmt = 'I IH H'  # page_id(uint32), offset(uint32), old_len(uint16), new_len(uint16)
    header = struct.pack(fmt, page_id, offset, old_len, new_len)
    return header + old_value + new_value


def build_insert_payload(page_id: int, offset: int, data: bytes) -> bytes:
    """构建INSERT操作的payload"""
    fmt = 'I I H'  # page_id, offset, length
    header = struct.pack(fmt, page_id, offset, len(data))
    return header + data


def build_delete_payload(page_id: int, offset: int, old_data: bytes) -> bytes:
    """构建DELETE操作的payload（包含旧数据用于撤销）
    page_id(4), offset(4), old_len(2), old_data
    """
    old_len = len(old_data)
    fmt = 'I I H'  # page_id, offset, old_len
    header = struct.pack(fmt, page_id, offset, old_len)
    return header + old_data


# 演示和测试用的模拟数据库
class MockDatabase:
    """模拟数据库，演示WAL工作原理"""
    
    def __init__(self, wal_manager: WALManager):
        self.wal = wal_manager
        self.data_pages: Dict[int, bytearray] = {}  # page_id -> page data
        self.page_size = 4096
        
        # 初始化一些数据页
        for i in range(10):
            self.data_pages[i] = bytearray(b'\x00' * self.page_size)
    
    def update(self, page_id: int, offset: int, old_val: bytes, new_val: bytes, tid: int) -> bool:
        """更新数据（Write-Ahead）"""
        # 1. 先写WAL (Write-Ahead规则)
        payload = build_update_payload(page_id, offset, old_val, new_val)
        lsn = self.wal.append(tid, LogType.UPDATE, payload)
        
        # 2. 修改缓冲区中的数据（标记脏）
        page = self.data_pages[page_id]
        page[offset:offset+len(new_val)] = new_val
        
        print(f"  Updated page {page_id}, offset {offset}, LSN={lsn}")
        return True
    
    def insert(self, page_id: int, offset: int, data: bytes, tid: int) -> bool:
        """插入数据"""
        payload = build_insert_payload(page_id, offset, data)
        lsn = self.wal.append(tid, LogType.INSERT, payload)
        
        page = self.data_pages[page_id]
        page[offset:offset+len(data)] = data
        
        print(f"  Inserted into page {page_id}, offset {offset}, LSN={lsn}")
        return True
    
    def delete(self, page_id: int, offset: int, old_data: bytes, tid: int) -> bool:
        """删除数据（清零区域）"""
        payload = build_delete_payload(page_id, offset, old_data)
        lsn = self.wal.append(tid, LogType.DELETE, payload)
        
        page = self.data_pages[page_id]
        page[offset:offset+len(old_data)] = b'\x00' * len(old_data)
        
        print(f"  Deleted from page {page_id}, offset {offset}, LSN={lsn}")
        return True
    
    def simulate_crash(self):
        """模拟系统崩溃"""
        print("\n" + "!"*50)
        print("SYSTEM CRASH! WAL will be used for recovery.")
        print("!"*50 + "\n")
        
        # 保存WAL文件用于恢复测试（已经在磁盘上）
        # 清空内存数据库（模拟崩溃后内存丢失）
        self.data_pages.clear()
        for i in range(10):
            self.data_pages[i] = bytearray(b'\x00' * self.page_size)
    
    def _apply_log(self, log: LogRecord) -> bool:
        """应用日志到数据页（重做/重放）
        
        返回: 是否成功应用
        """
        try:
            if log.type == LogType.UPDATE:
                # UPDATE payload: page_id(4), offset(4), old_len(2), new_len(2), old_value, new_value
                page_id, offset, old_len, new_len = struct.unpack('I I H H', log.payload[:12])
                new_value = log.payload[12+old_len:12+old_len+new_len]  # 修复偏移
                
                if page_id in self.data_pages:
                    page = self.data_pages[page_id]
                    page[offset:offset+len(new_value)] = new_value
                    return True
            
            elif log.type == LogType.INSERT:
                # INSERT payload: page_id(4), offset(4), length(2), data
                page_id, offset, length = struct.unpack('I I H', log.payload[:10])
                data = log.payload[10:10+length]
                
                if page_id in self.data_pages:
                    page = self.data_pages[page_id]
                    page[offset:offset+len(data)] = data
                    return True
            
            elif log.type == LogType.DELETE:
                # DELETE payload: page_id(4), offset(4), old_len(2), old_data
                page_id, offset, old_len = struct.unpack('I I H', log.payload[:10])
                old_data = log.payload[10:10+old_len]
                
                if page_id in self.data_pages:
                    page = self.data_pages[page_id]
                    # 删除操作：清零区域
                    page[offset:offset+old_len] = b'\x00' * old_len
                    return True
            
            return False
        except Exception as e:
            print(f"Error applying log LSN={log.lsn}: {e}")
            return False
    
    def _undo_log(self, log: LogRecord) -> bool:
        """撤销日志（回滚未提交事务）
        
        返回: 是否成功撤销
        """
        try:
            if log.type == LogType.UPDATE:
                # UPDATE payload: page_id(4), offset(4), old_len(2), new_len(2), old_value, new_value
                page_id, offset, old_len, new_len = struct.unpack('I I H H', log.payload[:12])
                old_value = log.payload[12:12+old_len]  # old_value直接在header后
                
                if page_id in self.data_pages:
                    page = self.data_pages[page_id]
                    page[offset:offset+len(old_value)] = old_value
                    return True
            
            elif log.type == LogType.INSERT:
                # INSERT需要UNDO：将插入的数据区域清零
                page_id, offset, length = struct.unpack('I I H', log.payload[:10])
                
                if page_id in self.data_pages:
                    page = self.data_pages[page_id]
                    page[offset:offset+length] = b'\x00' * length
                    return True
            
            elif log.type == LogType.DELETE:
                # DELETE需要UNDO：恢复旧数据
                page_id, offset, old_len = struct.unpack('I I H', log.payload[:10])
                old_data = log.payload[10:10+old_len]
                
                if page_id in self.data_pages:
                    page = self.data_pages[page_id]
                    page[offset:offset+len(old_data)] = old_data
                    return True
            
            return False
        except Exception as e:
            print(f"Error undoing log LSN={log.lsn}: {e}")
            return False
    
    def recover(self):
        """从WAL恢复数据库状态（完整恢复流程）"""
        print("=" * 50)
        print("Database Recovery Starting...")
        print("=" * 50)
        
        analysis = self.wal.analyze_recovery()
        
        if analysis['status'] == 'fresh':
            print("No WAL found, starting with empty database")
            return analysis
        
        logs = analysis['logs']
        active_tids = set(analysis['active_transactions'])
        redo_start_lsn = analysis['redo_start_lsn']
        
        # 重做阶段：重放所有数据修改日志（幂等）
        print(f"\nRedo phase (from LSN {redo_start_lsn}):")
        redo_count = 0
        
        for log in logs:
            if log.type in (LogType.UPDATE, LogType.INSERT, LogType.DELETE):
                if log.lsn >= redo_start_lsn:
                    if self._apply_log(log):
                        redo_count += 1
                        print(f"  Redo: LSN={log.lsn}, type={log.type.name}, tid={log.tid}")
        
        print(f"Redo applied {redo_count} operations")
        
        # 撤销阶段：回滚未提交事务（逆序）
        print("\nUndo phase:")
        undo_count = 0
        
        # 按LSN逆序排序需要撤销的日志
        logs_to_undo = [log for log in logs if log.tid in active_tids and log.type in (LogType.UPDATE, LogType.INSERT, LogType.DELETE)]
        logs_to_undo.sort(key=lambda x: x.lsn, reverse=True)
        
        for log in logs_to_undo:
            if self._undo_log(log):
                undo_count += 1
                print(f"  Undo: LSN={log.lsn}, type={log.type.name}, tid={log.tid}")
        
        print(f"Undo rolled back {undo_count} operations")
        
        stats = {
            'status': 'recovered',
            'checkpoint_lsn': analysis['checkpoint_lsn'],
            'dirty_pages_recovered': len(analysis['dirty_page_table']),
            'active_txns_rolled_back': undo_count,
            'logs_redone': redo_count,
            'total_logs_processed': len(logs)
        }
        
        print(f"\nRecovery Stats: {stats}")
        print("=" * 50)
        
        return stats


# 演示场景
def demo_wal_basic():
    """基础WAL演示"""
    print("=" * 60)
    print("WAL基础演示")
    print("=" * 60)
    
    # 1. 创建WAL管理器
    wal = WALManager('demo_wal.log')
    wal.open()
    
    # 2. 开始一个事务
    tid = 1
    wal.begin_transaction(tid)
    print(f"\n开始事务 T{tid}")
    
    # 3. 执行一些更新操作
    print("\n执行更新操作:")
    db = MockDatabase(wal)
    
    # 更新page 0
    db.update(0, 100, b'old1', b'new1', tid)
    
    # 更新page 1
    db.update(1, 200, b'old2', b'new2', tid)
    
    # 4. 提交事务
    wal.commit(tid)
    print(f"\n事务 T{tid} 已提交")
    
    # 5. 查看WAL统计
    print("\nWAL统计:", wal.get_stats())
    
    # 6. 创建检查点
    wal.create_checkpoint()
    
    wal.close()
    print("\n演示完成！")


def demo_wal_crash_recovery():
    """崩溃恢复演示"""
    print("\n" + "=" * 60)
    print("崩溃恢复演示")
    print("=" * 60)
    
    # 1. 准备数据库和WAL
    wal = WALManager('recovery_demo_wal.log')
    wal.open()
    db = MockDatabase(wal)
    
    # 2. 事务1: 提交
    tid1 = 1
    wal.begin_transaction(tid1)
    print(f"\n事务 {tid1}: 更新page 5")
    db.update(5, 100, b'A', b'B', tid1)
    wal.commit(tid1)
    
    # 3. 事务2: 未提交
    tid2 = 2
    wal.begin_transaction(tid2)
    print(f"\n事务 {tid2}: 更新page 6")
    db.update(6, 200, b'X', b'Y', tid2)
    # 注意：没有commit
    
    # 4. 事务3: 已提交
    tid3 = 3
    wal.begin_transaction(tid3)
    print(f"\n事务 {tid3}: 更新page 7")
    db.update(7, 300, b'P', b'Q', tid3)
    wal.commit(tid3)
    
    # 5. 创建检查点
    cp_lsn = wal.create_checkpoint()
    print(f"Checkpoint at LSN {cp_lsn}")
    
    wal.close()
    
    # 6. 模拟崩溃（清空内存数据库）
    print("\n[Simulating crash...]")
    db.simulate_crash()
    
    # 7. 恢复
    wal2 = WALManager('recovery_demo_wal.log')
    wal2.open()
    db2 = MockDatabase(wal2)
    
    stats = db2.recover()
    
    # 8. 验证
    print("\n恢复后验证:")
    print(f"  Page 5 (应从T{tid1}恢复): {db2.data_pages[5][100:101]}")
    print(f"  Page 6 (应保持原值X): {db2.data_pages[6][200:201]}")
    print(f"  Page 7 (应从T{tid3}恢复): {db2.data_pages[7][300:301]}")
    
    wal2.close()
    
    print("\n崩溃恢复演示完成！")


if __name__ == '__main__':
    # 运行演示
    demo_wal_basic()
    demo_wal_crash_recovery()
    
    print("\n" + "=" * 60)
    print("所有演示完成！")
    print("=" * 60)
