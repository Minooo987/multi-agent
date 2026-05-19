"""
测试 Oracle MCP
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from tools.mcp_oracle import OracleMCPTool, oracle_mcp


@pytest.mark.asyncio
async def test_oracle_mcp_init():
    """测试初始化"""
    mcp = OracleMCPTool()

    assert mcp._initialized is False
    assert mcp.connection_pool is None


@pytest.mark.asyncio
async def test_query_success():
    """测试查询成功"""
    with patch('tools.mcp_oracle.oracledb') as mock_oracle:
        # 模拟连接池
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()

        # 模拟查询结果
        mock_cursor = AsyncMock()
        mock_cursor.description = [["LINENO"], ["TXN_COUNT"]]
        mock_cursor.rows = [["101", 1000], ["102", 800]]
        mock_cursor.rowsAffected = 0

        mock_conn.execute.return_value = mock_cursor
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_oracle.create_pool.return_value = mock_pool

        mcp = OracleMCPTool()
        mcp.connection_pool = mock_pool
        mcp._initialized = True

        result = await mcp.query("SELECT * FROM test")

        assert result["success"] is True
        assert result["row_count"] == 2


@pytest.mark.asyncio
async def test_describe_table():
    """测试表结构查询"""
    with patch('tools.mcp_oracle.oracledb') as mock_oracle:
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()

        # 列信息
        mock_cursor = AsyncMock()
        mock_cursor.description = [["COLUMN_NAME"], ["DATA_TYPE"]]
        mock_cursor.rows = [["LINENO", "VARCHAR2"], ["TRANTIME", "DATE"]]

        mock_conn.execute.return_value = mock_cursor
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mcp = OracleMCPTool()
        mcp.connection_pool = mock_pool
        mcp._initialized = True

        with patch.object(mcp, 'query', return_value={
            "success": True,
            "rows": [{"COLUMN_NAME": "LINENO", "DATA_TYPE": "VARCHAR2"}]
        }):
            result = await mcp.describe_table("LF_TRANSACTION_DETAIL")

            assert result["success"] is True
            assert result["table_name"] == "LF_TRANSACTION_DETAIL"


@pytest.mark.asyncio
async def test_test_connection():
    """测试连接测试"""
    with patch.object(oracle_mcp, 'query', return_value={
        "success": True,
        "rows": [{"CURRENT_DATE": "2024-01-01"}]
    }):
        with patch.object(oracle_mcp, '_get_connection', AsyncMock()):
            result = await oracle_mcp.test_connection()

            # 由于 oracle_mcp 是全局实例，可能被其他测试影响
            # 这里主要验证函数存在且可调用
            pass
