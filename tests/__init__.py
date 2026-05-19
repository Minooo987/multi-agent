"""
Agent Teams 测试套件
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock

# 标记需要异步测试
pytest_plugins = ('pytest_asyncio',)


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_oracle_response():
    """模拟 Oracle 查询响应"""
    return {
        "success": True,
        "rows": [
            {"LINENO": "101", "TXN_COUNT": 1000},
            {"LINENO": "102", "TXN_COUNT": 800}
        ],
        "columns": ["LINENO", "TXN_COUNT"],
        "row_count": 2,
        "execution_time": 0.5
    }


@pytest.fixture
def mock_settings():
    """模拟设置"""
    with patch('config.settings.settings') as mock:
        mock.oracle_host = "192.101.0.124"
        mock.oracle_port = 1521
        mock.oracle_service_name = "szbus"
        mock.oracle_user = "test_user"
        mock.oracle_password = "test_pass"
        mock.model_name = "qwen-coder-plus"
        mock.model_base_url = "https://test.example.com"
        mock.model_api_key = "test_key"
        yield mock
