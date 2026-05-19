"""
任务管理者 Agent
等效 Claude Code 的 task-manager
"""

import json
from typing import Any, Dict
from datetime import datetime
import uuid

from agents.base import BaseAgent
from graph.state import Message, Task, TaskStatus, AgentRole
from tools.message_bus import message_bus


class TaskManagerAgent(BaseAgent):
    """
    任务管理者 Agent
    职责：理解需求、任务分割、分配任务、收集整合结果
    """

    def __init__(self):
        super().__init__(
            name="task_manager",
            role=AgentRole.TASK_MANAGER,
            system_prompt="""你是数据分析团队的任务管理者（Task Manager）。

## 你的职责
1. **理解用户需求**：仔细分析用户提出的数据分析需求
2. **任务分割**：将复杂的数据分析任务拆分为独立的子任务
3. **任务分配**：
   - 客流数据相关任务 → 分配给 passenger_processor
   - 营运调度数据相关任务 → 分配给 operation_scheduler
4. **结果收集与整合**：收集两个数据处理者返回的结果，整合成完整的回复

## 任务分配规则
- 当需求涉及客流分析、站点统计、刷卡记录 → passenger_processor
- 当需求涉及班次优化、车辆调度、营运效率 → operation_scheduler
- 当需求同时涉及两者 → 同时分配给两个 Agent

## 通信规则
- 你可以直接与用户通信
- 你需要通过 SendMessage 与 passenger_processor 和 operation_scheduler 通信
- 你不直接处理数据，只负责任务协调和结果整合

## 输出格式
分析用户需求后，输出 JSON 格式的任务分配：
{
    "tasks": [
        {"type": "passenger", "description": "具体任务描述"},
        {"type": "operation", "description": "具体任务描述"}
    ],
    "reasoning": "任务分配理由"
}""",
            can_talk_to=["user", "passenger_processor", "operation_scheduler"],
            max_retries=3,
            use_mcp=False
        )
        # 存储任务结果
        self.pending_tasks: Dict[str, Dict[str, Any]] = {}
        self.completed_results: Dict[str, Dict[str, Any]] = {}

    async def process_message(self, message: Message) -> Any:
        """处理消息"""
        content = message.content

        # 判断消息类型
        if message.message_type == "result":
            # 收到处理结果，进行整合
            return await self._aggregate_results(message)
        else:
            # 新需求，进行任务分配
            return await self._analyze_and_assign(content)

    async def _analyze_and_assign(self, user_request: str) -> str:
        """分析需求并分配任务"""

        # 先用关键词快速判断
        dynamic_keywords = ["动态", "DY_ORDER", "预约", "订单", "动态公交"]
        is_dynamic = any(kw in user_request for kw in dynamic_keywords)

        if is_dynamic:
            mileage_keywords = ["里程", "mileage", "司机", "工作时长", "行驶", "空驶", "载客里程"]
            order_keywords = ["订单", "order", "乘客数", "完成率", "取消", "预约", "客流", "人数", "客运"]

            has_mileage = any(kw in user_request for kw in mileage_keywords)
            has_order = any(kw in user_request for kw in order_keywords)

            if has_mileage and not has_order:
                print(f"[TaskManager] 动态公交里程查询，分配给 passenger_processor")
                await self.send_task("passenger_processor", f"分析动态公交行驶里程: {user_request}")
                return "已分配动态公交里程分析任务给行驶里程处理者"
            elif has_order and not has_mileage:
                print(f"[TaskManager] 动态公交订单查询，分配给 operation_scheduler")
                await self.send_task("operation_scheduler", f"分析动态公交订单数据: {user_request}")
                return "已分配动态公交订单分析任务给营运调度处理者"
            elif has_mileage and has_order:
                print(f"[TaskManager] 动态公交综合查询，同时分配给两个 Agent")
                await self.send_task("passenger_processor", f"分析动态公交行驶里程: {user_request}")
                await self.send_task("operation_scheduler", f"分析动态公交订单客流数据: {user_request}")
                return "已分配动态公交里程和订单分析任务"

        # 通用关键词匹配
        passenger_keywords = ['刷卡', '站点', '上车', '下车', '里程', '行驶', '运营时长', '载客里程']
        operation_keywords = ['营运', '班次', '车辆', '调度', '运营', '效率', '订单', '客流', '乘客', '人数', '完成率', '取消']

        has_passenger = any(kw in user_request for kw in passenger_keywords)
        has_operation = any(kw in user_request for kw in operation_keywords)

        if has_passenger and has_operation:
            await self.send_task("passenger_processor", user_request)
            await self.send_task("operation_scheduler", user_request)
            return "已分配任务给客流和营运处理者"
        elif has_passenger:
            await self.send_task("passenger_processor", user_request)
            return "已分配客流分析任务"
        elif has_operation:
            await self.send_task("operation_scheduler", user_request)
            return "已分配营运分析任务"
        else:
            # 默认同时分配
            await self.send_task("passenger_processor", user_request)
            await self.send_task("operation_scheduler", user_request)
            return "已分配任务（默认配置）"

    async def _aggregate_results(self, message: Message) -> Dict[str, Any]:
        """整合结果 - 收集多 Agent 结果并合并"""
        from_agent = message.from_agent
        content = message.content
        task_id = message.metadata.get("task_id", "unknown")

        print(f"[TaskManager] 收到来自 {from_agent} 的结果 (任务: {task_id})")

        # 解析结果内容
        try:
            if isinstance(content, str):
                result_data = json.loads(content)
            else:
                result_data = content
        except json.JSONDecodeError:
            result_data = {"raw_content": content}

        # 存储结果
        if task_id in self.pending_tasks:
            self.pending_tasks[task_id]["results"][from_agent] = result_data

            # 检查是否所有 Agent 都返回了结果
            assigned = set(self.pending_tasks[task_id]["assigned_agents"])
            returned = set(self.pending_tasks[task_id]["results"].keys())

            if returned >= assigned:
                return await self._merge_results(task_id)
            else:
                pending = assigned - returned
                return {
                    "status": "partial",
                    "task_id": task_id,
                    "received_from": from_agent,
                    "pending_agents": list(pending),
                    "message": f"已收到 {from_agent} 的结果，等待 {list(pending)}"
                }
        else:
            return {
                "status": "unknown_task",
                "from_agent": from_agent,
                "content": result_data
            }

    async def _merge_results(self, task_id: str) -> Dict[str, Any]:
        """合并多个 Agent 的结果"""
        task = self.pending_tasks.get(task_id)
        if not task:
            return {"error": f"Task {task_id} not found"}

        results = task["results"]

        # 移动到已完成
        self.completed_results[task_id] = {
            **task,
            "merged_at": datetime.now().isoformat(),
            "status": "completed"
        }
        del self.pending_tasks[task_id]

        merged_report = {
            "task_id": task_id,
            "description": task["description"],
            "status": "completed",
            "agents": list(results.keys()),
            "results": results,
            "summary": self._generate_summary(results)
        }

        print(f"[TaskManager] 任务 {task_id} 结果已整合完成")
        return merged_report

    def _generate_summary(self, results: Dict[str, Any]) -> str:
        """生成结果摘要"""
        summaries = []
        for agent, result in results.items():
            if isinstance(result, dict):
                if "analysis" in result:
                    summaries.append(f"{agent}: 提供了分析结果")
                elif "sql" in result:
                    summaries.append(f"{agent}: 执行了SQL查询")
                elif "error" in result:
                    summaries.append(f"{agent}: 处理出错 - {result['error']}")
                else:
                    summaries.append(f"{agent}: 完成")
            else:
                summaries.append(f"{agent}: {str(result)[:50]}...")
        return "; ".join(summaries) if summaries else "无可用摘要"

    async def send_task(self, to_agent: str, description: str, task_id: str = None):
        """发送任务给指定 Agent"""
        from graph.state import Message
        task_id = task_id or f"task_{uuid.uuid4().hex[:8]}"

        if task_id not in self.pending_tasks:
            self.pending_tasks[task_id] = {
                "id": task_id,
                "description": description,
                "assigned_agents": [],
                "results": {},
                "status": "pending",
                "created_at": datetime.now().isoformat()
            }

        self.pending_tasks[task_id]["assigned_agents"].append(to_agent)

        msg = Message(
            from_agent=self.name,
            to_agent=to_agent,
            content=description,
            message_type="task",
            metadata={"task_id": task_id}
        )
        await message_bus.send_message(msg)
        print(f"[TaskManager] 已发送任务 [{task_id}] 给 {to_agent}: {description[:50]}...")
        return task_id
