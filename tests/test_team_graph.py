"""
测试 LangGraph 工作流
"""

import pytest
from unittest.mock import patch, AsyncMock

from graph.team_graph import AgentTeamGraph
from graph.state import TeamState, Task, TaskStatus, Message


@pytest.fixture
def mock_agents():
    """模拟 Agents"""
    with patch('graph.team_graph.TaskManagerAgent') as mock_tm, \
         patch('graph.team_graph.PassengerProcessorAgent') as mock_pp, \
         patch('graph.team_graph.OperationSchedulerAgent') as mock_os:

        # 配置模拟
        mock_tm.return_value.invoke_llm = AsyncMock(return_value='{"needs_passenger": true}')
        mock_tm.return_value.aggregate_final_results = AsyncMock(return_value="测试报告")

        mock_pp.return_value.process_message = AsyncMock(return_value={"test": "passenger_result"})
        mock_os.return_value.process_message = AsyncMock(return_value={"test": "operation_result"})

        yield


@pytest.mark.asyncio
async def test_graph_init(mock_agents):
    """测试图初始化"""
    graph = AgentTeamGraph()

    assert graph.task_manager is not None
    assert graph.passenger_processor is not None
    assert graph.operation_scheduler is not None
    assert graph.workflow is not None


@pytest.mark.asyncio
async def test_analyze_request(mock_agents):
    """测试请求分析"""
    graph = AgentTeamGraph()

    state = {"request": "分析客流数据", "error": None}
    result = await graph._analyze_request(state)

    assert "analysis" in result
    assert result.get("status") == "analyzed"


@pytest.mark.asyncio
async def test_create_tasks(mock_agents):
    """测试任务创建"""
    graph = AgentTeamGraph()

    state = {
        "request": "测试请求",
        "analysis": {"needs_passenger": True, "needs_operation": True}
    }

    result = await graph._create_tasks(state)

    assert len(result["tasks"]) == 2
    assert result["status"] == "tasks_created"


@pytest.mark.asyncio
async def test_aggregate_results(mock_agents):
    """测试结果聚合"""
    graph = AgentTeamGraph()

    state = {
        "results": {
            "passenger": {"count": 100},
            "operation": {"buses": 10}
        }
    }

    result = await graph._aggregate_results(state)

    assert "final_report" in result
    assert result["status"] == "aggregated"


def test_generate_simple_report():
    """测试简单报告生成"""
    graph = AgentTeamGraph()

    passenger = {"analysis_type": "客流", "count": 100}
    operation = {"analysis_type": "营运", "buses": 10}

    report = graph._generate_simple_report(passenger, operation)

    assert "客流数据分析" in report
    assert "营运调度分析" in report
    assert "100" in report
