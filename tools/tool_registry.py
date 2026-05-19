"""
动态工具注册和管理系统
支持工具的热插拔、动态发现和智能选择
"""

from typing import Dict, List, Any, Optional, Callable, Type
from dataclasses import dataclass, field
from datetime import datetime
import inspect
import asyncio
import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_anthropic import ChatAnthropic

from config.settings import settings


@dataclass
class Tool:
    """工具定义"""
    name: str
    description: str
    function: Callable
    parameters: Dict[str, Any]  # JSON Schema
    return_type: str
    category: str               # 工具类别: db, memory, calc, external
    success_rate: float = 1.0   # 成功率
    avg_execution_time: float = 0.0  # 平均执行时间
    usage_count: int = 0        # 使用次数
    tags: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "return_type": self.return_type,
            "category": self.category,
            "success_rate": self.success_rate,
            "avg_execution_time": self.avg_execution_time,
            "usage_count": self.usage_count,
            "tags": self.tags
        }


@dataclass
class ToolExecutionResult:
    """工具执行结果"""
    tool_name: str
    success: bool
    result: Any
    execution_time: float
    error_message: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)


class ToolRegistry:
    """
    工具注册中心
    支持动态注册、发现和选择工具
    """

    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        self.execution_history: List[ToolExecutionResult] = []
        self.llm = ChatAnthropic(
            model=settings.model_name,
            anthropic_api_url=settings.model_base_url,
            anthropic_api_key=settings.model_api_key,
            temperature=0.2,
            max_tokens=1024
        )

    def register(
        self,
        name: str,
        description: str,
        function: Callable,
        parameters: Dict[str, Any] = None,
        return_type: str = "any",
        category: str = "general",
        tags: List[str] = None
    ) -> Tool:
        """
        注册新工具
        """
        # 自动从函数签名提取参数
        if parameters is None:
            parameters = self._extract_parameters(function)

        tool = Tool(
            name=name,
            description=description,
            function=function,
            parameters=parameters or {},
            return_type=return_type,
            category=category,
            tags=tags or []
        )

        self.tools[name] = tool
        print(f"[ToolRegistry] 注册工具: {name} ({category})")
        return tool

    def unregister(self, name: str) -> bool:
        """注销工具"""
        if name in self.tools:
            del self.tools[name]
            print(f"[ToolRegistry] 注销工具: {name}")
            return True
        return False

    def _extract_parameters(self, function: Callable) -> Dict[str, Any]:
        """从函数签名提取参数定义"""
        sig = inspect.signature(function)
        params = {}

        for name, param in sig.parameters.items():
            param_info = {
                "type": "any",
                "required": param.default == inspect.Parameter.empty
            }

            # 尝试获取类型注解
            if param.annotation != inspect.Parameter.empty:
                if hasattr(param.annotation, '__name__'):
                    param_info["type"] = param.annotation.__name__

            if param.default != inspect.Parameter.empty:
                param_info["default"] = param.default

            params[name] = param_info

        return {
            "type": "object",
            "properties": params,
            "required": [n for n, p in params.items() if p.get("required")]
        }

    def get_tool(self, name: str) -> Optional[Tool]:
        """获取工具"""
        return self.tools.get(name)

    def list_tools(self, category: str = None) -> List[Tool]:
        """列出工具"""
        tools = list(self.tools.values())
        if category:
            tools = [t for t in tools if t.category == category]
        return tools

    async def select_tools(
        self,
        task_description: str,
        max_tools: int = 3
    ) -> List[Tool]:
        """
        智能选择适合任务的工具
        """
        # 构建工具列表
        tools_desc = "\n".join([
            f"{i+1}. {tool.name}: {tool.description} (类别: {tool.category}, 成功率: {tool.success_rate:.2f})"
            for i, tool in enumerate(self.tools.values())
        ])

        prompt = f"""请从以下工具中选择最适合完成该任务的工具。

任务描述:
{task_description}

可用工具:
{tools_desc}

请分析任务需求，选择最多 {max_tools} 个最相关的工具。

输出格式 (JSON):
{{
    "selected_tools": ["tool_name_1", "tool_name_2"],
    "reasoning": "选择这些工具的原因",
    "execution_order": ["tool_name_1", "tool_name_2"]  // 建议的执行顺序
}}"""

        messages = [
            SystemMessage(content="你是一个工具选择专家，擅长根据任务需求选择最合适的工具。"),
            HumanMessage(content=prompt)
        ]

        response = await self.llm.ainvoke(messages)

        try:
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            result = json.loads(content)
            selected_names = result.get("selected_tools", [])

            # 返回工具对象
            return [self.tools[name] for name in selected_names if name in self.tools]
        except Exception as e:
            print(f"[ToolRegistry] 工具选择失败: {e}")
            # 返回按成功率排序的前几个工具
            return sorted(
                self.tools.values(),
                key=lambda t: t.success_rate,
                reverse=True
            )[:max_tools]

    async def execute_tool(
        self,
        tool_name: str,
        **kwargs
    ) -> ToolExecutionResult:
        """
        执行工具
        """
        tool = self.tools.get(tool_name)
        if not tool:
            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                result=None,
                execution_time=0,
                error_message=f"工具不存在: {tool_name}"
            )

        import time
        start_time = time.time()

        try:
            # 执行工具函数
            if asyncio.iscoroutinefunction(tool.function):
                result = await tool.function(**kwargs)
            else:
                result = tool.function(**kwargs)

            execution_time = time.time() - start_time

            # 更新工具统计
            tool.usage_count += 1
            tool.avg_execution_time = (
                (tool.avg_execution_time * (tool.usage_count - 1) + execution_time)
                / tool.usage_count
            )

            execution_result = ToolExecutionResult(
                tool_name=tool_name,
                success=True,
                result=result,
                execution_time=execution_time
            )

            self.execution_history.append(execution_result)
            return execution_result

        except Exception as e:
            execution_time = time.time() - start_time

            # 更新成功率
            tool.success_rate = (
                (tool.success_rate * tool.usage_count) / (tool.usage_count + 1)
            )

            execution_result = ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                result=None,
                execution_time=execution_time,
                error_message=str(e)
            )

            self.execution_history.append(execution_result)
            return execution_result

    def get_tool_stats(self) -> Dict[str, Any]:
        """获取工具统计"""
        if not self.tools:
            return {"total_tools": 0}

        return {
            "total_tools": len(self.tools),
            "by_category": self._group_by_category(),
            "top_tools": sorted(
                [t.to_dict() for t in self.tools.values()],
                key=lambda x: x["success_rate"],
                reverse=True
            )[:10],
            "execution_stats": self._get_execution_stats()
        }

    def _group_by_category(self) -> Dict[str, int]:
        """按类别分组"""
        categories = {}
        for tool in self.tools.values():
            categories[tool.category] = categories.get(tool.category, 0) + 1
        return categories

    def _get_execution_stats(self) -> Dict[str, Any]:
        """获取执行统计"""
        if not self.execution_history:
            return {}

        total = len(self.execution_history)
        success = sum(1 for r in self.execution_history if r.success)
        avg_time = sum(r.execution_time for r in self.execution_history) / total

        return {
            "total_executions": total,
            "success_rate": success / total,
            "avg_execution_time": avg_time,
            "recent_executions": [
                {
                    "tool": r.tool_name,
                    "success": r.success,
                    "time": r.execution_time
                }
                for r in self.execution_history[-10:]
            ]
        }


# 全局工具注册中心
registry = ToolRegistry()


# 装饰器形式的工具注册
def tool(description: str, category: str = "general", tags: List[str] = None):
    """
    工具装饰器

    用法:
    @tool(description="查询数据库", category="db")
    async def query_db(sql: str) -> Dict:
        ...
    """
    def decorator(func: Callable):
        registry.register(
            name=func.__name__,
            description=description,
            function=func,
            category=category,
            tags=tags or []
        )
        return func
    return decorator
