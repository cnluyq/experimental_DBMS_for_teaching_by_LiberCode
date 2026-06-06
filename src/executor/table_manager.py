"""
表记录管理器

管理表的元数据和记录访问。
提供记录级别的CRUD操作接口，封装底层页面存储细节。
"""

from typing import Optional, List, Dict, Any, Iterator, Tuple
from core.storage_interface import StorageEngine


class TableMetadata:
    """表元数据"""
    
    def __init__(self, table_name: str, columns: List[Dict[str, Any]]):
        """
        初始化表元数据
        
        Args:
            table_name: 表名
            columns: 列定义列表，每个元素是包含以下键的字典：
                - name: 列名
                - type: 数据类型（'INTEGER', 'FLOAT', 'TEXT', 'NULL'）
                - nullable: 是否可空
                - primary_key: 是否为主键
        """
        self.table_name = table_name
        self.columns = columns
        self.column_map = {col['name']: i for i, col in enumerate(columns)}
        
        # 记录格式：每条记录有头部信息 + 列数据
        self.record_header_size = 8  # 4字节记录ID + 1字节状态 + 3字节保留
        self.max_columns = len(columns)
    
    def get_column_index(self, column_name: str) -> Optional[int]:
        """获取列索引"""
        return self.column_map.get(column_name)
    
    def get_column_type(self, column_name: str) -> str:
        """获取列的数据类型"""
        idx = self.get_column_index(column_name)
        if idx is not None:
            return self.columns[idx]['type']
        return 'TEXT'  # 默认
    
    def get_nullable(self, column_name: str) -> bool:
        """获取列是否可空"""
        idx = self.get_column_index(column_name)
        if idx is not None:
            return self.columns[idx].get('nullable', True)
        return True


class Record:
    """表记录"""
    
    def __init__(self, table_meta: TableMetadata, record_id: int, values: Dict[str, Any]):
        """
        初始化记录
        
        Args:
            table_meta: 表元数据
            record_id: 记录ID（唯一标识）
            values: 列名到值的映射
        """
        self.table_meta = table_meta
        self.record_id = record_id
        self.values = values.copy()
    
    def to_bytes(self) -> bytes:
        """
        将记录序列化为字节数据
        
        简化格式：
        - 4字节：记录ID（小端int）
        - N字节：列数据（每列前缀1字节表示是否NULL，然后是数据）
        （实际设计会更复杂，需要考虑变长字段）
        """
        import struct
        data = struct.pack('<I', self.record_id)  # 小端32位整数
        
        # 按列定义顺序写入每列数据
        for col in self.table_meta.columns:
            col_name = col['name']
            col_type = col['type']
            value = self.values.get(col_name, None)
            
            if value is None:
                # NULL标记
                data += b'\x01'  # 1表示NULL
            else:
                data += b'\x00'  # 0表示非NULL
                # 根据类型编码
                if col_type == 'INTEGER':
                    data += struct.pack('<q', int(value))  # 8字节有符号长整型
                elif col_type == 'FLOAT':
                    data += struct.pack('<d', float(value))  # 8字节双精度
                elif col_type == 'TEXT':
                    # 字符串：先长度再数据
                    text = str(value).encode('utf-8')
                    data += struct.pack('<I', len(text))  # 4字节长度
                    data += text
                else:
                    # 未知类型，按TEXT处理
                    text = str(value).encode('utf-8')
                    data += struct.pack('<I', len(text))
                    data += text
        
        return data
    
    @classmethod
    def from_bytes(cls, table_meta: TableMetadata, data: bytes) -> 'Record':
        """
        从字节数据反序列化记录
        
        Args:
            table_meta: 表元数据
            data: 序列化的记录数据
            
        Returns:
            Record对象
        """
        import struct
        offset = 0
        
        # 读取记录ID
        record_id = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        
        values = {}
        
        for col in table_meta.columns:
            col_name = col['name']
            col_type = col['type']
            
            # 读取NULL标记
            null_flag = struct.unpack_from('B', data, offset)[0]
            offset += 1
            
            if null_flag == 1:
                values[col_name] = None
            else:
                # 读取数据
                if col_type == 'INTEGER':
                    val = struct.unpack_from('<q', data, offset)[0]
                    offset += 8
                elif col_type == 'FLOAT':
                    val = struct.unpack_from('<d', data, offset)[0]
                    offset += 8
                elif col_type == 'TEXT':
                    text_len = struct.unpack_from('<I', data, offset)[0]
                    offset += 4
                    val = data[offset:offset+text_len].decode('utf-8')
                    offset += text_len
                else:
                    # 未知类型，尝试按TEXT读取
                    text_len = struct.unpack_from('<I', data, offset)[0]
                    offset += 4
                    val = data[offset:offset+text_len].decode('utf-8')
                    offset += text_len
                
                values[col_name] = val
        
        return cls(table_meta, record_id, values)


