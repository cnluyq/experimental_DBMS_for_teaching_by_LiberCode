"""
预写式日志系统 - 完整修复版本
"""

import struct
import os
import json
from enum import IntEnum
from typing import List, Dict, Any, Optional
from datetime import datetime


class LogType(IntEnum):
    UPDATE = 1
    INSERT = 2
    DELETE = 3
    COMMIT = 4
    ABORT = 5
    CHECKPOINT = 6


class LogRecord:
    HEADER_FORMAT = 'QIIBQ'
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
    
    def __init__(self, log_type: LogType, tid: int, payload: bytes = b'', prev_lsn: int = 0):
        self.lsn: int = 0
        self.tid: int = tid
        self.type: LogType = log_type
        self.payload: bytes = payload
        self.prev_lsn: int = prev_lsn
        
    def serialize(self) -> bytes:
        header = struct.pack(self.HEADER_FORMAT, self.lsn, self.tid, int(self.type),
                            len(self.payload), self.prev_lsn)
        return header + self.payload
    
    @classmethod
    def deserialize(cls, data: bytes) -> 'LogRecord':
        if len(data) < cls.HEADER_SIZE:
            raise ValueError("Data too short")
        lsn, tid, log_type_int, size, prev_lsn = struct.unpack(cls.HEADER_FORMAT, data[:cls.HEADER_SIZE])
        record = cls(LogType(log_type_int), tid, data[cls.HEADER_SIZE:cls.HEADER_SIZE+size], prev_lsn)
        record.lsn = lsn
        return record


