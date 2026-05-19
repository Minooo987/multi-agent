"""
MCP Oracle 工具
等效 ~/.claude/mcp-skills/oracle-db/oracle-mcp-server.js
"""

# ============================================================
# Oracle 字符集环境变量设置（必须在 import oracledb 之前）
# ============================================================
# oracledb Thin 模式在导入时会读取 NLS_LANG 来决定客户端字符集。
# 如果设置太晚，中文字符会在驱动层面就解码错误，后续无法修复。
import os
import sys

os.environ.setdefault("NLS_LANG", "SIMPLIFIED CHINESE_CHINA.AL32UTF8")

# Windows 控制台默认编码为 GBK，若输出 UTF-8 中文会显示为乱码。
# 尝试将 stdout/stderr 重配置为 utf-8（Python 3.7+ 兼容）
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

import oracledb
import json
import asyncio
from typing import List, Any, Dict, Optional
from functools import wraps

from config.settings import settings


def _decode_oracle_string(value):
    """
    尝试修复 Oracle 查询结果中的中文乱码。
    oracledb Thin 模式在某些字符集配置下可能返回编码错误的字符串，
    本函数通过多种策略尝试恢复正确的中文字符。
    """
    # 非字符串/字节类型直接返回
    if not isinstance(value, (str, bytes)):
        return value

    # 处理 bytes 类型（某些配置下可能直接返回 bytes）
    if isinstance(value, bytes):
        for enc in ('utf-8', 'gbk', 'gb2312'):
            try:
                decoded = value.decode(enc)
                if any('一' <= c <= '鿿' for c in decoded):
                    return decoded
            except (UnicodeDecodeError, LookupError):
                continue
        return value.decode('utf-8', errors='replace')

    # 空字符串直接返回
    if not value:
        return value

    # 如果已经包含正常中文汉字（CJK 统一表意文字），认为编码正确
    if any('一' <= c <= '鿿' for c in value):
        return value

    # 如果包含 Unicode 替换字符（U+FFFD），说明原始字节已丢失，无法修复
    if '�' in value:
        return value

    # 处理 surrogateescape 序列 (\udc80-\udcff)
    # 某些驱动将无法解码的字节转为 surrogate 字符
    if any('\udc80' <= c <= '\udcff' for c in value):
        try:
            raw_bytes = value.encode('utf-8', 'surrogatepass')
            for enc in ('utf-8', 'gbk', 'gb2312'):
                try:
                    decoded = raw_bytes.decode(enc)
                    if any('一' <= c <= '鿿' for c in decoded):
                        return decoded
                except UnicodeDecodeError:
                    continue
        except UnicodeEncodeError:
            pass

    # 处理 latin1 透传的乱码字符
    # 将 str 按 latin1 编码回字节（保留 0x00-0xFF 的字节值），再用正确编码解码
    try:
        raw_bytes = value.encode('latin1')
    except UnicodeEncodeError:
        # 包含超出 latin1 范围的字符，无法使用此方法
        return value

    for enc in ('utf-8', 'gbk', 'gb2312'):
        try:
            decoded = raw_bytes.decode(enc)
            if decoded != value and any('一' <= c <= '鿿' for c in decoded):
                return decoded
        except (UnicodeDecodeError, LookupError):
            continue

    # 无需修复或无法修复，返回原值
    return value