class PageSlot:
    """页槽：记录在页面中的位置信息"""
    
    def __init__(self, page_id: int, offset: int, length: int):
        self.page_id = page_id
        self.offset = offset
        self.length = length


class TableRecordManager:
    """表记录管理器（基于页面存储）"""
    
    def __init__(self, storage: StorageEngine, table_meta: TableMetadata, 
                 initial_page: Optional[int] = None):
        """
        初始化表记录管理器
        
        Args:
            storage: 存储引擎
            table_meta: 表元数据
            initial_page: 初始数据页面ID（如果已有）
        """
        self.storage = storage
        self.table_meta = table_meta
        self.page_size = storage.get_page_size()
        
        # 记录ID计数器（每个表独立）
        self.next_record_id = 1
        
        # 表数据页面（包含记录的页面）
        self.data_pages: List[int] = []
        
        # 如果提供了初始页面，加载它
        if initial_page is not None:
            self.data_pages.append(initial_page)
        
        # 页面格式：
        # - 页面头部 (64字节)：记录偏移表 + 元数据
        # - 记录数据区：存放序列化的记录
        self.page_header_size = 64
        
        # 每个槽位大小（记录在页面中的位置信息）：4字节page_rel_offset + 2字节length + 1字节状态 = 11字节
        self.slot_size = 11
        self.max_slots_per_page = (self.page_header_size * 8) // self.slot_size
        
        # 记录ID到槽位的映射（缓存）
        self.record_slots: Dict[int, PageSlot] = {}
        
        # 如果已有页面，加载记录信息
        if self.data_pages:
            self._load_slots()
    
    def _load_slots(self):
        """从数据页面加载槽位信息"""
        self.record_slots.clear()
        self.next_record_id = 1
        
        for page_id in self.data_pages:
            page_data = self.storage.page_read(page_id)
            if page_data is None:
                continue
            
            # 读取记录ID映射
            # 页面头部包含记录ID到槽位偏移的映射
            # 简化：假设页面开头的连续slot_size*N字节存储槽位信息
            for slot_idx in range(self.max_slots_per_page):
                offset = slot_idx * self.slot_size
                if offset + self.slot_size > self.page_header_size:
                    break
                
                # 解析槽位: 记录ID (4字节), 偏移(2字节), 长度(2字节), 状态(1字节)
                record_id = int.from_bytes(page_data[offset:offset+4], 'little')
                slot_offset = int.from_bytes(page_data[offset+4:offset+6], 'little')
                slot_length = int.from_bytes(page_data[offset+6:offset+8], 'little')
                status = page_data[offset+8]
                
                if status == 1:  # 已使用
                    self.record_slots[record_id] = PageSlot(page_id, slot_offset, slot_length)
                    if record_id >= self.next_record_id:
                        self.next_record_id = record_id + 1
        
        self.next_record_id = max(self.next_record_id, 1)
    
    def scan_all(self) -> Iterator[Record]:
        """扫描表中的所有记录"""
        # 重新加载槽位确保最新
        self._load_slots()
        
        # 按记录ID排序返回
        for record_id in sorted(self.record_slots.keys()):
            slot = self.record_slots[record_id]
            page_data = self.storage.page_read(slot.page_id)
            if page_data is None:
                continue
            
            record_data = page_data[slot.offset:slot.offset+slot.length]
            record = Record.from_bytes(self.table_meta, record_data)
            yield record
    
    def get_record(self, record_id: int) -> Optional[Record]:
        """根据记录ID获取记录"""
        if record_id not in self.record_slots:
            return None
        
        slot = self.record_slots[record_id]
        page_data = self.storage.page_read(slot.page_id)
        if page_data is None:
            return None
        
        record_data = page_data[slot.offset:slot.offset+slot.length]
        return Record.from_bytes(self.table_meta, record_data)
    
    def insert_record(self, values: Dict[str, Any]) -> int:
        """
        插入新记录
        
        Returns:
            新记录的ID
        """
        # 检查值是否与表结构匹配
        self._validate_values(values)
        
        # 分配记录ID
        record_id = self.next_record_id
        self.next_record_id += 1
        
        # 序列化记录
        record = Record(self.table_meta, record_id, values)
        record_bytes = record.to_bytes()
        
        # 尝试在现有页面插入
        inserted = False
        for page_id in self.data_pages:
            if self._insert_into_page(page_id, record_bytes, record_id):
                inserted = True
                break
        
        # 如果现有页面都满了或不存在，分配新页面
        if not inserted:
            new_page_id = self.storage.allocate_page()
            self._init_data_page(new_page_id)
            self.data_pages.append(new_page_id)
            self._insert_into_page(new_page_id, record_bytes, record_id)
        
        # 更新槽位缓存
        self._load_slots()
        
        return record_id
    
    def _validate_values(self, values: Dict[str, Any]):
        """验证插入的值"""
        for col in self.table_meta.columns:
            col_name = col['name']
            col_type = col['type']
            nullable = col.get('nullable', True)
            
            if col_name not in values:
                if not nullable:
                    raise ValueError(f"列 '{col_name}' 不能为NULL")
                continue
            
            value = values[col_name]
            if value is not None:
                # 简单类型检查
                if col_type == 'INTEGER':
                    if not isinstance(value, int):
                        raise TypeError(f"列 '{col_name}' 类型应为INTEGER")
                elif col_type == 'FLOAT':
                    if not isinstance(value, (int, float)):
                        raise TypeError(f"列 '{col_name}' 类型应为FLOAT")
                elif col_type == 'TEXT':
                    if not isinstance(value, str):
                        raise TypeError(f"列 '{col_name}' 类型应为TEXT")
    
    def _init_data_page(self, page_id: int):
        """初始化数据页面"""
        page_data = bytearray(self.page_size)
        
        # 页面头：记录槽位表
        # 每个槽位11字节，用作记录ID到位置的映射
        # 格式：4字节记录ID | 2字节偏移 | 2字节长度 | 1字节状态
        # 初始化为0
        for i in range(self.max_slots_per_page):
            offset = i * self.slot_size
            if offset + self.slot_size > self.page_header_size:
                break
            # 全部清零即可
        
        # 写入页面
        self.storage.page_write(page_id, bytes(page_data))
    
    def _insert_into_page(self, page_id: int, record_bytes: bytes, record_id: int) -> bool:
        """
        尝试将记录插入指定页面
        
        Returns:
            成功返回True，失败返回False
        """
        page_data = self.storage.page_read(page_id)
        if page_data is None:
            return False
        
        page_bytes = bytearray(page_data)
        
        # 寻找空闲槽位（状态为0的槽位）
        for slot_idx in range(self.max_slots_per_page):
            offset = slot_idx * self.slot_size
            if offset + self.slot_size > self.page_header_size:
                break
            
            status = page_bytes[offset + 8]
            if status == 0:  # 空闲
                # 检查是否有足够空间存放记录（简化：假设数据区足够大）
                # 实际需要管理数据区的分配
                record_offset = self.page_header_size + slot_idx * 64  # 简单分配，每槽固定区域
                if record_offset + len(record_bytes) > self.page_size:
                    continue  # 空间不足，尝试下一个槽位
                
                # 写入记录数据
                page_bytes[record_offset:record_offset+len(record_bytes)] = record_bytes
                
                # 写入槽位信息
                page_bytes[offset:offset+4] = record_id.to_bytes(4, 'little')
                page_bytes[offset+4:offset+6] = record_offset.to_bytes(2, 'little')
                page_bytes[offset+6:offset+8] = len(record_bytes).to_bytes(2, 'little')
                page_bytes[offset+8] = 1  # 状态：已使用
                
                # 写回页面
                self.storage.page_write(page_id, bytes(page_bytes))
                return True
        
        return False
    
    def update_record(self, record_id: int, values: Dict[str, Any]) -> bool:
        """更新记录（简化：删除后插入）"""
        # 先检查记录是否存在
        if record_id not in self.record_slots:
            return False
        
        # 获取原记录
        record = self.get_record(record_id)
        if record is None:
            return False
        
        # 合并新值
        new_values = record.values.copy()
        new_values.update(values)
        
        # 简单实现：标记旧记录为删除，插入新记录
        # 注意：新记录会获得新的record_id，但这对于简化实现是可以接受的
        if not self.delete_record(record_id):
            return False
        
        new_record_id = self.insert_record(new_values)
        # 返回True表示更新成功（不要求ID相同）
        return new_record_id is not None
    
    def delete_record(self, record_id: int) -> bool:
        """删除记录（标记为删除）"""
        if record_id not in self.record_slots:
            return False
        
        slot = self.record_slots[record_id]
        page_data = self.storage.page_read(slot.page_id)
        if page_data is None:
            return False
        
        page_bytes = bytearray(page_data)
        
        # 找到对应的槽位并标记为删除
        for slot_idx in range(self.max_slots_per_page):
            offset = slot_idx * self.slot_size
            if offset + self.slot_size > self.page_header_size:
                break
            
            stored_id = int.from_bytes(page_bytes[offset:offset+4], 'little')
            if stored_id == record_id:
                # 标记状态为2（已删除）
                page_bytes[offset+8] = 2
                self.storage.page_write(slot.page_id, bytes(page_bytes))
                del self.record_slots[record_id]
                return True
        
        return False
    
    def close(self):
        """关闭管理器"""
        self.record_slots.clear()