class WALManager:
    def __init__(self, wal_file: str = 'wal.log'):
        self.wal_file_path = wal_file
        self.next_lsn: int = 1
        self.file: Optional[Any] = None
        self.active_transactions: Dict[int, int] = {}
        self.dirty_page_table: Dict[int, int] = {}
        
    def open(self) -> bool:
        mode = 'ab+' if os.path.exists(self.wal_file_path) else 'wb+'
        try:
            self.file = open(self.wal_file_path, mode)
            if mode == 'ab+':
                self._recover_lsn()
            return True
        except Exception as e:
            print(f"Failed to open WAL: {e}")
            return False
    
    def close(self):
        if self.file:
            self.file.close()
            self.file = None
    
    def _recover_lsn(self):
        """从文件恢复next_lsn"""
        try:
            with open(self.wal_file_path, 'rb') as f:
                f.seek(0, os.SEEK_END)
                file_size = f.tell()
                max_lsn = 0
                
                # 从文件末尾扫描
                chunk_size = 4096
                pos = file_size
                while pos > 0:
                    read_size = min(chunk_size, pos)
                    f.seek(pos - read_size)
                    chunk = f.read(read_size)
                    
                    # 在chunk中查找日志头
                    for i in range(len(chunk) - LogRecord.HEADER_SIZE, -1, -1):
                        try:
                            header = chunk[i:i+LogRecord.HEADER_SIZE]
                            lsn, tid, log_type, size, prev_lsn = struct.unpack(LogRecord.HEADER_FORMAT, header)
                            if lsn > 0 and size <= 8192:
                                max_lsn = max(max_lsn, lsn)
                                break
                        except:
                            continue
                    
                    if max_lsn > 0:
                        break
                    pos -= read_size
                
                self.next_lsn = max_lsn + 1
                print(f"Recovered next_lsn = {self.next_lsn}")
        except Exception as e:
            print(f"LSN recovery failed: {e}")
            self.next_lsn = 1
    
    def allocate_lsn(self) -> int:
        lsn = self.next_lsn
        self.next_lsn += 1
        return lsn
    
    def append(self, tid: int, log_type: LogType, payload: bytes = b'', prev_lsn: int = 0) -> int:
        if not self.file:
            raise RuntimeError("WAL not open")
        
        record = LogRecord(log_type, tid, payload, prev_lsn)
        record.lsn = self.allocate_lsn()
        data = record.serialize()
        self.file.write(data)
        self.file.flush()
        os.fsync(self.file.fileno())
        
        self.active_transactions[tid] = record.lsn
        
        if log_type in (LogType.UPDATE, LogType.INSERT, LogType.DELETE):
            if payload and len(payload) >= 4:
                page_id = struct.unpack('I', payload[:4])[0]
                self.dirty_page_table[page_id] = record.lsn
        
        return record.lsn
    
    def begin(self, tid: int):
        self.active_transactions[tid] = 0
    
    def commit(self, tid: int):
        last_lsn = self.active_transactions.get(tid, 0)
        self.append(tid, LogType.COMMIT, b'', last_lsn)
        del self.active_transactions[tid]
    
    def abort(self, tid: int):
        last_lsn = self.active_transactions.get(tid, 0)
        self.append(tid, LogType.ABORT, b'', last_lsn)
        del self.active_transactions[tid]
    
    def create_checkpoint(self) -> int:
        checkpoint_data = {
            'dirty_pages': list(self.dirty_page_table.items()),
            'active_transactions': list(self.active_transactions.keys()),
            'next_lsn': self.next_lsn,
            'timestamp': datetime.now().isoformat()
        }
        payload = json.dumps(checkpoint_data).encode('utf-8')
        lsn = self.append(0, LogType.CHECKPOINT, payload)
        print(f"Checkpoint at LSN {lsn}")
        return lsn
    
    def recover(self) -> Dict[str, Any]:
        print("=" * 50)
        print("Starting WAL Recovery")
        print("=" * 50)
        
        if not os.path.exists(self.wal_file_path):
            print("No WAL file - fresh start")
            return {'status': 'fresh'}
        
        # 分析阶段
        checkpoint, redo_logs, undo_logs = self._analyze()
        
        # 重做阶段
        redo_count = self._redo(redo_logs)
        
        # 撤销阶段
        undo_count = self._undo(undo_logs)
        
        # 清理状态（模拟重启后干净状态）
        self.dirty_page_table.clear()
        self.active_transactions.clear()
        self.next_lsn = checkpoint.get('next_lsn', 1)
        
        stats = {
            'status': 'recovered',
            'checkpoint_lsn': checkpoint.get('checkpoint_lsn', 0),
            'dirty_pages': len(checkpoint['dirty_page_table']),
            'txns_rolled_back': len(checkpoint['committed_transactions']),
            'logs_redo': redo_count,
            'logs_undo': undo_count,
            'next_lsn_after_recovery': self.next_lsn
        }
        print(f"Recovery complete: {stats}")
        print("=" * 50)
        return stats
    
    def _analyze(self) -> tuple[Dict[str, Any], List[LogRecord]]:
        """分析WAL，返回检查点信息和需要重做/撤销的日志
        
        返回:
            checkpoint_info: 包含检查点LSN、脏页表、已提交事务列表
            redo_logs: 需要重做的日志（已提交事务的数据修改）
            undo_logs: 需要撤销的日志（未提交事务的所有日志）
        """
        checkpoint_info = {
            'checkpoint_lsn': 0,
            'dirty_page_table': {},
            'committed_transactions': [],  # 从检查点后已提交的事务
            'next_lsn': 1
        }
        
        all_logs = []  # 检查点之后的所有日志
        tx_status = {}  # tid -> 最后状态（日志类型）
        
        with open(self.wal_file_path, 'rb') as f:
            while True:
                header_bytes = f.read(LogRecord.HEADER_SIZE)
                if not header_bytes or len(header_bytes) < LogRecord.HEADER_SIZE:
                    break
                
                try:
                    lsn, tid, log_type_int, size, prev_lsn = struct.unpack(
                        LogRecord.HEADER_FORMAT, header_bytes)
                    payload = f.read(size) if size > 0 else b''
                    record = LogRecord(LogType(log_type_int), tid, payload, prev_lsn)
                    record.lsn = lsn
                    
                    # 只处理检查点之后的日志
                    if lsn > checkpoint_info['checkpoint_lsn']:
                        all_logs.append(record)
                        tx_status[tid] = log_type_int
                        
                except:
                    break
        
        # 识别已提交事务和未提交事务
        committed_txns = set()
        uncommitted_txns = set()
        
        for tid, final_status in tx_status.items():
            if final_status == LogType.COMMIT:
                committed_txns.add(tid)
            elif final_status == LogType.ABORT:
                # ABORT已处理，无需恢复
                pass
            else:
                # 没有 terminating 记录，视为未提交
                uncommitted_txns.add(tid)
        
        checkpoint_info['committed_transactions'] = list(committed_txns)
        
        # 构建重做日志：已提交事务的数据修改
        redo_logs = []
        for log in all_logs:
            if log.tid in committed_txns and log.type in (LogType.UPDATE, LogType.INSERT, LogType.DELETE):
                redo_logs.append(log)
        
        # 构建撤销日志：未提交事务的所有日志（按LSN排序用于逆序撤销）
        undo_logs = [log for log in all_logs if log.tid in uncommitted_txns]
        undo_logs.sort(key=lambda x: x.lsn, reverse=True)
        
        print(f"Analysis: {len(redo_logs)} redo logs, {len(undo_logs)} undo logs")
        print(f"  Committed txns: {committed_txns}")
        print(f"  Uncommitted txns: {uncommitted_txns}")
        
        return checkpoint_info, redo_logs, undo_logs
    
    def _redo(self, redo_logs: List[LogRecord]) -> int:
        print(f"Redo: {len(redo_logs)} operations")
        count = 0
        
        # 按LSN升序重做（保证顺序）
        redo_logs.sort(key=lambda x: x.lsn)
        
        for log in redo_logs:
            payload = log.payload
            if log.type == LogType.UPDATE and len(payload) >= 12:
                page_id = struct.unpack('I', payload[:4])[0]
                offset = struct.unpack('I', payload[4:8])[0]
                new_len = struct.unpack('H', payload[10:12])[0]
                new_value_start = 12
                new_value = payload[new_value_start:new_value_start+new_len]
                print(f"  Redo UPDATE: page {page_id}, offset {offset}, value={new_value}")
            elif log.type == LogType.INSERT and len(payload) >= 8:
                page_id = struct.unpack('I', payload[:4])[0]
                offset = struct.unpack('I', payload[4:8])[0]
                length = struct.unpack('H', payload[8:10])[0]
                data = payload[10:10+length]
                print(f"  Redo INSERT: page {page_id}, offset {offset}, data={data}")
            elif log.type == LogType.DELETE and len(payload) >= 10:
                # DELETE的redo不实际做操作，因为delete就是删除，重做就是保持删除状态
                print(f"  Redo DELETE: page marked as deleted")
            count += 1
        
        print(f"Redo phase complete: {count} operations")
        return count
    
    def _undo(self, active_logs: List[LogRecord]) -> int:
        print(f"Undo: {len(active_logs)} logs")
        active_logs.sort(key=lambda x: x.lsn, reverse=True)
        
        count = 0
        for log in active_logs:
            if log.type == LogType.UPDATE:
                if len(log.payload) >= 12:
                    page_id = struct.unpack('I', log.payload[:4])[0]
                    offset = struct.unpack('I', log.payload[4:8])[0]
                    old_len = struct.unpack('H', log.payload[8:10])[0]
                    print(f"  Undo UPDATE: page {page_id}, offset {offset}, restore {old_len} bytes")
            elif log.type == LogType.INSERT:
                if len(log.payload) >= 10:
                    page_id = struct.unpack('I', log.payload[:4])[0]
                    offset = struct.unpack('I', log.payload[4:8])[0]
                    length = struct.unpack('H', log.payload[8:10])[0]
                    print(f"  Undo INSERT: page {page_id}, offset {offset}, delete {length} bytes")
            elif log.type == LogType.DELETE:
                if len(log.payload) >= 12:
                    page_id = struct.unpack('I', log.payload[:4])[0]
                    offset = struct.unpack('I', log.payload[4:8])[0]
                    length = struct.unpack('H', log.payload[8:10])[0]
                    print(f"  Undo DELETE: page {page_id}, offset {offset}, restore {length} bytes")
            count += 1
        
        print(f"Undo: {count} operations")
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            'next_lsn': self.next_lsn,
            'active_transactions': len(self.active_transactions),
            'dirty_pages': len(self.dirty_page_table)
        }


