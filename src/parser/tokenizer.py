"""
SQL词法分析器（Tokenizer）
将SQL字符串分解成标记（tokens）
"""

class Token:
    """标记类"""
    def __init__(self, type, value, line=1, column=0):
        self.type = type    # 标记类型（关键词、标识符、运算符等）
        self.value = value  # 标记的值
        self.line = line
        self.column = column

    def __repr__(self):
        return f"Token({self.type}, '{self.value}')"


class TokenizerError(Exception):
    """词法分析错误"""
    pass


class Tokenizer:
    """SQL词法分析器"""

    # 关键词映射
    KEYWORDS = {
        'SELECT': 'SELECT',
        'FROM': 'FROM',
        'WHERE': 'WHERE',
        'INSERT': 'INSERT',
        'INTO': 'INTO',
        'VALUES': 'VALUES',
        'UPDATE': 'UPDATE',
        'SET': 'SET',
        'DELETE': 'DELETE',
        'CREATE': 'CREATE',
        'TABLE': 'TABLE',
        'DROP': 'DROP',
        'BEGIN': 'BEGIN',
        'COMMIT': 'COMMIT',
        'ROLLBACK': 'ROLLBACK',
        'AND': 'AND',
        'OR': 'OR',
        'NOT': 'NOT',
        'NULL': 'NULL',
        'IS': 'IS',
        'INT': 'INT',
        'FLOAT': 'FLOAT',
        'VARCHAR': 'VARCHAR',
        'BOOLEAN': 'BOOLEAN',
        'KEY': 'KEY',
        'PRIMARY': 'PRIMARY',
        'UNIQUE': 'UNIQUE',
        'TRUE': 'TRUE',
        'FALSE': 'FALSE',
    }

    # 单字符运算符
    SINGLE_CHAR_TOKENS = {
        '=': 'EQ',
        '>': 'GT',
        '<': 'LT',
        '+': 'PLUS',
        '-': 'MINUS',
        '*': 'STAR',
        '/': 'SLASH',
        ',': 'COMMA',
        '(': 'LPAREN',
        ')': 'RPAREN',
        ';': 'SEMICOLON',
    }

    # 双字符运算符
    DOUBLE_CHAR_TOKENS = {
        '>=': 'GE',
        '<=': 'LE',
        '!=': 'NE',
    }

    def __init__(self, sql):
        self.sql = sql
        self.pos = 0
        self.line = 1
        self.column = 0
        self.tokens = []

    def tokenize(self):
        """主词法分析函数"""
        while self.pos < len(self.sql):
            self.skip_whitespace()
            if self.pos >= len(self.sql):
                break

            char = self.sql[self.pos]

            # 注释（简化处理：跳过单行注释）- 必须放在运算符检查之前
            if char == '-' and self.peek() == '-':
                self.skip_comment()
                continue

            # 字符串字面量
            if char == "'" or char == '"':
                self.tokenize_string(char)

            # 数字字面量
            elif char.isdigit():
                self.tokenize_number()

            # 标识符或关键词
            elif char.isalpha() or char == '_':
                self.tokenize_identifier()

            # 运算符和标点（包括双字符检查）
            else:
                self.tokenize_operator()

        return self.tokens

    def skip_whitespace(self):
        """跳过空白字符"""
        while self.pos < len(self.sql) and self.sql[self.pos].isspace():
            if self.sql[self.pos] == '\n':
                self.line += 1
                self.column = 0
            self.pos += 1
            self.column += 1

    def peek(self, offset=1):
        """查看当前位置之后的字符"""
        pos = self.pos + offset
        if pos < len(self.sql):
            return self.sql[pos]
        return ''

    def tokenize_string(self, quote_char):
        """处理字符串字面量（支持SQL风格的''转义）"""
        start_col = self.column
        self.pos += 1  # 跳过起始引号
        self.column += 1

        # 收集字符串字符
        chars = []
        while self.pos < len(self.sql):
            # 检查是否遇到结束引号
            if self.sql[self.pos] == quote_char:
                # 检查是否为两个连续引号（SQL转义）
                if self.pos + 1 < len(self.sql) and self.sql[self.pos + 1] == quote_char:
                    chars.append(quote_char)
                    self.pos += 2
                    self.column += 2
                    continue
                else:
                    # 正常结束
                    self.pos += 1
                    self.column += 1
                    value = ''.join(chars)
                    self.tokens.append(Token('STRING', value, self.line, start_col))
                    return

            # 反斜杠转义（可选）
            elif self.sql[self.pos] == '\\' and self.peek() == quote_char:
                chars.append(quote_char)
                self.pos += 2
                self.column += 2
            else:
                chars.append(self.sql[self.pos])
                self.pos += 1
                self.column += 1

        raise TokenizerError(f"未闭合的字符串在第 {self.line} 行, 列 {start_col}")

    def tokenize_number(self):
        """处理数字字面量（整数和浮点数）"""
        start_pos = self.pos
        start_col = self.column
        has_dot = False

        while self.pos < len(self.sql):
            char = self.sql[self.pos]
            if char.isdigit():
                self.pos += 1
                self.column += 1
            elif char == '.' and not has_dot and self.peek().isdigit():
                has_dot = True
                self.pos += 1
                self.column += 1
            else:
                break

        value_str = self.sql[start_pos:self.pos]
        if has_dot:
            value = float(value_str)
            token_type = 'FLOAT'
        else:
            value = int(value_str)
            token_type = 'INTEGER'

        self.tokens.append(Token(token_type, value, self.line, start_col))

    def tokenize_identifier(self):
        """处理标识符或关键词"""
        start_pos = self.pos
        start_col = self.column

        while self.pos < len(self.sql):
            char = self.sql[self.pos]
            if char.isalnum() or char == '_':
                self.pos += 1
                self.column += 1
            else:
                break

        original_value = self.sql[start_pos:self.pos]
        upper_value = original_value.upper()
        # 检查是否为关键词（使用大写形式检查）
        token_type = self.KEYWORDS.get(upper_value, 'IDENTIFIER')
        # 关键词保持原大小写，标识符保持原样
        value = original_value if token_type == 'IDENTIFIER' else original_value

        self.tokens.append(Token(token_type, value, self.line, start_col))

    def tokenize_operator(self):
        """处理运算符和标点符号"""
        start_col = self.column
        char = self.sql[self.pos]

        # 特殊处理：'!' 后跟 '=' 组成 !=，单独的 '!' 无效
        if char == '!':
            if self.peek() == '=':
                two_char = '!='
                self.tokens.append(Token('NE', two_char, self.line, start_col))
                self.pos += 2
                self.column += 2
                return
            else:
                raise TokenizerError(f"未知运算符 '!' 在第 {self.line} 行, 列 {start_col}")

        # 尝试双字符运算符
        if self.pos + 1 < len(self.sql):
            two_char = char + self.sql[self.pos + 1]
            if two_char in self.DOUBLE_CHAR_TOKENS:
                token_type = self.DOUBLE_CHAR_TOKENS[two_char]
                self.tokens.append(Token(token_type, two_char, self.line, start_col))
                self.pos += 2
                self.column += 2
                return

        # 单字符运算符
        token_type = self.SINGLE_CHAR_TOKENS.get(char)
        if token_type:
            self.tokens.append(Token(token_type, char, self.line, start_col))
            self.pos += 1
            self.column += 1
        else:
            raise TokenizerError(f"意外字符 '{char}' 在第 {self.line} 行, 列 {start_col}")

    def skip_comment(self):
        """跳过单行注释（-- 开头）"""
        # 已经匹配了--，现在跳过直到行尾
        while self.pos < len(self.sql) and self.sql[self.pos] != '\n':
            self.pos += 1


def tokenize(sql):
    """便利函数：直接返回标记列表"""
    tokenizer = Tokenizer(sql)
    return tokenizer.tokenize()
