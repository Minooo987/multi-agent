"""
LangGraph 工作流定义
等效 Claude Code Agent Teams 的 workflow orchestration
"""

from typing import Dict, Any, List, Optional, TypedDict
import asyncio
import json
import re
from datetime import datetime

from langgraph.graph import StateGraph, END
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command, interrupt

from graph.state import TeamState, Task, TaskStatus, Message, AgentRole
from agents.task_manager import TaskManagerAgent
from agents.passenger_processor import PassengerProcessorAgent
from agents.operation_scheduler import OperationSchedulerAgent
from tools.message_bus import message_bus


class AgentTeamGraph:
    """
    Agent Teams 工作流图
    等效 Claude Code 的 Agent Teams 协作流程
    """

    def __init__(self):
        self.task_manager = TaskManagerAgent()
        self.passenger_processor = PassengerProcessorAgent()
        self.operation_scheduler = OperationSchedulerAgent()

        # 构建工作流图
        self.workflow = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """构建 LangGraph 工作流"""

        class State(TypedDict):
            request: str
            tasks: List[Task]
            messages: List[Message]
            results: Dict[str, Any]
            status: str
            current_step: str
            error: Optional[str]
            requires_human_review: bool
            human_feedback: Optional[str]
            analysis: Optional[Dict[str, Any]]

        graph = StateGraph(State)

        # 添加节点
        graph.add_node("analyze_request", self._analyze_request)
        graph.add_node("create_tasks", self._create_tasks)
        graph.add_node("process_tasks", self._process_tasks)
        graph.add_node("aggregate_results", self._aggregate_results)
        graph.add_node("human_review", self._human_review)
        graph.add_node("finalize", self._finalize)
        graph.add_node("handle_error", self._handle_error)

        # 定义边和条件
        graph.set_entry_point("analyze_request")

        graph.add_conditional_edges(
            "analyze_request",
            self._should_continue_or_error,
            {"continue": "create_tasks", "error": "handle_error"}
        )

        graph.add_edge("create_tasks", "process_tasks")
        graph.add_edge("process_tasks", "aggregate_results")

        graph.add_conditional_edges(
            "aggregate_results",
            self._should_human_review,
            {"review": "human_review", "finalize": "finalize"}
        )

        graph.add_conditional_edges(
            "human_review",
            self._after_human_review,
            {"finalize": "finalize", "reprocess": "create_tasks", "end": END}
        )

        graph.add_edge("handle_error", END)
        graph.add_edge("finalize", END)

        memory = MemorySaver()

        return graph.compile(
            checkpointer=memory,
            interrupt_before=["human_review"],
        )

    async def _analyze_request(self, state: Dict) -> Dict:
        """分析用户请求 - 基于关键词匹配 + 上下文继承"""
        request = state.get('request', '')

        # 提取原始查询和上下文
        original_request = request
        context_section = ""
        if '[对话上下文]' in request:
            parts = request.split('[对话上下文]', 1)
            original_request = parts[0].strip()
            context_section = parts[1].strip() if len(parts) > 1 else ""

        print(f"[Graph] 分析请求: {original_request[:80]}...")

        # 从上下文中提取上一轮配置
        prev_config = {}
        if context_section:
            prev_config = self._extract_json_from_context(context_section)
            if prev_config:
                print(f"[Graph] 继承上轮配置: {prev_config}")

        # 判断是否是简写查询（只有日期范围，缺少分析对象）
        date_only_patterns = [
            r'^[\d月日\-~到至周上本今昨前天]+$',  # 纯日期表达
            r'^\d+月\d+日[\-~到至]\d+月?\d*日?$',  # "3月5日-3月20日"
            r'^(上周|本周|昨天|前天|今天|本月|上月)$',  # 相对时间
        ]
        # 指代词：查询依赖上文的日期范围
        coreferential_keywords = ['该时间段', '该时间', '这个时间段', '此时间段', '上述时间', '刚才', '之前', '上次']
        has_coreferential = any(kw in original_request for kw in coreferential_keywords)

        is_shortened = any(re.match(p, original_request.strip()) for p in date_only_patterns) or has_coreferential

        # 分析意图
        if is_shortened and prev_config:
            # 简写查询：继承上轮配置
            needs_passenger = prev_config.get('needs_passenger', True)
            needs_operation = prev_config.get('needs_operation', True)
            print(f"[Graph] 简写查询，继承上轮: passenger={needs_passenger}, operation={needs_operation}")
        else:
            # 完整查询：关键词匹配
            needs_passenger, needs_operation = self._match_analysis_type(original_request)

        analysis = {
            'needs_passenger': needs_passenger,
            'needs_operation': needs_operation,
            'needs_human_review': False,
            'inferred_from_context': is_shortened and bool(prev_config),
            'date_range': prev_config.get('date_range', {}) if prev_config else {}
        }

        print(f"[Graph] 分析结果: passenger={needs_passenger}, operation={needs_operation}, shortened={is_shortened}")

        return {
            **state,
            'analysis': analysis,
            'status': 'analyzed',
            'current_step': 'analyze_request'
        }

    def _extract_json_from_context(self, text: str) -> dict:
        """从文本中提取第一个完整的 JSON 对象（支持嵌套）。

        使用括号计数而非正则，避免非贪婪匹配在嵌套 JSON 的第一个 } 处停止。
        """
        marker = '上一轮配置:'
        start = text.find(marker)
        if start == -1:
            return {}

        # 从 marker 之后找第一个 {
        json_start = text.find('{', start + len(marker))
        if json_start == -1:
            return {}

        brace_count = 0
        for i, char in enumerate(text[json_start:]):
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    try:
                        return json.loads(text[json_start:json_start + i + 1])
                    except json.JSONDecodeError:
                        return {}
        return {}

    def _match_analysis_type(self, query: str) -> tuple:
        """基于关键词匹配分析类型"""
        # 动态公交关键词
        dynamic_keywords = ["动态", "DY_ORDER", "预约", "订单", "动态公交"]
        is_dynamic = any(kw in query for kw in dynamic_keywords)

        if is_dynamic:
            # 显式里程关键词（不含"司机"，因为"司机"可搭配订单使用）
            explicit_mileage_keywords = ["里程", "mileage", "工作时长", "行驶", "空驶", "载客里程"]
            order_keywords = ["订单", "order", "乘客数", "完成率", "取消", "预约", "客流", "人数", "客运", "接单", "派单"]

            has_explicit_mileage = any(kw in query for kw in explicit_mileage_keywords)
            has_order = any(kw in query for kw in order_keywords)
            has_driver = "司机" in query

            # "司机" + 显式里程关键词 → 里程查询
            if has_driver and has_explicit_mileage and not has_order:
                return True, False
            # 有显式里程关键词（不含司机）→ 里程查询
            if has_explicit_mileage and not has_order:
                return True, False
            # 有订单关键词，无显式里程 → 订单查询（"司机"不触发里程路由）
            if has_order and not has_explicit_mileage:
                return False, True
            # 两者都有 → 都分析
            if has_explicit_mileage and has_order:
                return True, True
            # 都没有 → 都分析
            return True, True

        # 通用关键词匹配
        passenger_keywords = ['刷卡', '上车', '下车', '里程', '行驶', '运营时长', '载客里程', '空驶']
        operation_keywords = ['营运', '班次', '车辆', '调度', '运营', '效率', '订单', '客流', '乘客', '人数', '完成率', '取消', '站点', '车站', '上车站点', '下车站点', '接单', '派单']

        has_passenger = any(kw in query for kw in passenger_keywords)
        has_operation = any(kw in query for kw in operation_keywords)

        # 里程主导规则：查询明确涉及里程时，只由 passenger_processor 处理
        if has_passenger and '里程' in query:
            return True, False

        # 客流/订单/站点主导规则：查询涉及客流、订单、站点时，只由 operation_scheduler 处理
        if has_operation and any(kw in query for kw in ['客流', '订单', '站点', '车站', '取消', '完成率']):
            return False, True

        if not has_passenger and not has_operation:
            # 无法判断时两者都分析
            return True, True

        return has_passenger, has_operation

    async def _create_tasks(self, state: Dict) -> Dict:
        """创建任务列表"""
        print("[Graph] 创建任务")

        analysis = state.get('analysis', {})
        tasks = []

        needs_passenger = analysis.get('needs_passenger')
        needs_operation = analysis.get('needs_operation')

        print(f"[Graph] 任务分配: needs_passenger={needs_passenger}, needs_operation={needs_operation}")

        if needs_passenger is True:
            tasks.append(Task(
                id=f"passenger_{datetime.now().timestamp()}",
                type="passenger",
                description=state.get('request', ''),
                status=TaskStatus.PENDING
            ))
            print("[Graph] 创建 passenger 任务")

        if needs_operation is True:
            tasks.append(Task(
                id=f"operation_{datetime.now().timestamp()}",
                type="operation",
                description=state.get('request', ''),
                status=TaskStatus.PENDING
            ))
            print("[Graph] 创建 operation 任务")

        print(f"[Graph] 共创建 {len(tasks)} 个任务")

        return {
            **state,
            'tasks': tasks,
            'status': 'tasks_created',
            'current_step': 'create_tasks'
        }

    async def _process_tasks(self, state: Dict) -> Dict:
        """并行处理所有任务（使用 asyncio.gather）"""
        tasks = state.get('tasks', [])
        print(f"[Graph] 并行处理 {len(tasks)} 个任务")

        if not tasks:
            state['results'] = {}
            return state

        analysis = state.get('analysis', {})

        async def execute_task(task):
            """执行单个任务"""
            print(f"[Graph] 开始执行任务: {task.type}")
            try:
                task.status = TaskStatus.PROCESSING

                if task.type == "passenger":
                    result = await self._execute_passenger(task, analysis)
                elif task.type == "operation":
                    result = await self._execute_operation(task, analysis)
                else:
                    raise ValueError(f"未知任务类型: {task.type}")

                task.status = TaskStatus.COMPLETED
                task.result = result
                return task.type, result

            except Exception as e:
                print(f"[Graph] 任务失败 {task.type}: {e}")
                import traceback
                traceback.print_exc()
                task.status = TaskStatus.FAILED
                task.error = str(e)
                return task.type, {
                    "error": str(e),
                    "key_findings": [f"任务执行失败: {str(e)}"],
                    "analysis": {"error": str(e)}
                }

        results_list = await asyncio.gather(*[execute_task(t) for t in tasks])

        results = {}
        for task_type, result in results_list:
            results[task_type] = result

        print(f"[Graph] 所有任务完成，结果: {list(results.keys())}")

        state['results'] = results
        state['current_step'] = 'process_tasks'
        return state

    async def _execute_passenger(self, task, analysis: Dict = None) -> dict:
        """执行 passenger 任务"""
        from graph.state import Message

        content = task.description
        # 如果 analysis 中有 date_range，注入到查询中
        if analysis and analysis.get('date_range'):
            dr = analysis['date_range']
            if dr.get('start') and dr.get('end'):
                # 检查查询是否已包含日期
                has_date = any(kw in content for kw in ['月', '日', 'TO_DATE', 'SYSDATE'])
                if not has_date:
                    content = f"{content}（日期范围：{dr['start']} 至 {dr['end']}）"

        message = Message(
            from_agent="task_manager",
            to_agent="passenger_processor",
            content=content,
            message_type="task",
            metadata={"analysis": analysis or {}}
        )

        try:
            result = await self.passenger_processor.process_message(message)

            if isinstance(result, dict):
                if 'key_findings' not in result:
                    result['key_findings'] = []
            else:
                result = {"raw_result": str(result), "key_findings": [], "analysis": {}}

            return result
        except Exception as e:
            print(f"[Graph] _execute_passenger 异常: {e}")
            return {"error": str(e), "key_findings": [f"执行异常: {str(e)}"], "analysis": {"error": str(e)}}

    async def _execute_operation(self, task, analysis: Dict = None) -> dict:
        """执行 operation 任务"""
        from graph.state import Message

        content = task.description
        # 如果 analysis 中有 date_range，注入到查询中
        if analysis and analysis.get('date_range'):
            dr = analysis['date_range']
            if dr.get('start') and dr.get('end'):
                has_date = any(kw in content for kw in ['月', '日', 'TO_DATE', 'SYSDATE'])
                if not has_date:
                    content = f"{content}（日期范围：{dr['start']} 至 {dr['end']}）"

        message = Message(
            from_agent="task_manager",
            to_agent="operation_scheduler",
            content=content,
            message_type="task",
            metadata={"analysis": analysis or {}}
        )

        try:
            result = await self.operation_scheduler.process_message(message)

            if isinstance(result, dict):
                if 'key_findings' not in result:
                    result['key_findings'] = []
            else:
                result = {"raw_result": str(result), "key_findings": [], "analysis": {}}

            return result
        except Exception as e:
            print(f"[Graph] _execute_operation 异常: {e}")
            return {"error": str(e), "key_findings": [f"执行异常: {str(e)}"], "analysis": {"error": str(e)}}

    async def _aggregate_results(self, state: Dict) -> Dict:
        """聚合结果"""
        print("[Graph] 聚合结果")

        results = state.get('results', {})
        passenger_result = results.get('passenger', {})
        operation_result = results.get('operation', {})

        # 合并关键发现
        findings = []
        if passenger_result and isinstance(passenger_result, dict) and 'key_findings' in passenger_result:
            findings.extend(passenger_result['key_findings'])
        if operation_result and isinstance(operation_result, dict) and 'key_findings' in operation_result:
            findings.extend(operation_result['key_findings'])

        final_report = {
            "analysis_summary": "数据分析完成",
            "key_findings": findings,
            "details": {
                "passenger": passenger_result,
                "operation": operation_result
            }
        }

        state['final_report'] = final_report
        state['status'] = 'aggregated'
        state['current_step'] = 'aggregate_results'

        return state

    async def _human_review(self, state: Dict) -> Dict:
        """人工审核节点"""
        print("[Graph] 等待人工审核...")

        feedback = interrupt({
            "final_report": state.get('final_report', ''),
            "status": state.get('status'),
            "message": "请审核生成的报告。输入 'approve' 批准，或提供修改建议。"
        })

        state['human_feedback'] = feedback
        state['requires_human_review'] = False
        state['current_step'] = 'human_review'

        return state

    async def _finalize(self, state: Dict) -> Dict:
        """完成工作流"""
        print("[Graph] 完成工作流")

        results = state.get('results', {})

        if not state.get('final_report'):
            passenger_result = results.get('passenger', {})
            operation_result = results.get('operation', {})

            findings = []
            if passenger_result and 'key_findings' in passenger_result:
                findings.extend(passenger_result['key_findings'])
            if operation_result and 'key_findings' in operation_result:
                findings.extend(operation_result['key_findings'])

            state['final_report'] = {
                "analysis_summary": "数据分析完成",
                "key_findings": findings,
                "details": {
                    "passenger": passenger_result,
                    "operation": operation_result
                }
            }

        state['status'] = 'completed'
        state['current_step'] = 'finalize'
        state['completed_at'] = datetime.now().isoformat()
        state['results'] = results

        return state

    async def _handle_error(self, state: Dict) -> Dict:
        """错误处理"""
        print(f"[Graph] 错误处理: {state.get('error')}")
        state['status'] = 'error'
        state['final_report'] = f"处理失败: {state.get('error', '未知错误')}"
        return state

    # 条件函数
    def _should_continue_or_error(self, state: Dict) -> str:
        if state.get('error'):
            return 'error'
        return 'continue'

    def _should_human_review(self, state: Dict) -> str:
        analysis = state.get('analysis', {})
        if analysis.get('needs_human_review', False):
            return 'review'
        return 'finalize'

    def _after_human_review(self, state: Dict) -> str:
        feedback = state.get('human_feedback', '').lower()
        if feedback == 'end' or feedback == '终止':
            return 'end'
        elif feedback == 'approve' or feedback == '批准':
            return 'finalize'
        else:
            return 'reprocess'

    async def run(self, request: str, thread_id: Optional[str] = None) -> Dict[str, Any]:
        """运行工作流"""
        initial_state = {
            "request": request,
            "tasks": [],
            "messages": [],
            "results": {},
            "status": "started",
            "current_step": "",
            "error": None,
            "requires_human_review": False,
            "human_feedback": None
        }

        config = {"configurable": {"thread_id": thread_id or "default"}}

        result = await self.workflow.ainvoke(initial_state, config)

        if hasattr(result, 'values') and isinstance(result.values, dict):
            result = result.values

        return result

    def get_state(self, thread_id: str) -> Optional[Dict]:
        """获取指定线程的状态"""
        config = {"configurable": {"thread_id": thread_id}}
        state = self.workflow.get_state(config)
        if state:
            return {
                "status": getattr(state, 'status', 'unknown'),
                "current_step": getattr(state, 'current_step', None),
                "tasks": getattr(state, 'tasks', []),
                "error": getattr(state, 'error', None)
            }
        return None

    def resume_after_interrupt(self, thread_id: str, feedback: str) -> Dict[str, Any]:
        """在中断后恢复执行"""
        config = {"configurable": {"thread_id": thread_id}}
        result = self.workflow.invoke(
            Command(resume=feedback),
            config
        )
        return result


# 全局图实例
team_graph = AgentTeamGraph()