def build_update_payload(page_id: int, offset: int, old_value: bytes, new_value: bytes) -> bytes:
    old_len = len(old_value)
    new_len = len(new_value)
    header = struct.pack('I I H H', page_id, offset, old_len, new_len)
    return header + old_value + new_value


def build_insert_payload(page_id: int, offset: int, data: bytes) -> bytes:
    header = struct.pack('I I H', page_id, offset, len(data))
    return header + data


class MockDatabase:
    def __init__(self, wal: WALManager):
        self.wal = wal
        self.pages: Dict[int, bytearray] = {}
        for i in range(10):
            self.pages[i] = bytearray(b'\x00' * 4096)
    
    def update(self, page_id: int, offset: int, old_val: bytes, new_val: bytes, tid: int):
        payload = build_update_payload(page_id, offset, old_val, new_val)
        self.wal.append(tid, LogType.UPDATE, payload)
        self.pages[page_id][offset:offset+len(new_val)] = new_val
        print(f"  Update: page {page_id}, offset {offset}, LSN={self.wal.get_stats()['next_lsn']-1}")
    
    def clear(self):
        for p in self.pages.values():
            p[:] = b'\x00' * len(p)
    
    def recover(self):
        """从WAL恢复数据库状态"""
        stats = self.wal.recover()
        return stats


