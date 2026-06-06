# Design Document for Educational RDBMS

## 1. System Overview

This design outlines a simplified relational database management system (RDBMS) for educational purposes. The system uses a layered architecture covering core functionalities: SQL parsing, query execution, transaction management, and storage management. It helps students understand database internals.

### 1.1 Design Principles
- **Simplicity**: Each module has a clear, focused responsibility (2000-5000 LOC)
- **Educational**: Clear architecture, visual data structures, easy to understand
- **Functional**: Supports complete CRUD operations and transaction processing
- **Extensible**: Modular design for future feature additions

### 1.2 Technology Recommendations
- **Language**: Python 3.8+ (easier for teaching) or Rust 1.60+ (performance/safety)
- **Storage**: File system (simulating disk persistence)
- **Memory**: OS memory + custom buffer pool

---

## 2. System Architecture

### 2.1 Layered Architecture

```
┌───────────────────────── Interface Layer ─────────────────────────┐
│  SQL CLI │ JDBC Driver │ Programmatic API                         │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌───────────────────────── SQL Layer ──────────────────────────────┐
│  Parser (Lexer → AST) │ Optimizer (Plan Generation)              │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌───────────────────────── Execution Layer ────────────────────────┐
│              Executor (Operator Execution)                        │
│   SeqScan │ IndexScan │ Filter │ Project │ Join                  │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌───────────────────────── Transaction Layer ──────────────────────┐
│ Transaction Manager (ACID, Locking, 2PL) │ WAL Manager (Recovery)│
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌───────────────────────── Storage Layer ──────────────────────────┐
│ Storage Manager (Files, Pages) │ Buffer Manager (LRU)           │
│ Index Manager (B+ Trees)                                            │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌───────────────────────── Physical Layer ─────────────────────────┐
│               Disk Files (.data, .index, .wal)                   │
└────────────────────────────────────────────────────────────────────┘
```

### 2.2 Module Dependency Graph

```
    Parser → Optimizer → Executor
                           │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   Transaction   Storage/Index   Buffer Manager
        │              │              │
        └──────────────┴──────────────┘
                      │
                 Physical Files
```

---

## 3. Detailed Module Design

### 3.1 SQL Parser

**Responsibilities**:
- Lexical analysis: Tokenize SQL string
- Syntax analysis: Build AST from grammar
- Semantic checks: Validate table/column names, types

**Core Classes** (Python-like):

```python
class Token:
    type: TokenType
    value: str

class ASTNode: pass

class SelectStmt(ASTNode):
    tables: List[str]
    columns: List[str]
    where: Optional[Expression]

class InsertStmt(ASTNode):
    table: str
    values: List[Expression]

class CreateTableStmt(ASTNode):
    table: str
    columns: List[ColumnDef]

class Parser:
    def parse(sql: str) -> ASTNode: ...
```

**Supported Syntax**: 
- DDL: CREATE TABLE, DROP TABLE
- DML: SELECT (single table + WHERE), INSERT, UPDATE, DELETE
- Transactions: BEGIN, COMMIT, ROLLBACK

### 3.2 Optimizer (Simplified)

**Responsibilities**:
- Logical optimization: Predicate pushdown, column pruning
- Physical planning: Choose scan strategy (index vs sequential)

**Core Classes**:

```python
class PlanNode: pass

class SeqScanNode(PlanNode):
    table: str
    filter: Optional[Expression]

class IndexScanNode(PlanNode):
    table: str
    index_name: str
    key: Expression

class Optimizer:
    def optimize(ast: ASTNode) -> PlanNode: ...
```

### 3.3 Executor

**Responsibilities**:
- Execute physical plan operator by operator
- Pass tuples (rows) between operators
- Interface with storage and transaction layers

**Core Classes**:

```python
class ExecutionContext:
    txn_id: int
    buffer_manager: BufferManager
    storage_manager: StorageManager

class Executor:
    def execute(plan: PlanNode, ctx: ExecutionContext) -> Iterator[Tuple]:
        ...
```

**Operators**:
- `SeqScanOperator`: Full table scan
- `IndexScanOperator`: Index-based lookup
- `FilterOperator`: Apply WHERE conditions
- `ProjectOperator`: Column selection

### 3.4 Transaction Manager

**Responsibilities**:
- Transaction lifecycle: BEGIN, COMMIT, ROLLBACK
- Concurrency control: 2-phase locking (2PL)
- Lock types: Shared (S) and Exclusive (X)
- Isolation level: Repeatable Read (RR) or Read Committed (RC)

