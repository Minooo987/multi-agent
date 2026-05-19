"""
消息总线
等效 Claude Code 的 SendMessage 机制
"""

import asyncio
from typing import Dict, List, Callable, Any
from collections import defaultdict
import json
from datetime import datetime

from graph.state import Message


class MessageBus:
    """
    消息总线 - 等效 Claude Code SendMessage
    实现 Agent 间异步通信
    """

    def __init__(self):
        self.subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self.message_history: List[Dict] = []
        self.message_queue: asyncio.Queue = asyncio.Queue()
        self.running = False

    def subscribe(self, agent_name: str, callback: Callable[[Message], Any]):
        """Agent 订阅消息"""
        self.subscribers[agent_name].append(callback)
        print(f"[MessageBus] {agent_name} 已订阅")

    def unsubscribe(self, agent_name: str, callback: Callable = None):
        """取消订阅"""
        if callback and callback in self.subscribers[agent_name]:
            self.subscribers[agent_name].remove(callback)
        elif not callback:
            self.subscribers[agent_name] = []

    async def send_message(self, message: Message) -> bool:
        """
        发送消息 - 等效 SendMessage 工具
        """
        # 记录消息
        msg_dict = message.to_dict()
        self.message_history.append(msg_dict)

        # 添加到消息队列
        await self.message_queue.put(message)

        # 立即通知订阅者
        target = message.to_agent
        if target in self.subscribers:
            for callback in self.subscribers[target]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        asyncio.create_task(callback(message))
                    else:
                        callback(message)
                except Exception as e:
                    print(f"[MessageBus] 消息发送失败: {e}")

        print(f"[MessageBus] {message.from_agent} -> {message.to_agent}: {message.content[:50]}...")
        return True

    async def broadcast(self, from_agent: str, content: str, message_type: str = "system"):
        """广播消息给所有 Agent"""
        for agent_name in self.subscribers.keys():
            msg = Message(
                from_agent=from_agent,
                to_agent=agent_name,
                content=content,
                message_type=message_type
            )
            await self.send_message(msg)

    def get_message_history(
        self,
        from_agent: str = None,
        to_agent: str = None,
        message_type: str = None,
        limit: int = 100
    ) -> List[Dict]:
        """获取消息历史"""
        messages = self.message_history[-limit:]

        if from_agent:
            messages = [m for m in messages if m.get("from_agent") == from_agent]
        if to_agent:
            messages = [m for m in messages if m.get("to_agent") == to_agent]
        if message_type:
            messages = [m for m in messages if m.get("message_type") == message_type]

        return messages

    def get_conversation(
        self,
        agent1: str,
        agent2: str,
        limit: int = 50
    ) -> List[Dict]:
        """获取两个 Agent 之间的对话历史"""
        messages = self.message_history[-limit:]
        conversation = [
            m for m in messages
            if (m.get("from_agent") == agent1 and m.get("to_agent") == agent2) or
               (m.get("from_agent") == agent2 and m.get("to_agent") == agent1)
        ]
        return conversation

    def clear_history(self):
        """清空消息历史"""
        self.message_history = []

    async def start(self):
        """启动消息总线"""
        self.running = True
        print("[MessageBus] 消息总线已启动")

    async def stop(self):
        """停止消息总线"""
        self.running = False
        print("[MessageBus] 消息总线已停止")


# 全局消息总线实例
message_bus = MessageBus()
