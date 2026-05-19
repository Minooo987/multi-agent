"""
Agent 基类
支持 LLM 驱动的数据分析 + SQL 自动修正
"""

from abc import ABC, abstractmethod
from typing import Any, List, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime
import asyncio
import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from graph.state import Message, AgentRole
from tools.message_bus import message_bus
from config.settings import settings

# Import memory manager
try:
    from memory.enhanced_memory import memory_manager
    MEMORY_AVAILABLE = True
except ImportError:
    memory_manager = None
    MEMORY_AVAILABLE = False

# Import tracing manager
try:
    from monitoring.tracing import tracer
    TRACING_AVAILABLE = True
except ImportError:
    tracer = None
    TRACING_AVAILABLE = False


class BaseAgent(ABC):
    """
    Agent 基类
    支持传统 LLM 驱动模式 + SQL 自动修正
    """

    def __init__(
        self,
        name: str,
        role: AgentRole,
        system_prompt: str,
        can_talk_to: List[str] = None,
        max_retries: int = 3,
        use_mcp: bool = False,
        enable_react: bool = False,  # 保留参数兼容，但不再使用
        max_react_steps: int = 10,
        enable_reflection: bool = False  # 保留参数兼容，但不再使用
    ):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.can_talk_to = can_talk_to or []
        self.max_retries = max_retries
        self.use_mcp = use_mcp
        self.retry_count = 0

        # 初始化 LLM (OpenAI 兼容协议)
        self.llm = ChatOpenAI(
            model=settings.model_name,
            openai_api_base=settings.model_base_url,
            openai_api_key=settings.model_api_key,
            temperature=0.7,
            max_tokens=4096,
            streaming=True
        )

        # 订阅消息总线
        message_bus.subscribe(name, self._on_message)
        print(f"[Agent:{name}] 已初始化")

    async def _on_message(self, message: Message):
        """收到消息时的回调"""
        print(f"[Agent:{self.name}] 收到来自 {message.from_agent} 的消息")

        # 验证通信规则
        if message.from_agent not in self.can_talk_to and message.from_agent != "user":
            await self._send_error(
                message.from_agent,
                f"根据通信规则，{self.name} 只与 {self.can_talk_to} 通信"
            )
            return

        # 处理消息
        try:
            # 获取对话上下文
            conversation_history = self.get_conversation_history(message.from_agent, limit=5)

            # 构建带上下文的消息
            context_message = self._build_context_message(message, conversation_history)

            # 使用传统模式处理
            result = await self.process_message(context_message)

            if result:
                await self._send_result(message.from_agent, result)
        except Exception as e:
            await self._handle_error(message, e)

    def _build_context_message(self, message: Message, history: List[Dict]) -> Message:
        """构建带上下文的消息"""
        if not history:
            return message

        context_content = message.content
        context_content += "\n\n[上下文信息]\n"
        context_content += f"这是当前对话的第 {len(history) + 1} 轮。\n"
        if history:
            context_content += f"之前的对话主题：{history[-1].get('content', '')[:50] if history else '无'}\n"

        return Message(
            from_agent=message.from_agent,
            to_agent=message.to_agent,
            content=context_content,
            message_type=message.message_type,
            metadata={
                **message.metadata,
                'conversation_history': history,
                'turn_count': len(history) + 1
            }
        )

    @abstractmethod
    async def process_message(self, message: Message) -> Any:
        """子类实现具体处理逻辑"""
        pass

    async def invoke_llm(
        self,
        content: str,
        context: List[Dict] = None,
        timeout: float = 60.0
    ) -> str:
        """调用 LLM（支持自定义超时）。"""
        print(f"[Agent:{self.name}] 调用LLM, content长度={len(content)}, timeout={timeout}s")

        messages = [SystemMessage(content=self.system_prompt)]

        if context:
            for msg in context:
                messages.append(HumanMessage(content=msg.get("content", "")))

        messages.append(HumanMessage(content=content))

        try:
            response = await asyncio.wait_for(
                self.llm.ainvoke(messages),
                timeout=timeout
            )
            print(f"[Agent:{self.name}] LLM响应接收完成")
            return response.content
        except asyncio.TimeoutError:
            print(f"[Agent:{self.name}] LLM调用超时({timeout}秒)")
            raise RetryableError(f"LLM调用超时({timeout}秒)，请稍后重试")
        except Exception as e:
            print(f"[Agent:{self.name}] LLM调用失败: {e}")
            raise

    async def execute_sql_with_correction(
        self,
        sql: str,
        task_description: str,
        table_schemas: Dict[str, Any],
        max_corrections: int = 3
    ) -> Dict[str, Any]:
        """
        执行 SQL，失败时自动将错误信息反馈给 LLM 修正，最多重试 max_corrections 次。

        Args:
            sql: 初始 SQL
            task_description: 任务描述（供 LLM 理解上下文）
            table_schemas: 表结构信息（供 LLM 参考）
            max_corrections: 最大修正次数

        Returns:
            {
                "success": bool,
                "sql": str,  # 最终执行的 SQL（可能是修正后的）
                "query_result": dict,  # 查询结果
                "corrections": int,  # 修正次数
                "error": str  # 最终错误（如果失败）
            }
        """
        from tools.mcp_oracle import oracle_mcp

        current_sql = sql
        correction_history = []

        # 构建 SchemaContext（用于 SQL 验证和修正 prompt）
        schema_ctx = None
        try:
            from schema.column_registry import SchemaContext
            for tname, schema in table_schemas.items():
                schema_ctx = SchemaContext(tname, schema.get("columns", []))
                break
        except ImportError:
            pass

        for attempt in range(max_corrections + 1):
            # SQL 预验证：规范化别名和列名大小写
            if schema_ctx and attempt == 0:
                current_sql = self._normalize_sql(current_sql, schema_ctx)

            print(f"[{self.name}] SQL 执行 (尝试 {attempt + 1}/{max_corrections + 1}): {current_sql[:120]}...")

            result = await oracle_mcp.query(current_sql, max_rows=1000)

            if result.get("success"):
                print(f"[{self.name}] SQL 执行成功, 返回 {len(result.get('rows', []))} 行")
                return {
                    "success": True,
                    "sql": current_sql,
                    "query_result": result,
                    "corrections": attempt,
                    "correction_history": correction_history
                }

            # SQL 执行失败，记录错误
            error_msg = result.get("error", "未知错误")
            error_code = result.get("error_code", "")
            print(f"[{self.name}] SQL 执行失败 (尝试 {attempt + 1}): {error_msg}")

            # 最后一次尝试失败，不再修正
            if attempt >= max_corrections:
                print(f"[{self.name}] 已达最大修正次数 ({max_corrections})，放弃")
                return {
                    "success": False,
                    "sql": current_sql,
                    "query_result": result,
                    "corrections": attempt,
                    "correction_history": correction_history,
                    "error": f"SQL 执行失败（已尝试 {max_corrections + 1} 次）: {error_msg}"
                }

            # 将错误反馈给 LLM 修正 SQL
            print(f"[{self.name}] 将错误反馈给 LLM 修正 SQL...")
            correction_history.append({
                "attempt": attempt + 1,
                "sql": current_sql,
                "error": error_msg,
                "error_code": error_code
            })

            # 构建 schema 描述（使用 SchemaContext 获取完整信息）
            if schema_ctx:
                schema_text = schema_ctx.format_for_prompt()
                constraints_text = schema_ctx.format_constraints()
            else:
                schema_desc = []
                for table_name, schema in table_schemas.items():
                    columns = schema.get("columns", [])
                    col_desc = [f"  - {c.get('COLUMN_NAME')}: {c.get('DATA_TYPE')} {c.get('COMMENTS', '')}" for c in columns[:25]]
                    schema_desc.append(f"表 {table_name}:\n" + "\n".join(col_desc))
                schema_text = chr(10).join(schema_desc)
                constraints_text = ""

            # 构建修正历史描述
            correction_desc = ""
            if correction_history:
                correction_desc = "\n## 之前的修正尝试\n"
                for c in correction_history:
                    correction_desc += f"- 尝试 {c['attempt']}: SQL={c['sql'][:80]}... → 错误: {c['error']}\n"

            correction_prompt = f"""以下 SQL 查询执行失败，请根据错误信息修正 SQL。

## 原始任务
{task_description[:300]}

## 失败的 SQL
```sql
{current_sql}
```

## 错误信息
{error_msg}

## 错误代码
{error_code or 'N/A'}

## 表结构（完整）
{schema_text}
{correction_desc}

{constraints_text}

## 常见错误修正规则
1. **ORA-00904 (标识符无效)**: 列名不存在，检查表结构中的实际列名，注意大小写
2. **ORA-00942 (表或视图不存在)**: 表名错误，检查可用表名
3. **ORA-00979 (不是 GROUP BY 表达式)**: SELECT 中有非聚合列未在 GROUP BY 中
4. **ORA-01722 (无效数字)**: 类型不匹配，检查是否对字符串列做了数值比较
5. **ORA-00933 (SQL 命令未正确结束)**: 语法错误，检查 Oracle 特有语法
6. **ORA-00936 (缺少表达式)**: 缺少字段或函数参数
7. **ORA-01861 (文字与格式字符串不匹配)**: 日期格式问题，使用 TO_DATE 函数

## 要求
1. 只输出修正后的 SQL，不要输出其他内容
2. 保持原始查询意图不变
3. 使用 Oracle 语法
4. 列名必须大写，禁止中文别名

请直接输出修正后的 SQL 语句（不要输出 JSON，不要输出解释）："""

            try:
                correction_response = await self.invoke_llm(correction_prompt)
                corrected_sql = correction_response.strip()

                # 清理 LLM 响应中可能的 markdown 代码块
                if corrected_sql.startswith("```sql"):
                    corrected_sql = corrected_sql[6:]
                elif corrected_sql.startswith("```"):
                    corrected_sql = corrected_sql[3:]
                if corrected_sql.endswith("```"):
                    corrected_sql = corrected_sql[:-3]
                corrected_sql = corrected_sql.strip()

                # 移除末尾可能的分号（Oracle oracledb 不需要）
                if corrected_sql.endswith(";"):
                    corrected_sql = corrected_sql[:-1].strip()

                if not corrected_sql:
                    print(f"[{self.name}] LLM 返回空 SQL，保持原 SQL")
                    continue

                print(f"[{self.name}] LLM 修正后 SQL: {corrected_sql[:120]}...")
                current_sql = corrected_sql

            except Exception as e:
                print(f"[{self.name}] LLM 修正 SQL 失败: {e}，保持原 SQL 重试")
                continue

        # 不应到达这里，但作为安全兜底
        return {
            "success": False,
            "sql": current_sql,
            "query_result": {},
            "corrections": max_corrections,
            "error": "SQL 修正循环异常退出"
        }

    def _normalize_sql(self, sql: str, schema_ctx) -> str:
        """规范化 SQL：修复列名大小写 + 中文别名转英文"""
        import re
        from schema.column_registry import ColumnRegistry

        # 1. 中文别名 → 英文别名: AS 总里程 → AS TOTAL_MILEAGE
        def replace_chinese_alias(m):
            alias = m.group(1)
            english = ColumnRegistry.key_from_label(alias)
            return f"AS {english}" if english else m.group(0)

        sql = re.sub(r'\bAS\s+([一-鿿][一-鿿\w]*)', replace_chinese_alias, sql, flags=re.IGNORECASE)

        # 2. 列名大小写修复：将小写列名替换为大写
        col_names = schema_ctx.get_column_names_upper()
        if col_names:
            # 找到所有标识符（字母开头，字母数字下划线）
            def fix_case(m):
                token = m.group(0)
                # 跳过 SQL 关键字和函数名
                upper_token = token.upper()
                sql_keywords = {'SELECT', 'FROM', 'WHERE', 'GROUP', 'BY', 'ORDER', 'HAVING',
                                'AND', 'OR', 'NOT', 'IN', 'AS', 'ON', 'JOIN', 'LEFT', 'RIGHT',
                                'INNER', 'OUTER', 'DISTINCT', 'COUNT', 'SUM', 'AVG', 'MAX', 'MIN',
                                'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'TRUNC', 'TO_DATE',
                                'ROUND', 'DESC', 'ASC', 'NULL', 'IS', 'BETWEEN', 'LIKE',
                                'UPPER', 'LOWER', 'NVL', 'COALESCE', 'SYSDATE', 'ROWNUM'}
                if upper_token in sql_keywords:
                    return token
                # 如果在 schema 列名中存在（忽略大小写），返回大写形式
                if upper_token in col_names:
                    return upper_token
                return token

            # 只在非字符串区域替换（简单处理：先去掉字符串字面量）
            sql = re.sub(r'[A-Za-z_][A-Za-z0-9_]*', fix_case, sql)

        return sql

    async def _send_result(self, to_agent: str, result: Any):
        """发送结果"""
        content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        from graph.state import Message as StateMessage
        msg = StateMessage(
            from_agent=self.name,
            to_agent=to_agent,
            content=content,
            message_type="result"
        )
        await message_bus.send_message(msg)

    async def _send_error(self, to_agent: str, error: str):
        """发送错误"""
        from graph.state import Message as StateMessage
        msg = StateMessage(
            from_agent=self.name,
            to_agent=to_agent,
            content=json.dumps({"error": error}, ensure_ascii=False),
            message_type="error"
        )
        await message_bus.send_message(msg)

    async def _handle_error(self, original_message: Message, error: Exception):
        """错误处理和重试 - 使用指数退避"""
        error_msg = f"处理失败: {str(error)}"
        print(f"[Agent:{self.name}] {error_msg}")

        await self._send_error(original_message.from_agent, error_msg)

        # 触发重试 - 使用指数退避
        if self.retry_count < self.max_retries:
            self.retry_count += 1
            delay = min(2 ** (self.retry_count - 1), 60)
            print(f"[Agent:{self.name}] 第 {self.retry_count} 次重试，等待 {delay} 秒...")
            await asyncio.sleep(delay)
            await self._on_message(original_message)
        else:
            print(f"[Agent:{self.name}] 达到最大重试次数，放弃重试")
            self.retry_count = 0

    async def discover_data(
        self,
        task_description: str,
        available_tables: List[str] = None
    ) -> Dict[str, Any]:
        """数据发现"""
        from tools.mcp_oracle import oracle_mcp

        print(f"[{self.name}] 开始数据发现...")

        if not available_tables:
            tables_result = await oracle_mcp.get_tables()
            if tables_result.get("success"):
                available_tables = [t.get("TABLE_NAME") for t in tables_result.get("rows", [])]
            else:
                return {"error": "无法获取表列表"}

        print(f"[{self.name}] 可用表: {len(available_tables)} 个")

        # 如果只提供1-2个表，跳过LLM选择直接返回
        if len(available_tables) <= 2:
            relevant_tables = available_tables
        else:
            table_selection_prompt = f"""根据任务选择相关表。
任务: {task_description[:100]}
可用表: {available_tables}
输出JSON: {{"relevant_tables": ["表名"], "reasoning": "原因"}}"""

            try:
                llm_response = await self.invoke_llm(table_selection_prompt)
                json_start = llm_response.find('{')
                json_end = llm_response.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = llm_response[json_start:json_end]
                    data = json.loads(json_str)
                    relevant_tables = data.get("relevant_tables", [])
                else:
                    relevant_tables = available_tables[:2]
            except Exception as e:
                print(f"[{self.name}] LLM表选择失败: {e}")
                relevant_tables = available_tables[:2]

        print(f"[{self.name}] 相关表: {relevant_tables}")

        # 获取相关表的字段结构
        table_schemas = {}
        for table_name in relevant_tables:
            if table_name in available_tables:
                schema_result = await oracle_mcp.describe_table(table_name)
                if schema_result.get("success"):
                    table_schemas[table_name] = {
                        "columns": schema_result.get("columns", []),
                        "primary_keys": schema_result.get("primary_keys", [])
                    }

        return {
            "task_description": task_description,
            "relevant_tables": relevant_tables,
            "table_schemas": table_schemas,
            "available_tables": available_tables
        }

    async def generate_key_findings(
        self,
        data_summary: Dict[str, Any],
        task_description: str,
        max_findings: int = 5,
        domain: str = None
    ) -> List[str]:
        """
        使用 KeyFindingsGenerator 生成关键发现。

        Args:
            data_summary: 数据摘要（统一格式，包含 domain, query_type, statistics 等）
            task_description: 原始任务描述
            max_findings: 最多生成的发现数量
            domain: 领域类型（已包含在 data_summary 中，保留参数兼容）

        Returns:
            关键发现字符串列表（永不返回空列表）
        """
        from agents.key_findings_generator import generate_key_findings as kfg_generate

        # 确保 data_summary 包含 domain
        if domain and "domain" not in data_summary:
            data_summary["domain"] = domain

        return await kfg_generate(data_summary, task_description)

    def get_conversation_history(self, with_agent: str, limit: int = 10) -> List[Dict]:
        """获取与某 Agent 的对话历史"""
        return message_bus.get_conversation(self.name, with_agent, limit)

    def cleanup(self):
        """清理资源"""
        message_bus.unsubscribe(self.name)
        print(f"[Agent:{self.name}] 已清理")


class RetryableError(Exception):
    """可重试错误"""
    pass