**Core Classes**:

```python
class Transaction:
    txn_id: int
    state: TransactionState  # ACTIVE, COMMITTED, ABORTED
    locks: Dict[str, Lock]   # table → Lock

class TransactionManager:
    def begin() -> int: ...
    def commit(txn_id: int): ...
    def rollback(txn_id: int): ...
    def acquire_lock(txn_id: int, table: str, lock_type: Lock) -> bool: ...
    def release_locks(txn_id: int): ...
```

**Locking Protocol**: Strict 2PL - all locks released at COMMIT

### 3.5 WAL (Write-Ahead Logging) Manager

**Responsibilities**:
- Log changes before modifying data (WAL)
- Support crash recovery (simplified ARIES)
- Optional checkpointing

**WAL Record Format**:

```python
class WALRecord:
    lsn: int          # Log Sequence Number
    txn_id: int
    type: WALType     # INSERT, UPDATE, DELETE, COMMIT, ABORT
    table: str
    before: Optional[Tuple]  # for UPDATE/DELETE
    after: Optional[Tuple]   # for INSERT/UPDATE

class WALManager:
    def log_insert(txn_id, table, record) -> int: ...
    def log_update(txn_id, table, before, after) -> int: ...
    def log_delete(txn_id, table, record) -> int: ...
    def log_commit(txn_id) -> int: ...
    def flush(lsn: int): ...
    def recover() -> List[Transaction]: ...
```

**Log File**:
- Fixed-size segments (e.g., 4MB)
- Sequential append writes
- Periodic archiving/truncation

### 3.6 Storage Manager

**Responsibilities**:
- Database file management: create, open, drop
- Page allocation and deallocation
- Record read/write

**File Organization**:
- **Heap File**: unordered collection of records
- Per table: `{table}.data` (data) and `{table}.index` (indexes)

**Page Structure** (typically 4KB or 8KB):

```
Page Header (fixed size)
├─ page_id: int64
├─ free_space: int16
├─ record_count: int16
└─ ...

Data Area (variable-length records)
[record1][record2][record3]...

Slot Directory (array of pointers)
[offset, length]
[offset, length]
...
```

**Core Classes**:

```python
PAGE_SIZE = 4096

class Page:
    header: PageHeader
    data: bytearray
    
    def get_record(slot_id: int) -> Tuple: ...
    def insert_record(record: Tuple) -> int: ...  # returns slot_id
    def delete_record(slot_id: int): ...
    def update_record(slot_id: int, new_record: Tuple): ...

class HeapFile:
    table_name: str
    file: BinaryIO
    free_pages: List[int]
    
    def get_page(page_id: int) -> Page: ...
    def allocate_page() -> int: ...
    def iterator() -> Iterator[Tuple]: ...

class StorageManager:
    def create_table(table: str, columns: List[ColumnDef]): ...
    def open_table(table: str) -> HeapFile: ...
    def drop_table(table: str): ...
```

### 3.7 Buffer Manager

**Responsibilities**:
- Cache frequently used pages in memory
- Replacement policy: LRU or Clock
- Pin/Unpin reference counting
- Write dirty pages back to disk

**Buffer Frame Structure**:

```python
class BufferFrame:
    page_id: int
    page: Page
    dirty: bool
    pin_count: int
    lsn: int  # last modified LSN (for recovery)

class BufferManager:
    def __init__(pool_size: int = 100): ...
    def get_page(page_id: int) -> BufferFrame: ...
    def release_page(page_id: int): ...
    def mark_dirty(page_id: int): ...
    def flush_all(): ...
```

**Replacement (LRU)**:
- Maintain doubly-linked list
- Move accessed page to head
- Replace tail page (if pin_count==0)

### 3.8 Index Manager (B+ Trees)

**Responsibilities**:
- Create, drop, and search B+ tree indexes
- Maintain indexes: handle splits/merges on insert/delete

**B+ Tree Design (Simplified)**:
- Order: typically 32-64 (page_size / key_size)
- All leaf nodes linked for range scans
- Non-leaf nodes store keys and child pointers

**File Organization**:
- Index file: `{table}.idx_{index_name}`
- Separate from heap file

**Node Page Layout**:

```
B+TreeNode Header
├─ node_type: INTERNAL or LEAF
├─ key_count: int16
├─ parent: int64 (optional)

Keys (ordered)
[ k1, k2, k3, ... ]

Child Pointers / Record Pointers
- Internal: [ptr1, ptr2, ...] → child pages
- Leaf: [slot_id1, slot_id2, ...] → record locations
```

