"""
测试 Message Bus
"""

import pytest
import asyncio
from unittest.mock import AsyncMock

from tools.message_bus import MessageBus, message_bus
from graph.state import Message, AgentRole


@pytest.fixture
def reset_message_bus():
    """重置消息总线"""
    message_bus.subscribers.clear()
    message_bus.messages.clear()
    yield
    message_bus.subscribers.clear()
    message_bus.messages.clear()


@pytest.mark.asyncio
async def test_subscribe(reset_message_bus):
    """测试订阅"""
    callback = AsyncMock()

    message_bus.subscribe("test_agent", callback)

    assert "test_agent" in message_bus.subscribers
    assert message_bus.subscribers["test_agent"] == callback


@pytest.mark.asyncio
async def test_send_message(reset_message_bus):
    """测试发送消息"""
    callback = AsyncMock()
    message_bus.subscribe("receiver", callback)

    msg = Message(
        from_agent="sender",
        to_agent="receiver",
        content="test message"
    )

    await message_bus.send_message(msg)

    # 验证消息被记录
    assert len(message_bus.messages) == 1

    # 验证回调被调用
    callback.assert_called_once()
    call_args = callback.call_args[0][0]
    assert call_args.content == "test message"


@pytest.mark.asyncio
async def test_get_conversation(reset_message_bus):
    """测试获取对话历史"""
    msg1 = Message(from_agent="a", to_agent="b", content="msg1")
    msg2 = Message(from_agent="b", to_agent="a", content="msg2")
    msg3 = Message(from_agent="a", to_agent="c", content="msg3")

    message_bus.messages = [msg1, msg2, msg3]

    history = message_bus.get_conversation("a", "b")

    assert len(history) == 2
    assert history[0]["content"] == "msg1"
    assert history[1]["content"] == "msg2"


@pytest.mark.asyncio
async def test_broadcast(reset_message_bus):
    """测试广播"""
    callback1 = AsyncMock()
    callback2 = AsyncMock()

    message_bus.subscribe("agent1", callback1)
    message_bus.subscribe("agent2", callback2)

    await message_bus.broadcast("broadcast message")

    callback1.assert_called_once()
    callback2.assert_called_once()
