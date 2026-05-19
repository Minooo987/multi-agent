"""
查询意图解析器
将自然语言查询转换为结构化意图
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict
from enum import Enum
import re
import json
from datetime import datetime, timedelta


class DataSource(Enum):
    MILEAGE = "MILEAGE"   # JS_DAY_DY_OP 表
    ORDER = "ORDER"       # DY_ORDER_INFO 表


class AggregationType(Enum):
    SUM = "sum"
    AVG_DAILY = "avg_daily"      # SUM / COUNT(DISTINCT DATE)
    AVG_PER_BUS = "avg_per_bus"  # SUM / COUNT(DISTINCT BUS)
    AVG_RECORD = "avg_record"    # AVG() - 仅当明确说"每条记录"
    COUNT = "count"


class GroupByDimension(Enum):
    DRIVER = "driver"
    BUS = "bus"
    ROUTE = "route"
    REGION = "region"
    DATE = "date"
    STATION = "station"   # 站点（订单域）
    STATUS = "status"     # 订单状态（订单域）
    NONE = "none"


@dataclass
class QueryIntent:
    """结构化查询意图"""
    query_type: str                     # "mileage", "order", "mixed"（保留兼容）
    data_source: DataSource = DataSource.MILEAGE
    aggregation: AggregationType = AggregationType.SUM
    group_by: List[GroupByDimension] = field(default_factory=lambda: [GroupByDimension.NONE])
    metrics: List[str] = field(default_factory=lambda: ["MILEAGE"])
    date_range: Optional[Dict[str, str]] = None  # {"start": "2026-03-01", "end": "2026-03-06"}
    filters: List[Dict] = field(default_factory=list)
    sort: Optional[Dict] = None         # {"field": "TOTAL_ORDERS", "direction": "DESC"}


class IntentParser:
    """规则化意图解析器（无需 LLM，零延迟）"""

    def parse(self, query: str) -> QueryIntent:
        """解析查询意图"""
        query_type = self._detect_query_type(query)
        data_source = DataSource.ORDER if query_type == "order" else DataSource.MILEAGE

        return QueryIntent(
            query_type=query_type,
            data_source=data_source,
            aggregation=self._detect_aggregation(query),
            group_by=self._detect_group_by(query, data_source),
            metrics=self._detect_metrics(query, data_source),
            date_range=self._extract_date_range(query),
            filters=[]
        )

    def _detect_query_type(self, query: str) -> str:
        order_keywords = ["订单", "order", "完成率", "取消", "客流", "站点", "车站", "乘客"]
        mileage_keywords = ["里程", "行驶", "公里", "mileage", "空驶", "载客"]

        has_order = any(kw in query for kw in order_keywords)
        has_mileage = any(kw in query for kw in mileage_keywords)

        if has_order and not has_mileage:
            return "order"
        elif has_mileage and not has_order:
            return "mileage"
        elif has_order and has_mileage:
            return "mixed"
        return "mileage"

    def _detect_aggregation(self, query: str) -> AggregationType:
        if "日均" in query or "平均每天" in query:
            return AggregationType.AVG_DAILY
        elif "单车" in query or "每辆车" in query:
            return AggregationType.AVG_PER_BUS
        elif "平均" in query and ("司机" in query or "驾驶员" in query):
            return AggregationType.AVG_DAILY
        elif any(kw in query for kw in ["总", "累计", "一共", "总计"]):
            return AggregationType.SUM
        elif "平均" in query:
            return AggregationType.AVG_DAILY
        return AggregationType.SUM

    def _detect_group_by(self, query: str, data_source: DataSource = DataSource.MILEAGE) -> List[GroupByDimension]:
        # 去除日期范围和相对时间词，避免误判
        cleaned = re.sub(r'\d{1,4}年?\d{1,2}月\d{1,2}日', '', query)
        cleaned = re.sub(r'\d{1,2}日', '', cleaned)
        cleaned = re.sub(r'(昨天|今天|前天|明天|后天)', '', cleaned)

        dimensions = []
        if any(kw in cleaned for kw in ["司机", "驾驶员"]):
            dimensions.append(GroupByDimension.DRIVER)
        if any(kw in cleaned for kw in ["车", "车辆", "bus"]):
            dimensions.append(GroupByDimension.BUS)
        if any(kw in cleaned for kw in ["线路", "路线", "route"]):
            dimensions.append(GroupByDimension.ROUTE)
        if any(kw in cleaned for kw in ["区域", "片区"]):
            dimensions.append(GroupByDimension.REGION)
        if any(kw in cleaned for kw in ["天", "日", "每天", "daily"]):
            dimensions.append(GroupByDimension.DATE)

        # 订单域特有维度
        if data_source == DataSource.ORDER:
            if any(kw in cleaned for kw in ["站点", "车站", "上车站点", "下车站点"]):
                dimensions.append(GroupByDimension.STATION)
            if any(kw in cleaned for kw in ["状态"]):
                dimensions.append(GroupByDimension.STATUS)

        return dimensions if dimensions else [GroupByDimension.NONE]

    def _detect_metrics(self, query: str, data_source: DataSource = DataSource.MILEAGE) -> List[str]:
        if data_source == DataSource.ORDER:
            metrics = []
            if any(kw in query for kw in ["订单", "order", "数量"]):
                metrics.append("ORDER_COUNT")
            if any(kw in query for kw in ["完成", "已完成"]):
                metrics.append("COMPLETED_ORDER")
            if any(kw in query for kw in ["取消", "已取消"]):
                metrics.append("CANCELLED_ORDER")
            if any(kw in query for kw in ["乘客", "人数", "客流"]):
                metrics.append("PASSENGER")
            if any(kw in query for kw in ["营收", "金额", "收入"]):
                metrics.append("PAY_AMOUNT")
            return metrics if metrics else ["ORDER_COUNT", "COMPLETED_ORDER", "PASSENGER"]

        # 里程域
        metrics = []
        if any(kw in query for kw in ["里程", "公里", "mileage"]):
            metrics.append("MILEAGE")
            if "CARRY_MILEAGE" not in metrics:
                metrics.append("CARRY_MILEAGE")
        if any(kw in query for kw in ["载客", "carry"]):
            if "CARRY_MILEAGE" not in metrics:
                metrics.append("CARRY_MILEAGE")
        return metrics if metrics else ["MILEAGE"]

    def _extract_date_range(self, query: str) -> Optional[Dict[str, str]]:
        # 格式1: "3月1日-3月5日" 或 "3月1-5日" 或 "3月1-3月5日"（无年份）
        pattern = r'(\d{1,2})月(\d{1,2})日?[\-~到至](\d{1,2}月)?(\d{1,2})日'
        match = re.search(pattern, query)
        if match:
            month1, day1, month2, day2 = match.groups()
            month2 = (month2.rstrip('月') if month2 else None) or month1
            year = datetime.now().year
            end_date = datetime(year, int(month2), int(day2)) + timedelta(days=1)
            return {
                "start": f"{year}-{int(month1):02d}-{int(day1):02d}",
                "end": end_date.strftime("%Y-%m-%d")
            }

        # 格式2: "2026年3月1日-15日"（单年份）
        pattern2 = r'(\d{4})年(\d{1,2})月(\d{1,2})日?[\-~到至](\d{1,2}月)?(\d{1,2})日'
        match2 = re.search(pattern2, query)
        if match2:
            year, month1, day1, month2, day2 = match2.groups()
            month2 = (month2.rstrip('月') if month2 else None) or month1
            end_date = datetime(int(year), int(month2), int(day2)) + timedelta(days=1)
            return {
                "start": f"{year}-{int(month1):02d}-{int(day1):02d}",
                "end": end_date.strftime("%Y-%m-%d")
            }

        # 格式3: "2026年3月10日-2026年3月15日"（双年份）
        pattern3 = r'(\d{4})年(\d{1,2})月(\d{1,2})日?[\-~到至](\d{4})年(\d{1,2})月(\d{1,2})日'
        match3 = re.search(pattern3, query)
        if match3:
            y1, m1, d1, y2, m2, d2 = match3.groups()
            end_date = datetime(int(y2), int(m2), int(d2)) + timedelta(days=1)
            return {
                "start": f"{y1}-{int(m1):02d}-{int(d1):02d}",
                "end": end_date.strftime("%Y-%m-%d")
            }

        return None


class LLMIntentParser:
    """LLM 驱动的意图解析器（输出结构化 JSON，不生成 SQL）"""

    PROMPT_TEMPLATE = """你是意图解析器。将用户查询转为结构化 JSON。