**Core Classes**:

```python
class BPlusTree:
    root_id: int64
    order: int
    
    def find(key) -> List[int]: ...    # returns matching slot_ids
    def insert(key, slot_id: int): ...   # recursive with split handling
    def delete(key, slot_id: int): ...  # recursive with merge/redistribute

class IndexManager:
    def create_index(table: str, column: str) -> BPlusTree: ...
    def drop_index(table: str, column: str): ...
    def get_index(table: str, column: str) -> Optional[BPlusTree]: ...
```

---

## 4. Data Model Design

### 4.1 Logical Schema

```python
class ColumnDef:
    name: str
    data_type: DataType  # INT, VARCHAR(n), BOOLEAN, DATE
    nullable: bool
    default: Optional[Any]
    primary_key: bool

class TableSchema:
    table_name: str
    columns: List[ColumnDef]
    indexes: List[IndexDef]
```

### 4.2 Physical Record Format

Variable-length records using "length-prefixed" format:

```
┌────────────┬─────────────────────┬────────────┐
│ slot_len   │   null bitmap       │  column1   │
│ (2 bytes)  │  (1 bit per col)    │  value...  │
├────────────┼─────────────────────┼────────────┤
│            │        ...          │ column2    │
│            │                     │  value...  │
└────────────┴─────────────────────┴────────────┘
```

**Encoding**:
- `slot_len`: 16-bit total length (including itself)
- `null bitmap`: ceil(n/8) bytes, 1 bit per column (1 = NULL)
- `value`:
  - INT: 4-byte signed integer
  - VARCHAR(n): 1-byte length + UTF-8 bytes
  - BOOLEAN: 1 byte (0/1)
  - DATE: 8 bytes (days since 1970-01-01)

**Example** (columns: INT, VARCHAR(20), BOOLEAN):
Record: (42, "hello", true)
Length: 2 + 1 + 4 + 1 + 5 + 1 = 14
Bytes: 0x0E 0x00 0x00 0x00 0x32 0x00 0x05 'h' 'e' 'l' 'l' 'o' 0x01
        ^slot_len   ^int     ^len    ^varchar    ^bool

### 4.3 Index Key Encoding

```python
def encode_key(value) -> bytes:
    if isinstance(value, int):
        return value.to_bytes(4, 'little', signed=True)
    elif isinstance(value, str):
        return value.encode('utf-8')
    elif isinstance(value, bool):
        return b'\x01' if value else b'\x00'

def compare_key(a: bytes, b: bytes) -> int:
    return (a > b) - (a < b)
```

### 4.4 Page Layout Example (4KB)

```
Page 0x1234 (4096 bytes)
├─ Header (32 bytes)
├─ Record Area (~4000 bytes)
│   ├─ Slot 0: offset=32, len=24 → (1, "Alice", true)
│   ├─ Slot 1: offset=56, len=20 → (2, "Bob", false)
│   └─ ...
└─ Slot Directory (remaining space)
    ├─ [32, 24]  ← inserted in order for fast delete
    ├─ [56, 20]
    └─ [0, 0]    ← sentinel
```

---

## 5. SQL Subset Specification

### 5.1 Supported Statements

**DDL**:
- `CREATE TABLE table_name (col1 TYPE [PRIMARY KEY], col2 TYPE, ...)`
- `DROP TABLE table_name`

**DML**:
- `INSERT INTO table_name VALUES (val1, val2, ...)`
- `SELECT col1, col2 FROM table_name [WHERE condition]`
- `UPDATE table_name SET col=val [, col2=val2] [WHERE condition]`
- `DELETE FROM table_name [WHERE condition]`

**WHERE Conditions (supported)**:
- Comparison: `=, !=, <, <=, >, >=`
- Logical: `AND, OR, NOT`
- Constants and column names

**WHERE Conditions (NOT supported)**:
- Subqueries
- IN, LIKE, BETWEEN
- Aggregate functions (COUNT, SUM, etc.)

**Transaction Statements**:
- `BEGIN`, `COMMIT`, `ROLLBACK`

### 5.2 Examples (Supported)

```sql
SELECT id, name FROM users WHERE age > 20;
SELECT * FROM users, orders WHERE users.id = orders.user_id;  -- simple join
INSERT INTO users VALUES (1, 'Alice', 25);
UPDATE users SET age=26 WHERE id=1;
DELETE FROM users WHERE age < 18;
```

