"""
动态公交行驶里程数据处理者 Agent
基于 LLM 生成 SQL + 自动修正 + 规则化报告生成
"""

import json
from typing import Any, Dict, List

from agents.base import BaseAgent
from agents.intent_parser import intent_parser
from agents.intent_to_sql import intent_to_sql
from graph.state import Message, AgentRole
from tools.mcp_oracle import oracle_mcp
from validation.result_validator import validate_and_fix_result, generate_key_findings_from_stats


class PassengerProcessorAgent(BaseAgent):
    """
    动态公交行驶里程数据处理者 Agent
    使用 LLM 生成 SQL，SQL 失败时自动修正，分析结果由规则生成
    """

    def __init__(self):
        super().__init__(
            name="passenger_processor",
            role=AgentRole.PASSENGER_PROCESSOR,
            system_prompt="""你是数据分析团队的动态公交行驶里程数据处理者（Dynamic Bus Mileage Processor）。

## 你的职责
1. **车辆行驶里程分析**：总里程、载客里程、空驶里程、调度里程
2. **运营效率分析**：车辆利用率、运营时长、等待时长
3. **司机工作时长分析**：司机工作时长、等待时长、有效工作时长
4. **区域运营分析**：各片区车辆运营情况、里程分布
5. **对比分析**：环比上周、同比去年同期等

## 可用数据表
- **JS_DAY_DY_OP**: 动态公交日结算表 ⭐ 主要表
  - JS_DATE: 结算日期
  - REGION_ID/REGION_NAME: 区域ID/名称
  - BUS_ID/BUS_NO: 车辆ID/自编号
  - BUS_CARD_ID: 车牌号
  - DRIVER_ID/DRIVER_NAME/JOB_NUMBER: 司机信息
  - ROUTE_ID/ROUTE_NAME: 线路ID/名称

  **时间字段（分钟）**:
  - INOUT_MIN: 进出总时长
  - WAIT_MIN: 等待时长
  - DISPATCH_START_MIN: 调度开始阶段时长
  - CARRY_MIN: 载客时长
  - PAUSE_MIN: 暂停时长
  - DISPATCH_END_MIN: 调度结束阶段时长

  **里程字段（公里）**:
  - MILEAGE: 总里程 ⭐
  - CARRY_MILEAGE: 载客里程 ⭐
  - INOUT_MILEAGE: 进出里程
  - DISPATCH_START_MILEAGE: 调度开始阶段里程
  - DISPATCH_END_MILEAGE: 调度结束阶段里程
  - DISPATCH_OTHER_MILEAGE: 其他调度里程
  - PAUSE_MILAGE: 暂停阶段里程

  **其他字段**:
  - REVENUE: 收入金额
  - REVENUE2: 收入金额2

## 数据使用说明
- 数据粒度：每行代表一辆车在某一天在一个片区的运营结算记录
- 日期查询格式：JS_DATE >= TO_DATE('2026-03-01', 'YYYY-MM-DD') AND JS_DATE < TO_DATE('2026-03-06', 'YYYY-MM-DD')
- 里程单位：公里
- 时间单位：分钟

## 分析要求
1. 根据用户需求生成合适的 SQL 查询
2. 如需对比分析（环比/同比），查询多个时间段的数据
3. 分析结果包含：统计数据、关键发现、结论建议
4. 输出格式为 JSON

## 通信规则
- **你只与 task_manager 通信**
- 使用 SendMessage 向 task_manager 返回结果
- 如需查询数据库，使用 MCP oracle-database 工具""",
            can_talk_to=["task_manager"],
            max_retries=3,
            use_mcp=True
        )

    async def process_message(self, message: Message) -> Any:
        """处理动态公交行驶里程分析任务"""
        task_description = message.content
        # 获取 metadata 中的 analysis（含 date_range）
        self._last_analysis = message.metadata.get('analysis', {}) if message.metadata else {}

        print(f"[PassengerProcessor] 处理任务: {task_description[:80]}...")

        try:
            # 步骤1: 数据发现
            print(f"[PassengerProcessor] 步骤1: 数据发现...")
            discovery = await self.discover_data(
                task_description,
                available_tables=['JS_DAY_DY_OP']
            )

            if "error" in discovery:
                return {"error": f"数据发现失败: {discovery['error']}", "key_findings": [], "analysis": {}}

            # 步骤2: 生成 SQL（带自动修正）
            print(f"[PassengerProcessor] 步骤2: 生成 SQL...")
            table_schemas = discovery.get("table_schemas", {})

            # 优先尝试模板/意图解析（无需LLM，零延迟）
            query_result = await self._generate_sql_fast_path(task_description, table_schemas)

            # 如果快速路径失败，回退到LLM生成
            if not query_result or not query_result.get("success"):
                print(f"[PassengerProcessor] 快速路径失败，回退到LLM生成...")
                query_result = await self._generate_and_execute_sql_with_correction(task_description, table_schemas)

            if not query_result.get("success"):
                error_msg = query_result.get('error', '未知错误')
                return {"error": f"SQL 查询失败: {error_msg}", "key_findings": [], "analysis": {}}

            # 步骤3: 生成报告
            print(f"[PassengerProcessor] 步骤3: 生成报告...")
            data = query_result.get("query_result", {})
            rows = data.get("rows", [])
            columns = data.get("columns", [])

            # 判断是否是分组明细查询（有 DRIVER_NAME/BUS_NO 等分组列）
            is_grouped = self._is_grouped_query(columns)

            if is_grouped and len(rows) > 0:
                # 分组明细：展示表格 + 简单统计
                result = await self._build_grouped_result(task_description, query_result, rows, columns, discovery, table_schemas)
            else:
                # 聚合概览：预计算统计 + 规则化报告
                result = await self._build_aggregated_result(task_description, query_result, rows, columns, discovery, table_schemas)

            # 验证和修正结果
            raw_data = {"rows": rows, "columns": columns}
            fixed_result = validate_and_fix_result("passenger", result, raw_data)

            if fixed_result.get("_validation_errors"):
                print(f"[PassengerProcessor] 验证错误已修复: {fixed_result['_validation_errors']}")

            # 如果没有关键发现，从统计数据生成
            if not fixed_result.get("key_findings"):
                fixed_result["key_findings"] = generate_key_findings_from_stats("passenger", fixed_result.get("statistics", {}))

            return fixed_result

        except Exception as e:
            print(f"[PassengerProcessor] 处理失败: {e}")
            import traceback
            traceback.print_exc()
            return {"error": str(e), "key_findings": [f"处理异常: {str(e)}"], "analysis": {"error": str(e)}}

    async def _generate_sql_fast_path(self, task_description: str, table_schemas: Dict[str, Any]) -> Dict[str, Any]:
        """快速路径：模板匹配 + 意图解析（无需LLM）。"""
        from agents.query_templates import match_template, apply_template
        from agents.intent_parser import intent_parser
        from agents.intent_to_sql import intent_to_sql
        from tools.mcp_oracle import oracle_mcp

        original_task = task_description
        if '[对话上下文]' in task_description:
            original_task = task_description.split('[对话上下文]')[0].strip()

        # 1. 尝试模板匹配（最可靠）
        template = match_template(original_task)
        if template:
            date_condition = self._extract_date_condition(original_task)
            # 如果没有日期但有analysis中的date_range，使用它
            if date_condition == "1=1":
                analysis = getattr(self, '_last_analysis', {})
                dr = analysis.get('date_range', {})
                if dr.get('start') and dr.get('end'):
                    date_condition = f"JS_DATE >= TO_DATE('{dr['start']}', 'YYYY-MM-DD') AND JS_DATE < TO_DATE('{dr['end']}', 'YYYY-MM-DD')"

            context = {
                "mileage_table": "JS_DAY_DY_OP",
                "date_condition": date_condition
            }
            sql = apply_template(template, context)
            print(f"[PassengerProcessor] 模板匹配成功: {template.name}")
            print(f"[PassengerProcessor] 模板SQL: {sql[:150]}...")

            result = await oracle_mcp.query(sql, max_rows=1000)
            if result.get("success"):
                return {
                    "success": True,
                    "sql": sql,
                    "query_result": result,
                    "corrections": 0,
                    "source": "template"
                }
            # 模板SQL执行失败，继续尝试意图解析

        # 2. 尝试意图解析（无需LLM）
        intent = intent_parser.parse(original_task)
        sql = intent_to_sql.convert(intent, table_name="JS_DAY_DY_OP")
        print(f"[PassengerProcessor] 意图解析SQL: {sql[:150]}...")

        result = await oracle_mcp.query(sql, max_rows=1000)
        if result.get("success"):
            return {
                "success": True,
                "sql": sql,
                "query_result": result,
                "corrections": 0,
                "source": "intent"
            }

        # 快速路径都失败了
        return {"success": False, "error": "模板和意图解析均失败", "source": "fast_path_failed"}

    def _extract_date_condition(self, query: str) -> str:
        """从查询中提取日期条件。"""
        import re
        from datetime import datetime, timedelta

        # 格式1: "3月1日-3月5日" 或 "3月1日-5日" 或 "3月1-5日" 或 "3月1-3月5日"（无年份）
        pattern = r'(\d{1,2})月(\d{1,2})日?[\-~到至](\d{1,2}月)?(\d{1,2})日'
        match = re.search(pattern, query)
        if match:
            month1, day1, month2, day2 = match.groups()
            month2_val = (month2.rstrip('月') if month2 else None) or month1
            year = datetime.now().year
            start_dt = datetime(year, int(month1), int(day1))
            end_dt = datetime(year, int(month2_val), int(day2)) + timedelta(days=1)
            start = f"TO_DATE('{start_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
            end = f"TO_DATE('{end_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
            return f"JS_DATE >= {start} AND JS_DATE < {end}"

        # 格式2: "2026年3月1日-15日"（单年份）
        pattern2 = r'(\d{4})年(\d{1,2})月(\d{1,2})日?[\-~到至](\d{1,2}月)?(\d{1,2})日'
        match2 = re.search(pattern2, query)
        if match2:
            year, month1, day1, month2, day2 = match2.groups()
            month2_val = (month2.rstrip('月') if month2 else None) or month1
            start_dt = datetime(int(year), int(month1), int(day1))
            end_dt = datetime(int(year), int(month2_val), int(day2)) + timedelta(days=1)
            start = f"TO_DATE('{start_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
            end = f"TO_DATE('{end_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
            return f"JS_DATE >= {start} AND JS_DATE < {end}"

        # 格式3: "2026年3月10日-2026年3月15日"（双年份）
        pattern3 = r'(\d{4})年(\d{1,2})月(\d{1,2})日?[\-~到至](\d{4})年(\d{1,2})月(\d{1,2})日'
        match3 = re.search(pattern3, query)
        if match3:
            y1, m1, d1, y2, m2, d2 = match3.groups()
            start_dt = datetime(int(y1), int(m1), int(d1))
            end_dt = datetime(int(y2), int(m2), int(d2)) + timedelta(days=1)
            start = f"TO_DATE('{start_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
            end = f"TO_DATE('{end_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
            return f"JS_DATE >= {start} AND JS_DATE < {end}"

        # 相对时间
        if '昨天' in query:
            return "TRUNC(JS_DATE) = TRUNC(SYSDATE - 1)"
        elif '今天' in query:
            return "TRUNC(JS_DATE) = TRUNC(SYSDATE)"
        elif '上周' in query:
            return "JS_DATE >= TRUNC(SYSDATE, 'IW') - 7 AND JS_DATE < TRUNC(SYSDATE, 'IW')"

        return "1=1"

    async def _generate_and_execute_sql_with_correction(self, task_description: str, table_schemas: Dict[str, Any]) -> Dict[str, Any]:
        """生成 SQL 并执行，失败时自动修正重试（LLM路径）。"""
        # 提取原始查询（排除对话上下文）
        original_task = task_description
        if '[对话上下文]' in task_description:
            original_task = task_description.split('[对话上下文]')[0].strip()

        # 构建 schema 描述（只取前10列，减少prompt长度）
        schema_desc = []
        for table_name, schema in table_schemas.items():
            columns = schema.get("columns", [])
            # 优先取关键列 + 前10列
            key_cols = ['JS_DATE', 'MILEAGE', 'CARRY_MILEAGE', 'BUS_ID', 'BUS_NO',
                        'DRIVER_ID', 'DRIVER_NAME', 'ROUTE_ID', 'ROUTE_NAME',
                        'INOUT_MIN', 'WAIT_MIN', 'CARRY_MIN']
            selected = []
            seen = set()
            # 先加关键列
            for c in columns:
                col_name = c.get('COLUMN_NAME', '')
                if col_name.upper() in key_cols and col_name not in seen:
                    selected.append(c)
                    seen.add(col_name)
            # 再补充其他列到10个
            for c in columns:
                col_name = c.get('COLUMN_NAME', '')
                if col_name not in seen and len(selected) < 10:
                    selected.append(c)
                    seen.add(col_name)

            col_desc = [f"  - {c.get('COLUMN_NAME')}: {c.get('DATA_TYPE')} {c.get('COMMENTS', '')}" for c in selected]
            schema_desc.append(f"表 {table_name}:\n" + "\n".join(col_desc))

        # 检查是否有日期范围在 analysis 中但未在查询中
        date_range_hint = ""
        analysis = getattr(self, '_last_analysis', {})
        if analysis and analysis.get('date_range'):
            dr = analysis['date_range']
            if dr.get('start') and dr.get('end'):
                has_date = any(kw in original_task for kw in ['月', '日', 'TO_DATE', 'SYSDATE'])
                if not has_date:
                    date_range_hint = f"\n注意：用户查询未指定日期，应使用上一轮日期范围 {dr['start']} 至 {dr['end']}。"

        # 根据查询意图推断需要的列
        query_lower = original_task.lower()
        is_avg_query = '平均' in query_lower or '日均' in query_lower
        is_total_query = '总' in query_lower or '累计' in query_lower or '一共' in query_lower

        select_requirement = ""
        if is_avg_query:
            select_requirement = """
SELECT列要求（必须遵守）:
- 用户问"平均/日均"，SQL必须同时返回:
  1. SUM(MILEAGE)/COUNT(DISTINCT TRUNC(JS_DATE)) AS AVG_DAILY_MILEAGE（日均里程）
  2. COUNT(DISTINCT TRUNC(JS_DATE)) AS DAYS_COUNT（天数，用于验证）
  3. SUM(MILEAGE) AS TOTAL_MILEAGE（总里程，参考值）
- 绝不允许只返回SUM(MILEAGE)而不返回AVG_DAILY_MILEAGE"""
        elif is_total_query:
            select_requirement = """
SELECT列要求:
- 用户问"总里程"，SQL必须返回: SUM(MILEAGE) AS TOTAL_MILEAGE
- 可选返回: SUM(CARRY_MILEAGE) AS TOTAL_CARRY_MILEAGE, COUNT(DISTINCT BUS_ID) AS UNIQUE_BUSES"""

        # ===== 优先：LLM 意图解析（输出 JSON，不生成 SQL） =====
        from agents.intent_parser import llm_intent_parser, intent_parser, intent_to_sql, DataSource

        intent = await llm_intent_parser.parse(original_task, timeout=20.0)
        if intent:
            intent.data_source = DataSource.MILEAGE
            # 如果查询没有日期但 analysis 有日期范围，注入
            if not intent.date_range and date_range_hint:
                dr = analysis.get('date_range', {})
                if dr.get('start') and dr.get('end'):
                    intent.date_range = {"start": dr['start'], "end": dr['end']}
            sql = intent_to_sql.convert(intent)
            print(f"[PassengerProcessor] LLM意图解析成功: {sql[:150]}...")

            result = await oracle_mcp.query(sql, max_rows=1000)
            if result.get("success"):
                return {
                    "success": True,
                    "sql": sql,
                    "query_result": result,
                    "corrections": 0,
                    "source": "llm_intent"
                }
            print(f"[PassengerProcessor] 意图SQL执行失败，回退到规则解析")

        # ===== 回退：规则化意图解析 =====
        intent = intent_parser.parse(original_task)
        intent.data_source = DataSource.MILEAGE
        if not intent.date_range and date_range_hint:
            dr = analysis.get('date_range', {})
            if dr.get('start') and dr.get('end'):
                intent.date_range = {"start": dr['start'], "end": dr['end']}
        sql = intent_to_sql.convert(intent)
        print(f"[PassengerProcessor] 规则意图解析: {sql[:150]}...")

        result = await oracle_mcp.query(sql, max_rows=1000)
        if result.get("success"):
            return {
                "success": True,
                "sql": sql,
                "query_result": result,
                "corrections": 0,
                "source": "rule_intent"
            }

        # ===== 最后回退：LLM 直接生成 SQL =====
        print(f"[PassengerProcessor] 意图解析SQL执行失败，回退到LLM直接生成SQL")

        from schema.column_registry import SchemaContext
        schema_ctx = None
        for tname, schema in table_schemas.items():
            schema_ctx = SchemaContext(tname, schema.get("columns", []))
            break

        schema_text = schema_ctx.format_for_prompt() if schema_ctx else chr(10).join(schema_desc)
        aggregation_rules = schema_ctx.format_aggregation_rules("MILEAGE") if schema_ctx else ""
        constraints = schema_ctx.format_constraints() if schema_ctx else ""

        sql_generation_prompt = f"""根据任务和表结构生成Oracle SQL。

任务: {original_task}{date_range_hint}

{schema_text}

{aggregation_rules}

{constraints}

输出JSON: {{"sql":"...","reasoning":"..."}}"""

        try:
            llm_response = await self.invoke_llm(sql_generation_prompt, timeout=30.0)
            sql = self._extract_sql_from_response(llm_response)
            if not sql:
                return {"error": "无法从 LLM 响应中提取 SQL", "success": False}
            print(f"[PassengerProcessor] LLM直接生成SQL: {sql[:150]}...")
        except Exception as e:
            print(f"[PassengerProcessor] SQL 生成失败: {e}")
            return {"error": str(e), "success": False}

        # 执行 SQL（带自动修正）
        return await self.execute_sql_with_correction(
            sql=sql,
            task_description=original_task,
            table_schemas=table_schemas,
            max_corrections=3
        )

    def _extract_sql_from_response(self, llm_response: str) -> str:
        """从 LLM 响应中提取 SQL"""
        try:
            # 尝试直接 JSON 解析
            sql_info = json.loads(llm_response.strip())
            return sql_info.get("sql", "")
        except json.JSONDecodeError:
            pass

        # 提取第一个 JSON 块
        json_start = llm_response.find('{')
        if json_start >= 0:
            brace_count = 0
            json_end = json_start
            for i, char in enumerate(llm_response[json_start:]):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        json_end = json_start + i + 1
                        break
            try:
                sql_info = json.loads(llm_response[json_start:json_end])
                return sql_info.get("sql", "")
            except json.JSONDecodeError:
                pass

        # 尝试提取 ```sql ... ``` 代码块
        if "```sql" in llm_response:
            sql = llm_response.split("```sql")[1].split("```")[0].strip()
            return sql
        elif "```" in llm_response:
            sql = llm_response.split("```")[1].split("```")[0].strip()
            if sql.upper().startswith("SELECT"):
                return sql

        # 最后尝试：如果响应本身就是 SQL
        cleaned = llm_response.strip()
        if cleaned.upper().startswith("SELECT"):
            return cleaned

        return ""

    def _is_grouped_query(self, columns: List[str]) -> bool:
        """判断返回结果是否是分组明细（含分组维度列）"""
        group_cols = {'DRIVER_NAME', 'DRIVER_ID', 'BUS_NO', 'BUS_ID', 'ROUTE_NAME', 'REGION_NAME'}
        col_set = {c.upper() for c in columns}
        return bool(group_cols & col_set)

    async def _build_grouped_result(self, task_description, query_result, rows, columns, discovery, table_schemas):
        """构建分组明细结果（支持总里程、日均里程、单车平均等多指标）。"""
        col_upper = {c.upper(): c for c in columns}

        # ---- 识别各类里程列 ----
        # 总里程列（求和得到总计）
        total_mileage_col = next((col_upper[k] for k in [
            'TOTAL_MILEAGE', 'SUM_MILEAGE', 'MILEAGE'
        ] if k in col_upper), None)

        # 日均里程列（求平均得到整体日均）
        avg_daily_col = next((col_upper[k] for k in [
            'AVG_DAILY_MILEAGE', 'AVG_MILEAGE'
        ] if k in col_upper), None)

        # 单车平均列（兼容 LLM 生成的 AVG_DAILY_MILEAGE 列名）
        avg_per_bus_col = next((col_upper[k] for k in [
            'AVG_PER_BUS_MILEAGE', 'AVG_MILEAGE_PER_BUS'
        ] if k in col_upper), None)

        # 载客里程列
        carry_col = next((col_upper[k] for k in [
            'CARRY_MILEAGE', 'TOTAL_CARRY_MILEAGE', 'SUM_CARRY_MILEAGE'
        ] if k in col_upper), None)

        # 天数列
        days_col = next((col_upper[k] for k in [
            'DAYS_COUNT', 'DAY_COUNT', 'UNIQUE_DAYS'
        ] if k in col_upper), None)

        # 车辆数列
        bus_count_col = next((col_upper[k] for k in [
            'BUS_COUNT', 'UNIQUE_BUSES', 'BUS_NUM'
        ] if k in col_upper), None)

        # ---- 判断查询意图（用于决定展示优先级） ----
        task_lower = task_description.lower()
        intent_is_avg_daily = '平均' in task_lower or '日均' in task_lower
        intent_is_avg_per_bus = '单车' in task_lower or '每辆车' in task_lower
        intent_is_total = '总' in task_lower or '累计' in task_lower

        # ---- 计算统计值（根据列类型选择正确的聚合方式） ----
        total_mileage = 0
        avg_daily_mileage = 0
        avg_per_bus_mileage = 0
        carry_mileage = 0
        total_days = 0
        total_buses = 0

        # 1. 总里程
        if total_mileage_col:
            total_mileage = sum(float(r.get(total_mileage_col, 0) or 0) for r in rows)
        elif avg_daily_col and days_col:
            total_mileage = sum(float(r.get(avg_daily_col, 0) or 0) * float(r.get(days_col, 1) or 1) for r in rows)

        # 2. 日均里程（优先从SQL返回的列取，否则用总里程/天数推算）
        if avg_daily_col:
            # SQL已返回日均列，直接用
            avg_daily_mileage = sum(float(r.get(avg_daily_col, 0) or 0) for r in rows) / len(rows) if rows else 0
        elif total_mileage_col and days_col:
            # 有总里程和天数，推算日均 = 总里程 / 天数
            avg_daily_mileage = sum(
                float(r.get(total_mileage_col, 0) or 0) / max(float(r.get(days_col, 1) or 1), 1)
                for r in rows
            ) / len(rows) if rows else 0
        elif total_mileage_col:
            # 只有总里程，用全局天数推算（从JS_DATE去重）
            date_cols_in_result = [c for c in columns if c.upper() in ['JS_DATE', 'OPERATE_DATE']]
            if date_cols_in_result:
                unique_days = len(set(str(r.get(date_cols_in_result[0]))[:10] for r in rows if r.get(date_cols_in_result[0])))
            else:
                unique_days = len(rows)  # 按分组数估算
            avg_daily_mileage = total_mileage / max(unique_days, 1) / len(rows) if rows else 0

        # 3. 单车平均
        # 当查询意图是"每辆车平均"时，AVG_DAILY_MILEAGE 实际上是每车的日均里程
        # 需要兼容 LLM 生成的列名（AVG_DAILY_MILEAGE vs AVG_PER_BUS_MILEAGE）
        effective_per_bus_col = avg_per_bus_col
        if not effective_per_bus_col and intent_is_avg_per_bus and avg_daily_col:
            # 查询意图是"每辆车平均"，LLM 生成的 AVG_DAILY_MILEAGE 实际是每车的日均
            effective_per_bus_col = avg_daily_col

        if effective_per_bus_col:
            avg_per_bus_mileage = sum(float(r.get(effective_per_bus_col, 0) or 0) for r in rows) / len(rows) if rows else 0
        elif total_mileage_col and bus_count_col:
            avg_per_bus_mileage = sum(
                float(r.get(total_mileage_col, 0) or 0) / max(float(r.get(bus_count_col, 1) or 1), 1)
                for r in rows
            ) / len(rows) if rows else 0

        # 4. 载客里程
        if carry_col:
            carry_mileage = sum(float(r.get(carry_col, 0) or 0) for r in rows)

        # 5. 天数和车辆数
        if days_col:
            total_days = sum(float(r.get(days_col, 0) or 0) for r in rows)
        if bus_count_col:
            total_buses = sum(float(r.get(bus_count_col, 0) or 0) for r in rows)

        # ---- 格式化展示数据（添加推算列） ----
        display_rows = rows
        formatted = []
        for r in display_rows:
            row = {}
            for k, v in r.items():
                if isinstance(v, float):
                    row[k] = round(v, 2)
                else:
                    row[k] = v

            # 如果查询意图是日均，但SQL没有返回日均列，用总里程/天数推算
            if intent_is_avg_daily and 'AVG_DAILY_MILEAGE' not in col_upper:
                if total_mileage_col and days_col:
                    daily = float(r.get(total_mileage_col, 0) or 0) / max(float(r.get(days_col, 1) or 1), 1)
                    row['AVG_DAILY_MILEAGE'] = round(daily, 2)
                elif total_mileage_col and total_days > 0:
                    daily = float(r.get(total_mileage_col, 0) or 0) / max(total_days / len(rows), 1)
                    row['AVG_DAILY_MILEAGE'] = round(daily, 2)

            # 如果查询意图是单车平均，但SQL没有返回，推算
            # 注意：LLM 可能用 AVG_DAILY_MILEAGE 代替 AVG_PER_BUS_MILEAGE
            if intent_is_avg_per_bus and 'AVG_PER_BUS_MILEAGE' not in col_upper and 'AVG_DAILY_MILEAGE' not in col_upper:
                if total_mileage_col and bus_count_col:
                    per_bus = float(r.get(total_mileage_col, 0) or 0) / max(float(r.get(bus_count_col, 1) or 1), 1)
                    row['AVG_PER_BUS_MILEAGE'] = round(per_bus, 2)

            formatted.append(row)

        # ---- 找出分组列名 ----
        group_col = next((col_upper[k] for k in [
            'DRIVER_NAME', 'DRIVER_ID', 'BUS_NO', 'BUS_ID',
            'ROUTE_NAME', 'REGION_NAME'
        ] if k in col_upper), None)

        # ---- 构建统计数据（包含所有可用指标） ----
        statistics = {"record_count": len(rows)}

        if total_mileage > 0:
            statistics["total_mileage_km"] = round(total_mileage, 2)
        if avg_daily_mileage > 0:
            statistics["avg_daily_mileage_km"] = round(avg_daily_mileage, 2)
        if avg_per_bus_mileage > 0:
            statistics["avg_per_bus_mileage_km"] = round(avg_per_bus_mileage, 2)
        if carry_mileage > 0:
            statistics["carry_mileage_km"] = round(carry_mileage, 2)
            if total_mileage > 0:
                statistics["empty_mileage_km"] = round(total_mileage - carry_mileage, 2)
                statistics["mileage_utilization_rate"] = round(carry_mileage / total_mileage * 100, 2)
        if total_days > 0:
            statistics["total_days"] = round(total_days, 1)
        if total_buses > 0:
            statistics["total_buses"] = int(total_buses)

        # ---- 使用 LLM 生成关键发现 ----
        valid_rows = []
        if group_col:
            valid_rows = [r for r in rows if r.get(group_col) is not None and str(r.get(group_col)).strip()]

        # 为 key_findings 选择最合适的数值列（根据查询意图优先）
        if intent_is_avg_daily and avg_daily_col:
            primary_value_col = avg_daily_col
        elif intent_is_avg_per_bus and effective_per_bus_col:
            primary_value_col = effective_per_bus_col
        elif intent_is_total and total_mileage_col:
            primary_value_col = total_mileage_col
        else:
            primary_value_col = avg_daily_col or total_mileage_col or avg_per_bus_col or None

        data_summary = {
            "domain": "passenger",
            "query_type": "grouped",
            "group_by": group_col,
            "record_count": len(rows),
            "statistics": statistics,
            "top_data": [
                {group_col: r.get(group_col), primary_value_col: float(r.get(primary_value_col, 0) or 0)}
                for r in sorted(valid_rows, key=lambda r: float(r.get(primary_value_col, 0) or 0), reverse=True)[:5]
            ] if valid_rows and primary_value_col else None
        }
        findings = await self.generate_key_findings(data_summary, task_description)

        # ---- 生成有针对性的结论 ----
        conclusions = self._generate_grouped_conclusions_v2(
            group_col, valid_rows,
            total_mileage_col, avg_daily_col, avg_per_bus_col,
            total_mileage, avg_daily_mileage, carry_mileage
        )

        from schema.column_registry import ColumnRegistry as CR
        all_cols = list(formatted[0].keys()) if formatted else columns
        column_metadata = CR.get_metadata_dict(all_cols)

        return {
            "task": task_description,
            "data_discovery": {
                "relevant_tables": discovery.get("relevant_tables", []),
                "schemas": {k: {"column_count": len(v.get("columns", []))} for k, v in table_schemas.items()}
            },
            "sql_used": query_result.get("sql", ""),
            "query_summary": {
                "total_rows": len(rows),
                "columns": columns
            },
            "grouped_data": {
                "group_by": group_col,
                "total_records": len(rows),
                "display_records": formatted,
                "column_metadata": column_metadata
            },
            "column_metadata": column_metadata,
            "statistics": statistics,
            "key_findings": findings,
            "conclusions": conclusions,
            "analysis": {
                "analysis_summary": self._generate_analysis_summary(
                    group_col, len(rows), statistics, intent_is_avg_daily, intent_is_avg_per_bus
                ),
            },
            "corrections": query_result.get("corrections", 0)
        }

    async def _build_aggregated_result(self, task_description, query_result, rows, columns, discovery, table_schemas):
        """构建聚合概览结果"""
        precomputed = self._precompute_stats(rows, columns)
        print(f"[PassengerProcessor] 预计算统计: {precomputed}")

        final_statistics = {
            "total_mileage_km": precomputed.get("total_mileage", 0),
            "carry_mileage_km": precomputed.get("carry_mileage", 0),
            "empty_mileage_km": precomputed.get("empty_mileage", 0),
            "mileage_utilization_rate": precomputed.get("utilization_rate", 0),
            "unique_buses": precomputed.get("unique_buses", 0),
            "unique_days": precomputed.get("unique_days", 0)
        }

        data_summary = {
            "domain": "passenger",
            "query_type": "aggregated",
            "record_count": len(rows),
            "statistics": final_statistics
        }
        findings = await self.generate_key_findings(data_summary, task_description)
        # KeyFindingsGenerator内部已处理降级，无需重复

        from schema.column_registry import ColumnRegistry as CR
        column_metadata = CR.get_metadata_dict(list(final_statistics.keys()))

        return {
            "task": task_description,
            "data_discovery": {
                "relevant_tables": discovery.get("relevant_tables", []),
                "schemas": {k: {"column_count": len(v.get("columns", []))} for k, v in table_schemas.items()}
            },
            "sql_used": query_result.get("sql", ""),
            "query_summary": {
                "total_rows": len(rows),
                "columns": columns
            },
            "column_metadata": column_metadata,
            "statistics": final_statistics,
            "key_findings": findings,
            "conclusions": self._generate_conclusions(final_statistics),
            "analysis": {
                "analysis_summary": self._generate_summary(final_statistics),
            },
            "corrections": query_result.get("corrections", 0)
        }

    def _precompute_stats(self, rows: List[Dict], columns: List[str]) -> Dict[str, Any]:
        """预计算统计数据"""
        if not rows:
            return {}

        stats = {}

        # 查找匹配的列名（大小写不敏感）
        col_upper = {c.upper(): c for c in columns}

        mileage_col = next((col_upper[k] for k in ['MILEAGE', 'TOTAL_MILEAGE', 'AVG_MILEAGE', '总里程', '总里程_公里'] if k in col_upper), None)
        carry_mileage_col = next((col_upper[k] for k in ['CARRY_MILEAGE', 'TOTAL_CARRY_MILEAGE', '载客里程', '载客里程_公里', 'CARRY_MILEAGE_KM'] if k in col_upper), None)

        if mileage_col:
            try:
                total = sum(float(r.get(mileage_col, 0) or 0) for r in rows)
                stats['total_mileage'] = round(total, 2)
            except Exception as e:
                print(f"[PassengerProcessor] 预计算总里程失败: {e}")

        if carry_mileage_col:
            try:
                total = sum(float(r.get(carry_mileage_col, 0) or 0) for r in rows)
                stats['carry_mileage'] = round(total, 2)
            except Exception as e:
                print(f"[PassengerProcessor] 预计算载客里程失败: {e}")

        if 'total_mileage' in stats and 'carry_mileage' in stats:
            stats['empty_mileage'] = round(stats['total_mileage'] - stats['carry_mileage'], 2)

        if 'carry_mileage' in stats and 'total_mileage' in stats and stats['total_mileage'] > 0:
            stats['utilization_rate'] = round(stats['carry_mileage'] / stats['total_mileage'] * 100, 2)

        # 车辆数：优先使用 SQL 预聚合的 UNIQUE_BUSES，否则从 BUS_ID 去重
        bus_agg_col = col_upper.get('UNIQUE_BUSES')
        bus_col = next((col_upper[k] for k in ['BUS_NO', 'BUS_ID', '运营车辆数', '车辆编号', '车辆自编号'] if k in col_upper), None)
        if bus_agg_col:
            try:
                # 按天分组时每行有当天车辆数，取最大值作为期间运营车辆数近似值
                stats['unique_buses'] = max(int(float(r.get(bus_agg_col, 0) or 0)) for r in rows)
            except:
                pass
        elif bus_col:
            try:
                stats['unique_buses'] = len(set(r.get(bus_col) for r in rows if r.get(bus_col)))
            except:
                pass

        # 天数：优先使用 SQL 预聚合的 UNIQUE_DAYS，否则从日期列去重
        days_agg_col = col_upper.get('UNIQUE_DAYS')
        date_col = next((col_upper[k] for k in ['JS_DATE', 'OPERATE_DATE', '日期', 'ORDER_DATE'] if k in col_upper), None)
        if days_agg_col:
            try:
                stats['unique_days'] = max(int(float(r.get(days_agg_col, 0) or 0)) for r in rows)
            except:
                pass
        elif date_col:
            try:
                stats['unique_days'] = len(set(str(r.get(date_col))[:10] for r in rows if r.get(date_col)))
            except:
                pass

        return stats

    def _generate_summary(self, stats: Dict[str, Any]) -> str:
        """生成分析摘要"""
        total = stats.get("total_mileage_km", 0)
        carry = stats.get("carry_mileage_km", 0)
        empty = stats.get("empty_mileage_km", 0) or (total - carry if total > 0 else 0)
        rate = stats.get("mileage_utilization_rate", 0)
        buses = stats.get("unique_buses", 0)
        days = stats.get("unique_days", 0)

        parts = [f"总里程 {total:.1f} 公里"]
        if buses > 0:
            parts.insert(0, f"共 {buses} 辆车参与运营")
        if days > 0:
            parts.insert(0 if buses == 0 else 1, f"覆盖 {days} 天")
        if carry > 0:
            parts.append(f"载客里程 {carry:.1f} 公里")
        if empty > 0:
            parts.append(f"空驶里程 {empty:.1f} 公里")
        if rate > 0:
            parts.append(f"里程利用率 {rate:.1f}%")

        return "，".join(parts) + "。"

    def _generate_grouped_conclusions(self, group_col, valid_rows, mileage_col, total_mileage, carry_mileage):
        """旧版结论生成（保留兼容）。"""
        return self._generate_grouped_conclusions_v2(
            group_col, valid_rows, mileage_col, None, None,
            total_mileage, 0, carry_mileage
        )

    def _generate_grouped_conclusions_v2(
        self, group_col, valid_rows,
        total_mileage_col, avg_daily_col, avg_per_bus_col,
        total_mileage, avg_daily_mileage, carry_mileage
    ) -> str:
        """为分组查询生成有针对性的结论（支持多指标）。"""
        if not valid_rows or not group_col:
            return f"共查询到 {len(valid_rows)} 条分组记录，详见数据表格。"

        conclusions = []

        # 选择主指标列用于找最高/最低（优先使用日均列，其次总里程）
        primary_col = avg_daily_col or total_mileage_col or avg_per_bus_col

        # 分组维度中文映射
        from schema.column_registry import ColumnRegistry
        group_display = ColumnRegistry.get_label(group_col)

        # 1. 整体概况
        if avg_daily_col:
            avg_val = sum(float(r.get(avg_daily_col, 0) or 0) for r in valid_rows) / len(valid_rows)
            conclusions.append(f"共 {len(valid_rows)} 个{group_display}，日均里程平均 {avg_val:.2f} km/天")
        elif avg_per_bus_col:
            avg_val = sum(float(r.get(avg_per_bus_col, 0) or 0) for r in valid_rows) / len(valid_rows)
            conclusions.append(f"共 {len(valid_rows)} 个{group_display}，单车平均里程 {avg_val:.2f} km/辆")
        elif total_mileage_col:
            avg_val = total_mileage / len(valid_rows) if valid_rows else 0
            conclusions.append(f"共 {len(valid_rows)} 个{group_display}，总里程平均 {avg_val:.2f} km")

        # 2. 找出最高/最低（使用主指标）
        if primary_col:
            max_row = max(valid_rows, key=lambda r: float(r.get(primary_col, 0) or 0))
            min_row = min(valid_rows, key=lambda r: float(r.get(primary_col, 0) or 0))
            max_val = float(max_row.get(primary_col, 0) or 0)
            min_val = float(min_row.get(primary_col, 0) or 0)

            if avg_daily_col:
                conclusions.append(
                    f"日均里程最高为 {max_row.get(group_col)}（{max_val:.2f} km/天），"
                    f"最低为 {min_row.get(group_col)}（{min_val:.2f} km/天）"
                )
            elif avg_per_bus_col:
                conclusions.append(
                    f"单车平均里程最高为 {max_row.get(group_col)}（{max_val:.2f} km/辆），"
                    f"最低为 {min_row.get(group_col)}（{min_val:.2f} km/辆）"
                )
            else:
                conclusions.append(
                    f"总里程最高为 {max_row.get(group_col)}（{max_val:.2f} km），"
                    f"最低为 {min_row.get(group_col)}（{min_val:.2f} km）"
                )

        # 3. 里程利用率
        if carry_mileage > 0 and total_mileage > 0:
            rate = carry_mileage / total_mileage * 100
            if rate < 40:
                conclusions.append(f"整体里程利用率仅 {rate:.1f}%，空驶比例高，建议优化调度减少空驶里程")
            elif rate > 60:
                conclusions.append(f"整体里程利用率 {rate:.1f}%，运营效率良好")

        return "；".join(conclusions)

    def _generate_analysis_summary(self, group_col, record_count, statistics, intent_is_avg_daily, intent_is_avg_per_bus) -> str:
        """根据查询意图生成分析摘要。"""
        from schema.column_registry import ColumnRegistry
        group_display = ColumnRegistry.get_label(group_col) if group_col else "维度"

        parts = [f"按{group_display}分组统计完成，共{record_count}条记录"]

        if intent_is_avg_daily and statistics.get("avg_daily_mileage_km"):
            parts.append(f"，日均里程平均 {statistics['avg_daily_mileage_km']:.2f} km/天")
        elif intent_is_avg_per_bus and statistics.get("avg_per_bus_mileage_km"):
            parts.append(f"，单车平均里程 {statistics['avg_per_bus_mileage_km']:.2f} km/辆")
        elif statistics.get("total_mileage_km"):
            parts.append(f"，总里程 {statistics['total_mileage_km']:.2f} km")

        return "，".join(parts)

    def _generate_conclusions(self, stats: Dict[str, Any]) -> str:
        """生成结论和建议"""
        rate = stats.get("mileage_utilization_rate", 0)
        conclusions = []

        if rate < 40:
            conclusions.append("里程利用率偏低，建议优化调度策略减少空驶")
        elif rate < 60:
            conclusions.append("里程利用率处于中等水平，有提升空间")
        else:
            conclusions.append("里程利用率良好")

        empty = stats.get("empty_mileage_km", 0)
        if empty > 0:
            conclusions.append(f"空驶里程 {empty:.1f} 公里，建议优化接单调度减少空驶")

        conclusions.append("建议持续监控里程利用率趋势，结合订单密度优化车辆部署")

        return "；".join(conclusions)
