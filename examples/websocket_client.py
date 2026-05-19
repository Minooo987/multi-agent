"""
Python WebSocket 客户端示例
用于与 Agent Teams API 实时通信
"""

import asyncio
import json
import websockets
from typing import Callable, Optional


class AgentTeamsClient:
    """
    Agent Teams WebSocket 客户端

    Usage:
        client = AgentTeamsClient("ws://localhost:8000/ws/client-001")
        await client.connect()
        await client.analyze("分析昨天客流")
    """

    def __init__(
        self,
        uri: str,
        on_message: Optional[Callable] = None,
        on_error: Optional[Callable] = None
    ):
        self.uri = uri
        self.websocket = None
        self.on_message = on_message or self._default_on_message
        self.on_error = on_error or self._default_on_error
        self.connected = False

    async def connect(self):
        """连接 WebSocket"""
        try:
            self.websocket = await websockets.connect(self.uri)
            self.connected = True
            print(f"✅ 已连接到 {self.uri}")

            # 启动消息接收循环
            asyncio.create_task(self._receive_loop())

        except Exception as e:
            print(f"❌ 连接失败: {e}")
            raise

    async def disconnect(self):
        """断开连接"""
        if self.websocket:
            await self.websocket.close()
            self.connected = False
            print("🔌 已断开连接")

    async def analyze(self, query: str, thread_id: Optional[str] = None):
        """
        发送分析请求

        Args:
            query: 分析查询
            thread_id: 可选的会话ID
        """
        message = {
            "type": "analyze",
            "query": query
        }
        if thread_id:
            message["thread_id"] = thread_id

        await self._send(message)
        print(f"📤 发送分析请求: {query}")

    async def submit_feedback(self, thread_id: str, feedback: str):
        """
        提交人工反馈

        Args:
            thread_id: 会话ID
            feedback: 反馈内容 ('approve' 或建议)
        """
        await self._send({
            "type": "feedback",
            "thread_id": thread_id,
            "feedback": feedback
        })
        print(f"📤 提交反馈: {feedback}")

    async def get_status(self, thread_id: str):
        """
        查询任务状态

        Args:
            thread_id: 会话ID
        """
        await self._send({
            "type": "status",
            "thread_id": thread_id
        })

    async def _send(self, message: dict):
        """发送消息"""
        if not self.websocket:
            raise RuntimeError("未连接到服务器")

        await self.websocket.send(json.dumps(message))

    async def _receive_loop(self):
        """接收消息循环"""
        try:
            async for message in self.websocket:
                data = json.loads(message)
                await self.on_message(data)
        except websockets.exceptions.ConnectionClosed:
            self.connected = False
            print("🔌 连接已关闭")
        except Exception as e:
            await self.on_error(e)

    async def _default_on_message(self, data: dict):
        """默认消息处理器"""
        msg_type = data.get('type')

        if msg_type == 'started':
            print(f"🚀 任务已启动: {data.get('thread_id')}")

        elif msg_type == 'completed':
            print(f"✅ 任务完成: {data.get('thread_id')}")
            print(f"📊 结果: {data.get('result', 'N/A')[:200]}...")

        elif msg_type == 'error':
            print(f"❌ 错误: {data.get('error')}")

        elif msg_type == 'status':
            print(f"📋 状态: {data.get('state', {})}")

        else:
            print(f"📨 收到消息: {data}")

    async def _default_on_error(self, error: Exception):
        """默认错误处理器"""
        print(f"❌ 错误: {error}")


async def demo():
    """演示用法"""
    client = AgentTeamsClient("ws://localhost:8000/ws/demo-client")

    try:
        await client.connect()

        # 发送分析请求
        await client.analyze("分析昨天各线路的客流情况")

        # 等待结果
        await asyncio.sleep(10)

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(demo())