### 5.3 Examples (Not Supported - Advanced)

```sql
SELECT COUNT(*) FROM users;           -- aggregates
SELECT dept, AVG(salary) GROUP BY;   -- GROUP BY
SELECT * FROM users WHERE id IN (...); -- subqueries
```

### 5.4 Integrity Constraints (Simplified)

- `NOT NULL` column constraint
- `PRIMARY KEY` (single column, implies NOT NULL + unique index)

Other constraints (FOREIGN KEY, UNIQUE) can be added later.

---

## 6. Key Data Structures & Algorithms

### 6.1 Transaction State Machine

```
     ┌──────────┐
     │  ACTIVE  │───COMMIT──▶ COMMITTED
     └──────────┘            │
         │                  ▼
         │              (persist)
         │                  │
         │             ┌────┴───┐
         │             │ RECOVERY│
         │             └────┬───┘
         │                  │
         ▼                  │
     ABORTED ◀──ROLLBACK──┘
```

### 6.2 Two-Phase Locking (2PL)

```
Phase 1 (Growing): acquire locks, cannot release
  ┌→ acquire(S on A)
  │   acquire(X on B)
  │   ...
  └─── (start releasing) ────┐
                           │
Phase 2 (Shrinking): release locks, cannot acquire new
  release(S on A)
  release(X on B)
  ...
  COMMIT/ROLLBACK
```

### 6.3 Recovery Algorithm (Simplified ARIES)

**Three Phases**:
1. **Analysis**: Scan WAL to determine committed and active transactions
2. **Redo**: Replay all committed transactions' changes from earliest dirty LSN
3. **Undo**: Roll back all active transactions by applying compensation log records

**Simplification for Teaching**:
- No checkpoints; scan entire log
- Undo via manual rollback or automatic on startup

---

## 7. Development Standards

### 7.1 Project Structure

```
dbms/
├── Cargo.toml / setup.py
├── README.md
├── docs/
│   ├── DESIGN.md
│   ├── API.md
│   └── TUTORIAL.md
├── src/
│   ├── parser/
│   ├── optimizer/
│   ├── executor/
│   ├── storage/
│   ├── buffer/
│   ├── transaction/
│   ├── wal/
│   ├── index/
│   ├── types/
│   ├── common/
│   └── main.py / bin/
├── tests/
├── examples/
├── data/  # runtime data files
└── target/ / build/
```

### 7.2 Interface Specifications

Use abstract base classes (Python) or traits (Rust) to define interfaces.

**Example (Python)**:

```python
from abc import ABC, abstractmethod

class Storage(ABC):
    @abstractmethod
    def read_page(page_id: int) -> Page: ...
    @abstractmethod
    def write_page(page_id: int, page: Page): ...
```

### 7.3 Error Handling

Define a hierarchy of exceptions:

```python
class DBError(Exception): pass
class SyntaxError(DBError): pass
class TransactionError(DBError): pass
class StorageError(DBError): pass
```

Functions should raise exceptions or return Result types (Rust).

### 7.4 Logging

- Use standard logging module
- Log levels: DEBUG, INFO, WARN, ERROR
- Key events: transaction begin/commit/rollback, lock acquire/release, page I/O

### 7.5 Testing

- Target: High coverage for core modules
- Frameworks: pytest (Python), built-in test (Rust)
- Include ACID compliance tests
- Include recovery tests

### 7.6 Code Comments

- File header: module purpose, author, date
- Docstrings for all public classes and functions
- Inline comments for complex algorithms

---

## 8. Data Flow Example: INSERT

```
User: INSERT INTO users VALUES (1, 'Alice', 25)
  ↓
Parser → AST(InsertStmt)
  ↓
Optimizer → Physical plan (no real optimization needed)
  ↓
Executor (auto-starts transaction)
  ↓
1. Acquire exclusive lock on 'users'
2. Open heap file, get buffer frame for a page
3. Encode record, find free space on page
4. Write record to page, mark dirty
5. Log to WAL (before flushing)
6. Release lock on commit
```

---

## 9. Summary

This design provides a complete blueprint for building an educational RDBMS. The modular architecture separates concerns, making it easier to implement and understand each component. The simplified SQL subset covers fundamental operations while keeping complexity manageable. The physical storage design (pages, slots, B+ trees) demonstrates real database internals. With these specifications, students can implement a working database system in about 2000-5000 lines of code per module, gaining hands-on experience with core database concepts.

**End of Document**