数据源（二选一）:
- MILEAGE: 里程数据，表 JS_DAY_DY_OP
- ORDER: 订单数据，表 DY_ORDER_INFO

MILEAGE 可用指标: MILEAGE, CARRY_MILEAGE, INOUT_MILEAGE, REVENUE
ORDER 可用指标: ORDER_COUNT, COMPLETED_ORDER, CANCELLED_ORDER, PASSENGER, PAY_AMOUNT

分组维度（可多选）: DRIVER, BUS, ROUTE, REGION, DATE, STATION, STATUS, NONE

聚合类型: SUM, AVG_DAILY, AVG_PER_BUS, COUNT

用户查询: {query}

只输出 JSON，不要任何解释:
{{"data_source":"MILEAGE|ORDER","metrics":["..."],"group_by":["..."],"aggregation":"SUM","date_range":null,"sort":null}}"""

    def __init__(self, llm=None):
        self._llm = llm

    def _get_llm(self):
        if self._llm is None:
            from langchain_openai import ChatOpenAI
            from config.settings import settings
            self._llm = ChatOpenAI(
                model=settings.model_name,
                openai_api_base=settings.model_base_url,
                openai_api_key=settings.model_api_key,
                temperature=0.1,
                max_tokens=512,
                streaming=False
            )
        return self._llm

    async def parse(self, query: str, timeout: float = 20.0) -> Optional[QueryIntent]:
        """LLM 意图解析，失败返回 None"""
        import asyncio
        try:
            llm = self._get_llm()
            prompt = self.PROMPT_TEMPLATE.format(query=query)
            response = await asyncio.wait_for(
                llm.ainvoke([{"role": "user", "content": prompt}]),
                timeout=timeout
            )
            return self._parse_response(response.content, query)
        except Exception as e:
            print(f"[LLMIntentParser] 解析失败: {e}")
            return None

    def _parse_response(self, llm_output: str, original_query: str) -> Optional[QueryIntent]:
        """解析 LLM JSON 输出为 QueryIntent"""
        # 提取 JSON
        text = llm_output.strip()
        # 去掉 markdown 代码块
        if "```" in text:
            match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
            if match:
                text = match.group(1)
        # 找到第一个 { 到最后一个 }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            text = text[start:end + 1]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None

        # 构建 QueryIntent
        try:
            data_source_str = data.get("data_source", "MILEAGE")
            data_source = DataSource.ORDER if data_source_str == "ORDER" else DataSource.MILEAGE

            aggregation_str = data.get("aggregation", "SUM").upper()
            try:
                aggregation = AggregationType[aggregation_str]
            except KeyError:
                aggregation = AggregationType.SUM

            group_by = []
            for dim_str in data.get("group_by", ["NONE"]):
                try:
                    group_by.append(GroupByDimension[dim_str.upper()])
                except KeyError:
                    pass
            if not group_by:
                group_by = [GroupByDimension.NONE]

            metrics = data.get("metrics", [])
            if not metrics:
                metrics = ["ORDER_COUNT"] if data_source == DataSource.ORDER else ["MILEAGE"]

            query_type = "order" if data_source == DataSource.ORDER else "mileage"

            return QueryIntent(
                query_type=query_type,
                data_source=data_source,
                aggregation=aggregation,
                group_by=group_by,
                metrics=metrics,
                date_range=data.get("date_range"),
                filters=data.get("filters", []),
                sort=data.get("sort"),
            )
        except Exception:
            return None


# 全局实例
intent_parser = IntentParser()
llm_intent_parser = LLMIntentParser()
