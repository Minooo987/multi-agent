"""
ReAct Agent 基类
实现 Reasoning + Acting 循环，替代固定工作流
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, TypedDict, Literal
from dataclasses import dataclass, field
from datetime import datetime
import json
import asyncio

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_anthropic import ChatAnthropic

from config.settings import settings


class ActionType(str, Enum):
    """动作类型"""
    THINK = "think"           # 思考
    QUERY_DB = "query_db"     # 查询数据库
    SEARCH_MEMORY = "search_memory"  # 搜索记忆
    CALCULATE = "calculate"   # 计算
    ASK_USER = "ask_user"     # 询问用户
    FINAL_ANSWER = "final_answer"  # 给出最终答案


@dataclass
class ThoughtAction:
    """ReAct 步骤"""
    step_number: int
    thought: str              # 思考内容
    action: ActionType        # 动作类型
    action_input: Dict[str, Any]  # 动作输入
    observation: Optional[str] = None  # 观察结果
    timestamp: datetime = field(default_factory=datetime.now)


class ReActState(TypedDict):
    """ReAct 状态"""
    query: str
    thought_history: List[ThoughtAction]
    current_step: int
    max_steps: int
    final_answer: Optional[str]
    context: Dict[str, Any]


class ReActAgent(ABC):
    """
    ReAct Agent 基类
    核心循环: Thought → Action → Observation → ... → Final Answer
    """

    def __init__(
        self,
        name: str,
        system_prompt: str,
        max_iterations: int = 10,
        tools: Dict[str, Any] = None
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.tools = tools or {}

        # LLM
        self.llm = ChatAnthropic(
            model=settings.model_name,
            anthropic_api_url=settings.model_base_url,
            anthropic_api_key=settings.model_api_key,
            temperature=0.3,
            max_tokens=4096
        )

        # 反思模块（将在1.2中实现）
        self.reflection_module = None

    async def run(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        运行 ReAct 循环
        """
        state = ReActState(
            query=query,
            thought_history=[],
            current_step=0,
            max_steps=self.max_iterations,
            final_answer=None,
            context=context or {}
        )

        print(f"[{self.name}] 开始 ReAct 循环，查询: {query[:50]}...")

        while state["current_step"] < state["max_steps"]:
            # 1. 思考下一步
            thought_action = await self._think(state)

            if thought_action.action == ActionType.FINAL_ANSWER:
                state["final_answer"] = thought_action.action_input.get("answer", "")
                print(f"[{self.name}] 达成最终答案")
                break

            # 2. 执行动作
            observation = await self._act(thought_action)
            thought_action.observation = observation

            # 3. 记录历史
            state["thought_history"].append(thought_action)
            state["current_step"] += 1

            # 4. 自我反思（将在1.2中启用）
            if self.reflection_module:
                reflection = await self.reflection_module.reflect(
                    thought_action, state["thought_history"]
                )
                if reflection.should_backtrack:
                    # 回退到之前的状态
                    state = self._backtrack(state, reflection.backtrack_to_step)

        return {
            "answer": state["final_answer"],
            "thought_history": [
                {
                    "step": t.step_number,
                    "thought": t.thought,
                    "action": t.action.value,
                    "input": t.action_input,
                    "observation": t.observation
                }
                for t in state["thought_history"]
            ],
            "steps_taken": state["current_step"],
            "context": state["context"]
        }

    async def _think(self, state: ReActState) -> ThoughtAction:
        """
        思考下一步行动
        """
        # 构建 prompt
        react_prompt = self._build_react_prompt(state)

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=react_prompt)
        ]

        response = await self.llm.ainvoke(messages)
        content = response.content

        # 解析 LLM 响应
        return self._parse_thought_action(content, state["current_step"] + 1)

    def _build_react_prompt(self, state: ReActState) -> str:
        """构建 ReAct prompt"""
        history_str = ""
        for ta in state["thought_history"][-5:]:  # 最近5步
            history_str += f"""
Step {ta.step_number}:
Thought: {ta.thought}
Action: {ta.action.value}
Input: {json.dumps(ta.action_input, ensure_ascii=False)}
Observation: {ta.observation or 'N/A'}
"""

        tools_desc = "\n".join([
            f"- {name}: {tool.get('description', 'No description')}"
            for name, tool in self.tools.items()
        ])

        return f"""请回答以下问题，使用 ReAct 模式（思考-行动-观察循环）。

问题: {state['query']}

可用工具:
{tools_desc}

历史步骤:
{history_str}

当前是第 {state['current_step'] + 1} 步。

请按以下格式输出你的思考:
Thought: <你的思考过程，分析当前状态>
Action: <选择以下之一: think, query_db, search_memory, calculate, ask_user, final_answer>
Action Input: <JSON格式的输入>

如果已有足够信息，请使用 Action: final_answer 给出最终答案。
"""

    def _parse_thought_action(self, content: str, step_number: int) -> ThoughtAction:
        """解析 LLM 响应为 ThoughtAction"""
        thought = ""
        action = ActionType.THINK
        action_input = {}

        # 提取 Thought
        if "Thought:" in content:
            thought = content.split("Thought:")[1].split("Action:")[0].strip()

        # 提取 Action
        if "Action:" in content:
            action_str = content.split("Action:")[1].split("Action Input:")[0].strip().lower()
            try:
                action = ActionType(action_str)
            except ValueError:
                action = ActionType.THINK

        # 提取 Action Input
        if "Action Input:" in content:
            input_str = content.split("Action Input:")[1].strip()
            try:
                # 尝试解析 JSON
                if "```json" in input_str:
                    input_str = input_str.split("```json")[1].split("```")[0].strip()
                action_input = json.loads(input_str)
            except:
                action_input = {"raw": input_str}

        return ThoughtAction(
            step_number=step_number,
            thought=thought,
            action=action,
            action_input=action_input
        )

    async def _act(self, thought_action: ThoughtAction) -> str:
        """执行动作"""
        action = thought_action.action
        input_data = thought_action.action_input

        if action == ActionType.QUERY_DB:
            return await self._tool_query_db(input_data)
        elif action == ActionType.SEARCH_MEMORY:
            return await self._tool_search_memory(input_data)
        elif action == ActionType.CALCULATE:
            return await self._tool_calculate(input_data)
        elif action == ActionType.ASK_USER:
            return await self._tool_ask_user(input_data)
        elif action == ActionType.THINK:
            return "思考完成，继续下一步"
        else:
            return f"未知动作: {action}"

    @abstractmethod
    async def _tool_query_db(self, input_data: Dict) -> str:
        """查询数据库工具"""
        pass

    async def _tool_search_memory(self, input_data: Dict) -> str:
        """搜索记忆工具（将在2.1中实现）"""
        return "记忆搜索功能待实现"

    async def _tool_calculate(self, input_data: Dict) -> str:
        """计算工具"""
        try:
            expression = input_data.get("expression", "")
            # 安全计算
            allowed_names = {"sum": sum, "len": len, "max": max, "min": min}
            result = eval(expression, {"__builtins__": {}}, allowed_names)
            return str(result)
        except Exception as e:
            return f"计算错误: {e}"

    async def _tool_ask_user(self, input_data: Dict) -> str:
        """询问用户工具"""
        question = input_data.get("question", "")
        # 在实际实现中，这可能需要通过 WebSocket 发送给用户
        return f"已向用户提问: {question}"

    def _backtrack(self, state: ReActState, to_step: int) -> ReActState:
        """回退到指定步骤"""
        state["thought_history"] = state["thought_history"][:to_step]
        state["current_step"] = to_step
        return state


class ActionType(str, Enum):
    """动作类型"""
    THINK = "think"
    QUERY_DB = "query_db"
    SEARCH_MEMORY = "search_memory"
    CALCULATE = "calculate"
    ASK_USER = "ask_user"
    FINAL_ANSWER = "final_answer"
