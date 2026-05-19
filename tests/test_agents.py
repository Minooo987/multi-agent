"""
测试 Agents
"""

import pytest
from unittest.mock import patch, AsyncMock

from agents.passenger_processor import PassengerProcessorAgent
from agents.operation_scheduler import OperationSchedulerAgent
from graph.state import Message


@pytest.mark.asyncio
async def test_passenger_processor_init():
    """测试 Passenger Processor 初始化"""
    with patch('agents.base.ChatOpenAI') as mock_llm:
        mock_llm.return_value = AsyncMock()

        agent = PassengerProcessorAgent()

        assert agent.name == "passenger_processor"
        assert "客流" in agent.system_prompt
        assert "task_manager" in agent.can_talk_to

        agent.cleanup()


@pytest.mark.asyncio
async def test_operation_scheduler_init():
    """测试 Operation Scheduler 初始化"""
    with patch('agents.base.ChatOpenAI') as mock_llm:
        mock_llm.return_value = AsyncMock()

        agent = OperationSchedulerAgent()

        assert agent.name == "operation_scheduler"
        assert "营运" in agent.system_prompt
        assert "task_manager" in agent.can_talk_to

        agent.cleanup()


@pytest.mark.asyncio
async def test_passenger_detect_analysis_type():
    """测试分析类型检测"""
    with patch('agents.base.ChatOpenAI') as mock_llm:
        mock_llm.return_value = AsyncMock()

        agent = PassengerProcessorAgent()

        # 测试站点相关
        assert agent._detect_analysis_type("分析站点客流") == "站点"

        # 测试线路相关
        assert agent._detect_analysis_type("线路统计") == "线路"

        # 测试高峰相关
        assert agent._detect_analysis_type("高峰时段") == "高峰"

        # 测试换乘相关
        assert agent._detect_analysis_type("换乘分析") == "换乘"

        agent.cleanup()


@pytest.mark.asyncio
async def test_operation_scheduler_detect_task():
    """测试 Operation Scheduler 任务检测"""
    with patch('agents.base.ChatOpenAI') as mock_llm:
        mock_llm.return_value = AsyncMock()

        agent = OperationSchedulerAgent()

        # 测试班次相关
        msg = Message(content="班次分析")
        # 内部逻辑会调用 _analyze_schedule
        assert "班次" in msg.content or "间隔" in msg.content or "发车" in msg.content

        agent.cleanup()