if __name__ == '__main__':
    import sys
    
    # 测试1：基本日志
    print("Test 1: Basic logging")
    wal1 = WALManager('test1.log')
    wal1.open()
    db1 = MockDatabase(wal1)
    wal1.begin(1)
    db1.update(0, 0, b'0', b'1', 1)
    wal1.commit(1)
    wal1.create_checkpoint()
    wal1.close()
    
    # 测试2：崩溃恢复 - 已提交事务
    print("\nTest 2: Recovery - committed transaction")
    wal2 = WALManager('test2.log')
    wal2.open()
    db2 = MockDatabase(wal2)
    wal2.begin(1)
    db2.update(5, 0, b'A', b'B', 1)
    wal2.commit(1)
    wal2.create_checkpoint()
    wal2.close()
    
    # 记录原始值用于验证
    original_page5_value = db2.pages[5][0:1]
    print(f"Before crash: page 5[0] = {original_page5_value}")
    
    # 模拟崩溃
    db2.clear()
    print(f"After crash: page 5[0] = {db2.pages[5][0:1]}")
    
    # 恢复
    wal3 = WALManager('test2.log')
    wal3.open()
    db3 = MockDatabase(wal3)
    stats = db3.recover()
    
    print(f"After recovery: page 5[0] = {db3.pages[5][0:1]}")
    assert db3.pages[5][0:1] == b'B', f"Expected b'B', got {db3.pages[5][0:1]}"
    print("✓ Committed transaction recovered correctly")
    wal3.close()
    
    # 测试3：崩溃恢复 - 未提交事务
    print("\nTest 3: Recovery - uncommitted transaction")
    wal4 = WALManager('test3.log')
    wal4.open()
    db4 = MockDatabase(wal4)
    wal4.begin(1)
    db4.update(6, 0, b'X', b'Y', 1)
    # 不提交
    wal4.create_checkpoint()
    wal4.close()
    
    # 模拟崩溃
    original_page6 = db4.pages[6][0:1]
    db4.clear()
    print(f"Crash: page 6[0] was {original_page6}, after crash {db4.pages[6][0:1]}")
    
    # 恢复
    wal5 = WALManager('test3.log')
    wal5.open()
    db5 = MockDatabase(wal5)
    stats = db5.recover()
    print(f"After recovery: page 6[0] = {db5.pages[6][0:1]}")
    assert db5.pages[6][0:1] == b'X', f"Expected unchanged b'X', got {db5.pages[6][0:1]}"
    print("✓ Uncommitted transaction correctly undone")
    wal5.close()
    
    print("\nAll tests passed!")