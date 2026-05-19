"""
测试 API 端点
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

from api.server import app


@pytest.fixture
def client():
    """创建测试客户端"""
    return TestClient(app)


@pytest.fixture
def mock_team_graph():
    """模拟 Team Graph"""
    with patch('api.server.team_graph') as mock:
        mock.run = AsyncMock(return_value={
            "status": "completed",
            "final_report": "测试报告",
            "results": {"test": "data"},
            "tasks": []
        })
        mock.get_state = AsyncMock(return_value={
            "status": "completed",
            "current_step": "finalize"
        })
        mock.resume_after_interrupt = AsyncMock(return_value={
            "status": "completed",
            "final_report": "更新后的报告"
        })
        yield mock


def test_health_check(client):
    """测试健康检查"""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_root(client):
    """测试根路径"""
    response = client.get("/")

    assert response.status_code == 200
    assert "Agent Teams API" in response.json()["message"]


@pytest.mark.asyncio
async def test_create_analysis(client, mock_team_graph):
    """测试创建分析"""
    response = client.post(
        "/api/v1/analyze",
        json={"query": "测试查询", "require_human_review": False}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert "thread_id" in response.json()


def test_get_status(client, mock_team_graph):
    """测试获取状态"""
    response = client.get("/api/v1/status/test-thread-id")

    assert response.status_code == 200


def test_db_status(client):
    """测试数据库状态"""
    with patch('api.server.oracle_mcp') as mock_oracle:
        mock_oracle.test_connection = AsyncMock(return_value={
            "success": True,
            "connected": True
        })

        response = client.get("/api/v1/db/status")

        assert response.status_code == 200


def test_get_tables(client):
    """测试获取表列表"""
    with patch('api.server.oracle_mcp') as mock_oracle:
        mock_oracle.get_tables = AsyncMock(return_value={
            "success": True,
            "rows": [{"TABLE_NAME": "TEST_TABLE"}]
        })

        response = client.get("/api/v1/db/tables")

        assert response.status_code == 200


def test_describe_table(client):
    """测试表结构查询"""
    with patch('api.server.oracle_mcp') as mock_oracle:
        mock_oracle.describe_table = AsyncMock(return_value={
            "success": True,
            "table_name": "TEST",
            "columns": []
        })

        response = client.get("/api/v1/db/tables/TEST_TABLE")

        assert response.status_code == 200
