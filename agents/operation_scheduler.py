"""
营运调度数据处理者 Agent
基于 LLM 生成 SQL + 自动修正 + 规则化报告生成
"""

import json
from typing import Any, Dict, List

from agents.base import BaseAgent
from graph.state import Message, AgentRole
from tools.mcp_oracle import oracle_mcp
from validation.result_validator import validate_and_fix_result, generate_key_findings_from_stats


class OperationSchedulerAgent(BaseAgent):
    """
    营运调度数据处理者 Agent
    职责：车辆调度、班次优化、营运效率、车辆利用率
    """

    def __init__(self):
        super().__init__(
            name="operation_scheduler",
            role=AgentRole.OPERATION_SCHEDULER,
            system_prompt="""你是数据分析团队的营运调度数据处理者（Operation Scheduler）。

## 你的职责
1. **车辆调度分析**：车辆利用率、运行效率、准点率
2. **班次优化**：发车间隔、班次密度、满载率分析
3. **营运效率**：线路效率、周转时间、运营成本
4. **车辆管理**：车辆状态、维修计划、能耗分析
5. **调度建议**：基于客流的班次调整建议

## 可用数据表
- **DY_ORDER_INFO**: 动态公交订单表 ⭐ 动态公交
  - ORDER_NUM: 订单编号
  - CREATE_DATE: 订单创建时间
  - REGION_NAME: 区域名称
  - BUS_SELF_ID: 车辆自编号
  - BUS_NO: 车牌号
  - STATUS_NAME: 订单状态（'已完成'、'已取消'等）
  - PAY_AMOUNT: 支付金额
  - accept_date: 派单时间
  - start_date: 车辆到达起点时间
  - end_date: 车辆到达终点时间
  - start_station_name: 上车站点名称
  - end_station_name: 下车站点名称
  - PASSENGER: 乘车人数
  - ORDER_PAY_TYPE_NAME: 支付途径
  - cancel_type: 取消来源
  - CANCEL_REASON: 取消订单原因

## 通信规则
- **你只与 task_manager 通信**，不直接与用户通信
- 使用 SendMessage 向 task_manager 返回结果

## 输出要求
1. 提供调度优化建议
2. 包含效率指标分析
3. 给出具体的改进方案
4. 使用中文输出""",
            can_talk_to=["task_manager"],
            max_retries=3,
            use_mcp=True
        )

    async def process_message(self, message: Message) -> Any:
        """处理营运调度任务"""
        task_description = message.content
        self._last_analysis = message.metadata.get('analysis', {}) if message.metadata else {}

        print(f"[OperationScheduler] 处理任务: {task_description[:80]}...")

        try:
            # 步骤1: 数据发现
            print(f"[OperationScheduler] 步骤1: 数据发现...")
            discovery = await self.discover_data(
                task_description,
                available_tables=['DY_ORDER_INFO']
            )

            if "error" in discovery:
                return {"error": f"数据发现失败: {discovery['error']}", "key_findings": [], "analysis": {}}

            # 步骤2: 生成 SQL（优先快速路径，失败时回退LLM）
            print(f"[OperationScheduler] 步骤2: 生成 SQL...")
            table_schemas = discovery.get("table_schemas", {})

            # 优先尝试模板匹配（无需LLM，零延迟）
            query_result = await self._generate_sql_fast_path(task_description, table_schemas)

            # 如果快速路径失败，回退到LLM生成
            if not query_result or not query_result.get("success"):
                print(f"[OperationScheduler] 快速路径失败，回退到LLM生成...")
                query_result = await self._generate_and_execute_sql_with_correction(task_description, table_schemas)

            if not query_result.get("success"):
                error_msg = query_result.get('error', '未知错误')
                return {"error": f"SQL 查询失败: {error_msg}", "key_findings": [], "analysis": {}}

            # 步骤3: 预计算统计 + 规则化生成报告
            print(f"[OperationScheduler] 步骤3: 生成报告...")
            data = query_result.get("query_result", {})
            rows = data.get("rows", [])
            columns = data.get("columns", [])

            # 判断是否是分组明细查询
            is_grouped = self._is_grouped_query(columns)

            if is_grouped and len(rows) > 0:
                result = await self._build_grouped_result(task_description, query_result, rows, columns, discovery, table_schemas)
            else:
                result = await self._build_aggregated_result(task_description, query_result, rows, columns, discovery, table_schemas)

            # 验证和修正结果
            raw_data = {"rows": rows, "columns": columns}
            fixed_result = validate_and_fix_result("operation", result, raw_data)

            if fixed_result.get("_validation_errors"):
                print(f"[OperationScheduler] 验证错误已修复: {fixed_result['_validation_errors']}")

            if not fixed_result.get("key_findings"):
                fixed_result["key_findings"] = generate_key_findings_from_stats("operation", fixed_result.get("statistics", {}))

            return fixed_result

        except Exception as e:
            print(f"[OperationScheduler] 处理失败: {e}")
            import traceback
            traceback.print_exc()
            return {"error": str(e), "key_findings": [f"处理异常: {str(e)}"], "analysis": {"error": str(e)}}

    async def _generate_sql_fast_path(self, task_description: str, table_schemas: Dict[str, Any]) -> Dict[str, Any]:
        """快速路径：模板匹配（无需LLM，零延迟）。"""
        from agents.query_templates import match_template, apply_template
        from tools.mcp_oracle import oracle_mcp

        original_task = task_description
        if '[对话上下文]' in task_description:
            original_task = task_description.split('[对话上下文]')[0].strip()

        # 尝试模板匹配
        template = match_template(original_task)
        if template:
            date_condition = self._extract_date_condition(original_task)
            if date_condition == "1=1":
                analysis = getattr(self, '_last_analysis', {})
                dr = analysis.get('date_range', {})
                if dr.get('start') and dr.get('end'):
                    date_condition = f"CREATE_DATE >= TO_DATE('{dr['start']}', 'YYYY-MM-DD') AND CREATE_DATE < TO_DATE('{dr['end']}', 'YYYY-MM-DD')"

            context = {
                "order_table": "DY_ORDER_INFO",
                "date_condition": date_condition
            }
            sql = apply_template(template, context)
            print(f"[OperationScheduler] 模板匹配成功: {template.name}")
            print(f"[OperationScheduler] 模板SQL: {sql[:150]}...")

            result = await oracle_mcp.query(sql, max_rows=1000)
            if result.get("success"):
                return {
                    "success": True,
                    "sql": sql,
                    "query_result": result,
                    "corrections": 0,
                    "source": "template"
                }

        # Stage 2: 规则化意图解析（无需 LLM）
        try:
            from agents.intent_parser import intent_parser, DataSource, AggregationType
            from agents.intent_to_sql import intent_to_sql

            _VALID_ORDER_METRICS = {"ORDER_COUNT", "COMPLETED_ORDER", "CANCELLED_ORDER", "PASSENGER", "PAY_AMOUNT"}

            intent = intent_parser.parse(original_task)
            intent.data_source = DataSource.ORDER
            if not any(m.upper() in _VALID_ORDER_METRICS for m in intent.metrics):
                intent.metrics = ["ORDER_COUNT"]
                intent.aggregation = AggregationType.COUNT
            sql = intent_to_sql.convert(intent)
            print(f"[OperationScheduler] 意图解析SQL: {sql[:150]}...")

            result = await oracle_mcp.query(sql, max_rows=1000)
            if result.get("success"):
                return {
                    "success": True,
                    "sql": sql,
                    "query_result": result,
                    "corrections": 0,
                    "source": "intent"
                }
        except Exception as e:
            print(f"[OperationScheduler] 意图解析失败: {e}")

        return {"success": False, "error": "快速路径全部失败", "source": "fast_path_failed"}

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
            return f"CREATE_DATE >= {start} AND CREATE_DATE < {end}"

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
            return f"CREATE_DATE >= {start} AND CREATE_DATE < {end}"

        # 格式3: "2026年3月10日-2026年3月15日"（双年份）
        pattern3 = r'(\d{4})年(\d{1,2})月(\d{1,2})日?[\-~到至](\d{4})年(\d{1,2})月(\d{1,2})日'
        match3 = re.search(pattern3, query)
        if match3:
            y1, m1, d1, y2, m2, d2 = match3.groups()
            start_dt = datetime(int(y1), int(m1), int(d1))
            end_dt = datetime(int(y2), int(m2), int(d2)) + timedelta(days=1)
            start = f"TO_DATE('{start_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
            end = f"TO_DATE('{end_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
            return f"CREATE_DATE >= {start} AND CREATE_DATE < {end}"

        # 相对时间
        if '昨天' in query:
            return "TRUNC(CREATE_DATE) = TRUNC(SYSDATE - 1)"
        elif '今天' in query:
            return "TRUNC(CREATE_DATE) = TRUNC(SYSDATE)"

        return "1=1"

    async def _generate_and_execute_sql_with_correction(self, task_description: str, table_schemas: Dict[str, Any]) -> Dict[str, Any]:
        """生成 SQL 并执行，失败时自动修正重试"""
        original_task = task_description
        if '[对话上下文]' in task_description:
            original_task = task_description.split('[对话上下文]')[0].strip()

        # 日期范围提示
        date_range_hint = ""
        analysis = getattr(self, '_last_analysis', {})
        if analysis and analysis.get('date_range'):
            dr = analysis['date_range']
            if dr.get('start') and dr.get('end'):
                has_date = any(kw in original_task for kw in ['月', '日', 'TO_DATE', 'SYSDATE'])
                if not has_date:
                    date_range_hint = f"\n注意：用户查询未指定日期，应使用上一轮日期范围 {dr['start']} 至 {dr['end']}。"

        # ===== 优先：LLM 意图解析（输出 JSON，不生成 SQL） =====
        from agents.intent_parser import llm_intent_parser, intent_parser, intent_to_sql, DataSource

        # 订单域合法指标
        _VALID_ORDER_METRICS = {"ORDER_COUNT", "COMPLETED_ORDER", "CANCELLED_ORDER", "PASSENGER", "PAY_AMOUNT"}

        def _fix_order_intent(intent):
            """确保意图的 metrics 与 ORDER 数据源匹配"""
            intent.data_source = DataSource.ORDER
            if not any(m.upper() in _VALID_ORDER_METRICS for m in intent.metrics):
                intent.metrics = ["ORDER_COUNT"]
                from agents.intent_parser import AggregationType
                intent.aggregation = AggregationType.COUNT

        intent = await llm_intent_parser.parse(original_task, timeout=20.0)
        if intent:
            _fix_order_intent(intent)
            if not intent.date_range and date_range_hint:
                dr = analysis.get('date_range', {})
                if dr.get('start') and dr.get('end'):
                    intent.date_range = {"start": dr['start'], "end": dr['end']}
            sql = intent_to_sql.convert(intent)
            print(f"[OperationScheduler] LLM意图解析成功: {sql[:150]}...")

            from tools.mcp_oracle import oracle_mcp
            result = await oracle_mcp.query(sql, max_rows=1000)
            if result.get("success"):
                return {
                    "success": True,
                    "sql": sql,
                    "query_result": result,
                    "corrections": 0,
                    "source": "llm_intent"
                }
            print(f"[OperationScheduler] 意图SQL执行失败，回退到规则解析")

        # ===== 回退：规则化意图解析 =====
        intent = intent_parser.parse(original_task)
        _fix_order_intent(intent)
        if not intent.date_range and date_range_hint:
            dr = analysis.get('date_range', {})
            if dr.get('start') and dr.get('end'):
                intent.date_range = {"start": dr['start'], "end": dr['end']}
        sql = intent_to_sql.convert(intent)
        print(f"[OperationScheduler] 规则意图解析: {sql[:150]}...")

        from tools.mcp_oracle import oracle_mcp
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
        print(f"[OperationScheduler] 意图解析SQL执行失败，回退到LLM直接生成SQL")

        from schema.column_registry import SchemaContext
        schema_ctx = None
        schema_desc = []
        for tname, schema in table_schemas.items():
            schema_ctx = SchemaContext(tname, schema.get("columns", []))
            columns = schema.get("columns", [])
            col_desc = [f"  - {c.get('COLUMN_NAME')}: {c.get('DATA_TYPE')} {c.get('COMMENTS', '')}" for c in columns]
            schema_desc.append(f"表 {tname}:\n" + "\n".join(col_desc))

        schema_text = schema_ctx.format_for_prompt() if schema_ctx else chr(10).join(schema_desc)
        aggregation_rules = schema_ctx.format_aggregation_rules("ORDER") if schema_ctx else ""
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
            print(f"[OperationScheduler] LLM直接生成SQL: {sql[:150]}...")
        except Exception as e:
            print(f"[OperationScheduler] SQL 生成失败: {e}")
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
            sql_info = json.loads(llm_response.strip())
            return sql_info.get("sql", "")
        except json.JSONDecodeError:
            pass

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

        if "```sql" in llm_response:
            return llm_response.split("```sql")[1].split("```")[0].strip()

        cleaned = llm_response.strip()
        if cleaned.upper().startswith("SELECT"):
            return cleaned

        return ""

    def _is_grouped_query(self, columns: List[str]) -> bool:
        """判断返回结果是否是分组明细（含分组维度列）"""
        group_cols = {'DRIVER_NAME', 'DRIVER_ID', 'BUS_NO', 'BUS_ID', 'ROUTE_NAME', 'REGION_NAME',
                      'STATUS_NAME', 'START_STATION_NAME', 'END_STATION_NAME', 'STATION_NAME'}
        col_set = {c.upper() for c in columns}
        return bool(group_cols & col_set)

    async def _build_grouped_result(self, task_description, query_result, rows, columns, discovery, table_schemas):
        """构建分组明细结果"""
        col_upper = {c.upper(): c for c in columns}

        # 查找各类指标列
        order_col = next((col_upper[k] for k in ['TOTAL_ORDERS', 'ORDER_COUNT', 'FINISH_ORDER_COUNT'] if k in col_upper), None)
        completed_col = next((col_upper[k] for k in ['COMPLETED_ORDERS', 'TOTAL_FINISH_ORDERS'] if k in col_upper), None)
        cancelled_col = next((col_upper[k] for k in ['CANCELLED_ORDERS', 'TOTAL_CANCEL_ORDERS'] if k in col_upper), None)
        passenger_col = next((col_upper[k] for k in ['TOTAL_PASSENGERS', 'PASSENGER', 'TOTAL_PASSENGER'] if k in col_upper), None)

        # 计算汇总统计
        total_orders = sum(float(r.get(order_col, 0) or 0) for r in rows) if order_col else 0
        completed_orders = sum(float(r.get(completed_col, 0) or 0) for r in rows) if completed_col else 0
        cancelled_orders = sum(float(r.get(cancelled_col, 0) or 0) for r in rows) if cancelled_col else 0
        total_passengers = sum(float(r.get(passenger_col, 0) or 0) for r in rows) if passenger_col else 0

        display_rows = rows
        formatted = []
        for r in display_rows:
            row = {}
            for k, v in r.items():
                if isinstance(v, float):
                    row[k] = round(v, 2)
                else:
                    row[k] = v
            formatted.append(row)

        group_col = next((col_upper[k] for k in ['DRIVER_NAME', 'DRIVER_ID', 'BUS_NO', 'BUS_ID', 'ROUTE_NAME',
                                                   'REGION_NAME', 'STATUS_NAME', 'START_STATION_NAME',
                                                   'END_STATION_NAME', 'STATION_NAME'] if k in col_upper), None)

        # 计算排名数据
        valid_rows = []
        if group_col and order_col:
            valid_rows = [r for r in rows if r.get(group_col) is not None and str(r.get(group_col)).strip()]
            if valid_rows:
                top_rows = sorted(valid_rows, key=lambda r: float(r.get(order_col, 0) or 0), reverse=True)[:5]

        # 构建统计
        statistics = {
            "total_orders": round(total_orders, 0),
            "record_count": len(rows)
        }
        if completed_orders > 0:
            statistics["completed_orders"] = round(completed_orders, 0)
        if cancelled_orders > 0:
            statistics["cancelled_orders"] = round(cancelled_orders, 0)
        if total_passengers > 0:
            statistics["total_passengers"] = round(total_passengers, 0)
        if total_orders > 0 and completed_orders > 0:
            statistics["completion_rate"] = round(completed_orders / total_orders * 100, 2)

        # 排名数据（排序后取前5）
        sorted_top = sorted(valid_rows, key=lambda r: float(r.get(order_col, 0) or 0), reverse=True)[:5] if valid_rows and order_col else []

        data_summary = {
            "domain": "operation",
            "query_type": "grouped",
            "group_by": group_col,
            "record_count": len(rows),
            "statistics": statistics,
            "top_data": [{group_col: r.get(group_col), order_col: float(r.get(order_col, 0) or 0)} for r in sorted_top] if sorted_top and order_col else None
        }
        findings = await self.generate_key_findings(data_summary, task_description)

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
            "conclusions": self._generate_grouped_conclusions(group_col, valid_rows, order_col, total_orders),
            "analysis": {
                "analysis_summary": f"按 {group_col} 分组统计完成，共 {len(rows)} 条记录",
            },
            "corrections": query_result.get("corrections", 0)
        }

    async def _build_aggregated_result(self, task_description, query_result, rows, columns, discovery, table_schemas):
        """构建聚合概览结果"""
        precomputed = self._precompute_order_stats(rows, columns)
        print(f"[OperationScheduler] 预计算统计: {precomputed}")

        final_statistics = {
            "total_orders": precomputed.get("total_orders", 0),
            "completed_orders": precomputed.get("completed_orders", 0),
            "cancelled_orders": precomputed.get("cancelled_orders", 0),
            "completion_rate": precomputed.get("completion_rate", 0),
            "total_passengers": precomputed.get("total_passengers", 0),
            "avg_passengers_per_order": precomputed.get("avg_passengers_per_order", 0)
        }

        data_summary = {
            "domain": "operation",
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

    def _precompute_order_stats(self, rows: List[Dict], columns: List[str]) -> Dict[str, Any]:
        """预计算订单统计数据"""
        if not rows:
            return {}

        stats = {}
        column_aliases = {
            'total_orders': ['TOTAL_ORDERS', '订单数', 'ORDER_COUNT', '总订单数', 'FINISH_ORDER_COUNT', '完成订单数'],
            'completed_orders': ['COMPLETED_ORDERS', 'TOTAL_FINISH_ORDERS', '完成订单数', 'FINISHED_ORDERS', '已完成订单数', 'FINISH_ORDER_COUNT'],
            'cancelled_orders': ['CANCELLED_ORDERS', 'TOTAL_CANCEL_ORDERS', '取消订单数', 'CANCEL_ORDERS', '已取消订单数', 'CANCEL_ORDER_COUNT'],
            'passengers': ['TOTAL_PASSENGERS', 'PASSENGER', '乘客数', '总乘客数', 'PASSENGERS', 'TOTAL_PASSENGER']
        }

        columns_upper_map = {col.upper(): col for col in columns}

        matched_columns = {}
        for stat_name, aliases in column_aliases.items():
            for alias in aliases:
                if alias.upper() in columns_upper_map:
                    matched_columns[stat_name] = columns_upper_map[alias.upper()]
                    break

        if 'total_orders' in matched_columns:
            try:
                stats['total_orders'] = sum(float(r.get(matched_columns['total_orders'], 0) or 0) for r in rows)
            except:
                pass

        if 'completed_orders' in matched_columns:
            try:
                stats['completed_orders'] = sum(float(r.get(matched_columns['completed_orders'], 0) or 0) for r in rows)
            except:
                pass

        if 'cancelled_orders' in matched_columns:
            try:
                stats['cancelled_orders'] = sum(float(r.get(matched_columns['cancelled_orders'], 0) or 0) for r in rows)
            except:
                pass

        if 'passengers' in matched_columns:
            try:
                stats['total_passengers'] = sum(float(r.get(matched_columns['passengers'], 0) or 0) for r in rows)
            except:
                pass

        if 'completed_orders' in stats and 'total_orders' in stats and stats['total_orders'] > 0:
            stats['completion_rate'] = round(stats['completed_orders'] / stats['total_orders'] * 100, 2)

        if 'total_passengers' in stats and 'total_orders' in stats and stats['total_orders'] > 0:
            stats['avg_passengers_per_order'] = round(stats['total_passengers'] / stats['total_orders'], 2)

        return stats

    def _generate_summary(self, stats: Dict[str, Any]) -> str:
        """生成分析摘要"""
        total = stats.get("total_orders", 0)
        completed = stats.get("completed_orders", 0)
        cancelled = stats.get("cancelled_orders", 0)
        passengers = stats.get("total_passengers", 0)
        rate = stats.get("completion_rate", 0)

        return (f"共 {total:.0f} 单订单，完成 {completed:.0f} 单，取消 {cancelled:.0f} 单，"
                f"完成率 {rate:.1f}%，服务乘客 {passengers:.0f} 人次。")

    def _generate_grouped_conclusions(self, group_col, valid_rows, order_col, total_orders):
        """为分组查询生成有针对性的结论"""
        if not valid_rows or not group_col or not order_col:
            return f"共查询到 {len(valid_rows)} 条分组记录，详见数据表格。"

        conclusions = []
        avg_orders = total_orders / len(valid_rows) if valid_rows else 0
        conclusions.append(f"共 {len(valid_rows)} 个{group_col}，平均每人/车完成 {avg_orders:.0f} 单")

        max_row = max(valid_rows, key=lambda r: float(r.get(order_col, 0) or 0))
        min_row = min(valid_rows, key=lambda r: float(r.get(order_col, 0) or 0))
        max_val = float(max_row.get(order_col, 0) or 0)
        min_val = float(min_row.get(order_col, 0) or 0)

        if max_val > avg_orders * 2:
            conclusions.append(f"{max_row.get(group_col)} 订单量显著高于均值（{max_val:.0f} 单），表现突出")
        if min_val < avg_orders * 0.3 and min_val > 0:
            conclusions.append(f"{min_row.get(group_col)} 订单量偏低（{min_val:.0f} 单），建议关注")
        if min_val == 0:
            conclusions.append(f"{min_row.get(group_col)} 订单量为 0，可能存在未排班或数据缺失")

        return "；".join(conclusions)

    def _generate_conclusions(self, stats: Dict[str, Any]) -> str:
        """生成结论和建议"""
        rate = stats.get("completion_rate", 0)
        conclusions = []

        if rate < 60:
            conclusions.append("订单完成率偏低，需分析取消原因并优化调度")
        elif rate < 80:
            conclusions.append("订单完成率中等，有优化空间")
        else:
            conclusions.append("订单完成率良好")

        avg_p = stats.get("avg_passengers_per_order", 0)
        if avg_p < 2:
            conclusions.append("平均每单乘客数偏低，可考虑拼单优化")

        conclusions.append("建议持续监控订单完成率趋势，优化派单策略")

        return "；".join(conclusions)