class OracleMCPTool:
    """
    Oracle MCP 工具实现
    等效 Claude Code 的 MCP 服务器
    """

    def __init__(self):
        self.connection_pool = None
        self._initialized = False

    async def initialize(self):
        """初始化连接池"""
        if self._initialized:
            return

        try:
            # 优先尝试 Thick 模式（对中文编码支持更完整）
            try:
                oracledb.init_oracle_client()
                print("[OracleMCP] 使用 Thick 模式连接数据库")
                thick_mode = True
            except Exception as thick_err:
                print(f"[OracleMCP] Thick 模式不可用 ({thick_err})，回退到 Thin 模式")
                thick_mode = False

            self.connection_pool = oracledb.create_pool(
                user=settings.oracle_user,
                password=settings.oracle_password,
                dsn=f"{settings.oracle_host}:{settings.oracle_port}/{settings.oracle_service_name}",
                min=settings.oracle_pool_min,
                max=settings.oracle_pool_max,
            )

            self._initialized = True
            mode_str = "Thick" if thick_mode else "Thin"
            print(f"[OracleMCP] 连接池已创建 ({mode_str} 模式, min={settings.oracle_pool_min}, max={settings.oracle_pool_max})")

        except Exception as e:
            print(f"[OracleMCP] 初始化失败: {e}")
            raise

    async def _get_connection(self):
        """获取数据库连接"""
        if not self._initialized:
            await self.initialize()
        conn = self.connection_pool.acquire()

        # 设置会话级 NLS 参数，帮助 Thin 模式正确处理中文
        # 仅在连接首次从池中获取时设置（通过 _nls_set 标记避免重复执行）
        if not getattr(conn, '_nls_set', False):
            try:
                cursor = conn.cursor()
                cursor.execute("ALTER SESSION SET NLS_LANGUAGE='SIMPLIFIED CHINESE'")
                cursor.execute("ALTER SESSION SET NLS_TERRITORY='CHINA'")
                cursor.close()
                conn._nls_set = True
            except Exception:
                pass

        return conn

    async def query(
        self,
        sql: str,
        params: List[Any] = None,
        max_rows: int = 1000
    ) -> Dict[str, Any]:
        """
        执行 SQL 查询（异步包装）
        """
        conn = None
        cursor = None
        start_time = asyncio.get_event_loop().time()

        try:
            conn = await self._get_connection()
            cursor = conn.cursor()

            # 使用线程池执行同步数据库操作
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: cursor.execute(sql, params or []))

            # 获取列名
            columns = []
            if cursor.description:
                columns = [col[0] for col in cursor.description]

            # 获取结果行（异步包装）
            if max_rows > 0:
                rows_raw = await loop.run_in_executor(None, lambda: cursor.fetchmany(max_rows))
            else:
                rows_raw = await loop.run_in_executor(None, cursor.fetchall)

            # 转换结果为字典列表
            rows = []
            for row in rows_raw:
                row_dict = {}
                for i, col_name in enumerate(columns):
                    value = row[i]
                    # 处理日期类型
                    if hasattr(value, 'isoformat'):
                        value = value.isoformat()
                    # 处理中文乱码：尝试将 latin1 透传字节还原为正确编码
                    value = _decode_oracle_string(value)
                    row_dict[col_name] = value
                rows.append(row_dict)

            execution_time = asyncio.get_event_loop().time() - start_time

            return {
                "success": True,
                "rows": rows,
                "columns": columns,
                "row_count": len(rows),
                "rows_affected": cursor.rowcount or 0,
                "execution_time": round(execution_time, 3)
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "error_code": getattr(e, 'errorNum', None)
            }
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    async def get_tables(self, schema: str = None) -> Dict[str, Any]:
        """
        获取表列表
        等效 MCP oracle_get_tables 工具
        """
        schema = schema or settings.oracle_user.upper()

        sql = """
            SELECT table_name, comments
            FROM all_tab_comments
            WHERE owner = :owner
              AND table_name NOT LIKE 'BIN$%'
            ORDER BY table_name
        """

        return await self.query(sql, [schema])

    async def describe_table(
        self,
        table_name: str,
        schema: str = None
    ) -> Dict[str, Any]:
        """
        查看表结构
        等效 MCP oracle_describe_table 工具
        """
        schema = schema or settings.oracle_user.upper()

        # 首先获取表的实际 owner
        owner_sql = """
            SELECT DISTINCT owner
            FROM all_tab_columns
            WHERE table_name = :table_name
        """
        owner_result = await self.query(owner_sql, [table_name.upper()])
        actual_owner = owner_result.get('rows', [{}])[0].get('OWNER') if owner_result.get('success') and owner_result.get('rows') else schema

        # 获取列信息
        columns_sql = """
            SELECT c.column_name, c.data_type, c.data_length, c.nullable, c.data_default, cc.comments
            FROM all_tab_columns c
            LEFT JOIN all_col_comments cc ON c.owner = cc.owner
                AND c.table_name = cc.table_name
                AND c.column_name = cc.column_name
            WHERE c.owner = :owner AND c.table_name = :table_name
            ORDER BY c.column_id
        """

        columns_result = await self.query(
            columns_sql,
            [actual_owner, table_name.upper()]
        )

        # 获取主键信息
        pk_sql = """
            SELECT cols.column_name
            FROM all_constraints cons
            JOIN all_cons_columns cols ON cons.constraint_name = cols.constraint_name
            WHERE cons.constraint_type = 'P'
              AND cons.owner = :owner
              AND cons.table_name = :table_name
        """

        pk_result = await self.query(pk_sql, [schema, table_name.upper()])

        return {
            "success": columns_result.get("success", False),
            "table_name": table_name.upper(),
            "schema": schema,
            "columns": columns_result.get("rows", []),
            "primary_keys": [row.get("COLUMN_NAME") for row in pk_result.get("rows", [])],
            "error": columns_result.get("error")
        }

    async def get_indexes(
        self,
        table_name: str,
        schema: str = None
    ) -> Dict[str, Any]:
        """
        获取索引信息
        等效 MCP oracle_get_indexes 工具
        """
        schema = schema or settings.oracle_user.upper()

        sql = """
            SELECT index_name, index_type, uniqueness, column_name
            FROM all_ind_columns ic
            JOIN all_indexes i ON ic.index_name = i.index_name AND ic.index_owner = i.owner
            WHERE i.table_owner = :owner AND i.table_name = :table_name
            ORDER BY index_name, column_position
        """

        return await self.query(sql, [schema, table_name.upper()])

    async def execute(
        self,
        sql: str,
        params: List[Any] = None
    ) -> Dict[str, Any]:
        """
        执行 DML/DDL 语句（异步包装）
        """
        conn = None
        cursor = None
        try:
            conn = await self._get_connection()
            cursor = conn.cursor()

            # 使用线程池执行同步操作
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: cursor.execute(sql, params or []))
            await loop.run_in_executor(None, conn.commit)

            return {
                "success": True,
                "rows_affected": cursor.rowcount or 0,
                "last_rowid": cursor.lastrowid
            }

        except Exception as e:
            if conn:
                await asyncio.get_event_loop().run_in_executor(None, conn.rollback)
            return {
                "success": False,
                "error": str(e)
            }
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    async def get_nls_parameters(self) -> Dict[str, Any]:
        """
        获取数据库 NLS 字符集参数，用于诊断中文乱码问题。
        关键字段：NLS_CHARACTERSET（数据库字符集）、NLS_NCHAR_CHARACTERSET（国家字符集）。
        """
        sql = """
            SELECT parameter, value
            FROM nls_database_parameters
            WHERE parameter LIKE '%CHARACTERSET%'
               OR parameter IN ('NLS_LANGUAGE', 'NLS_TERRITORY', 'NLS_CALENDAR')
            ORDER BY parameter
        """
        return await self.query(sql)

    async def test_connection(self) -> Dict[str, Any]:
        """测试数据库连接并返回字符集信息"""
        try:
            result = await self.query("SELECT SYSDATE as current_date FROM dual")

            if result.get("success"):
                version_result = await self.query("SELECT * FROM v$version")
                version = version_result.get("rows", [{}])[0].get("BANNER", "Unknown")

                # 获取字符集信息（用于诊断乱码）
                nls_result = await self.get_nls_parameters()
                nls_params = {
                    row["PARAMETER"]: row["VALUE"]
                    for row in nls_result.get("rows", [])
                } if nls_result.get("success") else {}

                return {
                    "success": True,
                    "connected": True,
                    "database_version": version,
                    "current_time": result.get("rows", [{}])[0].get("CURRENT_DATE"),
                    "user": settings.oracle_user,
                    "host": settings.oracle_host,
                    "nls_parameters": nls_params,
                    "client_nls_lang": os.environ.get("NLS_LANG", "Not Set"),
                    "python_stdout_encoding": sys.stdout.encoding if hasattr(sys.stdout, "encoding") else "Unknown",
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error")
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def close(self):
        """关闭连接池"""
        if self.connection_pool:
            self.connection_pool.close()
            self._initialized = False
            print("[OracleMCP] 连接池已关闭")


# 全局 MCP 工具实例
oracle_mcp = OracleMCPTool()
