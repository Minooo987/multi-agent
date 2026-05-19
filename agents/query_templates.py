"""
SQL 查询模板库
预定义常见查询模式，LLM 只负责填空参数
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Callable
import re


@dataclass
class QueryTemplate:
    name: str
    description: str
    pattern: str  # 正则匹配用户查询
    sql_template: str
    required_params: List[str]
    param_extractors: Dict[str, Callable]  # 参数提取函数


QUERY_TEMPLATES = [
    QueryTemplate(
        name="mileage_by_driver_daily_avg",
        description="司机日均里程",
        pattern=r"(每个|各)?司机.*平均.*里程|日均.*里程.*司机|每个司机.*里程|司机.*日均",
        sql_template="""
            SELECT
                DRIVER_NAME,
                SUM(MILEAGE) / COUNT(DISTINCT TRUNC(JS_DATE)) AS AVG_DAILY_MILEAGE,
                SUM(MILEAGE) AS TOTAL_MILEAGE,
                COUNT(DISTINCT TRUNC(JS_DATE)) AS DAYS_COUNT,
                COUNT(DISTINCT BUS_ID) AS BUS_COUNT
            FROM {table}
            WHERE {date_condition}
            GROUP BY DRIVER_NAME, DRIVER_ID
        """,
        required_params=["table", "date_condition"],
        param_extractors={
            "table": lambda ctx: ctx.get("mileage_table", "T_BUS_MILEAGE_DETAIL"),
            "date_condition": lambda ctx: ctx.get("date_condition", "1=1")
        }
    ),
    QueryTemplate(
        name="mileage_by_bus_avg",
        description="单车平均里程",
        pattern=r"每辆车.*平均.*里程|单车.*平均|平均.*每辆车|车辆.*日均",
        sql_template="""
            SELECT
                BUS_NO,
                SUM(MILEAGE) / COUNT(DISTINCT TRUNC(JS_DATE)) AS AVG_DAILY_MILEAGE,
                SUM(MILEAGE) AS TOTAL_MILEAGE,
                COUNT(DISTINCT TRUNC(JS_DATE)) AS DAYS_COUNT
            FROM {table}
            WHERE {date_condition}
            GROUP BY BUS_NO, BUS_ID
        """,
        required_params=["table", "date_condition"],
        param_extractors={
            "table": lambda ctx: ctx.get("mileage_table", "T_BUS_MILEAGE_DETAIL"),
            "date_condition": lambda ctx: ctx.get("date_condition", "1=1")
        }
    ),
    QueryTemplate(
        name="mileage_total_overview",
        description="里程总览",
        pattern=r"总里程|累计里程|一共.*公里|里程.*概览",
        sql_template="""
            SELECT
                SUM(MILEAGE) AS TOTAL_MILEAGE,
                SUM(CARRY_MILEAGE) AS TOTAL_CARRY_MILEAGE,
                COUNT(DISTINCT BUS_ID) AS UNIQUE_BUSES,
                SUM(MILEAGE) / COUNT(DISTINCT BUS_ID) AS AVG_MILEAGE_PER_BUS
            FROM {table}
            WHERE {date_condition}
        """,
        required_params=["table", "date_condition"],
        param_extractors={
            "table": lambda ctx: ctx.get("mileage_table", "T_BUS_MILEAGE_DETAIL"),
            "date_condition": lambda ctx: ctx.get("date_condition", "1=1")
        }
    ),
    QueryTemplate(
        name="mileage_by_driver_total",
        description="司机总里程",
        pattern=r"(每个|各)?司机.*里程|司机.*总里程|每个驾驶员.*里程",
        sql_template="""
            SELECT
                DRIVER_NAME,
                SUM(MILEAGE) AS TOTAL_MILEAGE,
                SUM(CARRY_MILEAGE) AS TOTAL_CARRY_MILEAGE,
                COUNT(DISTINCT TRUNC(JS_DATE)) AS DAYS_COUNT
            FROM {table}
            WHERE {date_condition}
            GROUP BY DRIVER_NAME, DRIVER_ID
        """,
        required_params=["table", "date_condition"],
        param_extractors={
            "table": lambda ctx: ctx.get("mileage_table", "T_BUS_MILEAGE_DETAIL"),
            "date_condition": lambda ctx: ctx.get("date_condition", "1=1")
        }
    ),
    QueryTemplate(
        name="mileage_by_bus_total",
        description="车辆总里程",
        pattern=r"(每辆|各)?车.*里程|车辆.*总里程|每辆车.*里程",
        sql_template="""
            SELECT
                BUS_NO,
                SUM(MILEAGE) AS TOTAL_MILEAGE,
                SUM(CARRY_MILEAGE) AS TOTAL_CARRY_MILEAGE,
                COUNT(DISTINCT TRUNC(JS_DATE)) AS DAYS_COUNT
            FROM {table}
            WHERE {date_condition}
            GROUP BY BUS_NO, BUS_ID
        """,
        required_params=["table", "date_condition"],
        param_extractors={
            "table": lambda ctx: ctx.get("mileage_table", "T_BUS_MILEAGE_DETAIL"),
            "date_condition": lambda ctx: ctx.get("date_condition", "1=1")
        }
    ),
    # ===== 营运/订单类模板 =====
    QueryTemplate(
        name="order_by_station",
        description="按站点统计客流",
        pattern=r"(每个|各个|各)?(站点|车站).*客流|客流.*(站点|车站)|(上车|下车)站.*统计",
        sql_template="""
            SELECT
                START_STATION_NAME AS STATION_NAME,
                COUNT(*) AS TOTAL_ORDERS,
                COUNT(CASE WHEN STATUS_NAME = '已完成' THEN 1 END) AS COMPLETED_ORDERS,
                SUM(PASSENGER) AS TOTAL_PASSENGERS
            FROM {table}
            WHERE {date_condition}
            GROUP BY START_STATION_NAME
            ORDER BY TOTAL_ORDERS DESC
        """,
        required_params=["table", "date_condition"],
        param_extractors={
            "table": lambda ctx: ctx.get("order_table", "DY_ORDER_INFO"),
            "date_condition": lambda ctx: ctx.get("date_condition", "1=1")
        }
    ),
    QueryTemplate(
        name="order_overview",
        description="订单概览统计",
        pattern=r"订单.*(概览|统计|情况|汇总)|总订单|订单.*多少",
        sql_template="""
            SELECT
                COUNT(*) AS TOTAL_ORDERS,
                COUNT(CASE WHEN STATUS_NAME = '已完成' THEN 1 END) AS COMPLETED_ORDERS,
                COUNT(CASE WHEN STATUS_NAME = '已取消' THEN 1 END) AS CANCELLED_ORDERS,
                SUM(PASSENGER) AS TOTAL_PASSENGERS,
                ROUND(COUNT(CASE WHEN STATUS_NAME = '已完成' THEN 1 END) / COUNT(*) * 100, 2) AS COMPLETION_RATE
            FROM {table}
            WHERE {date_condition}
        """,
        required_params=["table", "date_condition"],
        param_extractors={
            "table": lambda ctx: ctx.get("order_table", "DY_ORDER_INFO"),
            "date_condition": lambda ctx: ctx.get("date_condition", "1=1")
        }
    ),
    QueryTemplate(
        name="order_by_region",
        description="按区域统计订单",
        pattern=r"(每个|各个|各)?(区域|片区|区).*订单|订单.*(区域|片区)",
        sql_template="""
            SELECT
                REGION_NAME,
                COUNT(*) AS TOTAL_ORDERS,
                COUNT(CASE WHEN STATUS_NAME = '已完成' THEN 1 END) AS COMPLETED_ORDERS,
                SUM(PASSENGER) AS TOTAL_PASSENGERS
            FROM {table}
            WHERE {date_condition}
            GROUP BY REGION_NAME
            ORDER BY TOTAL_ORDERS DESC
        """,
        required_params=["table", "date_condition"],
        param_extractors={
            "table": lambda ctx: ctx.get("order_table", "DY_ORDER_INFO"),
            "date_condition": lambda ctx: ctx.get("date_condition", "1=1")
        }
    ),
    QueryTemplate(
        name="order_by_status",
        description="按状态统计订单",
        pattern=r"订单.*状态|状态.*统计|取消.*订单.*多少",
        sql_template="""
            SELECT
                STATUS_NAME,
                COUNT(*) AS ORDER_COUNT,
                SUM(PASSENGER) AS TOTAL_PASSENGERS
            FROM {table}
            WHERE {date_condition}
            GROUP BY STATUS_NAME
            ORDER BY ORDER_COUNT DESC
        """,
        required_params=["table", "date_condition"],
        param_extractors={
            "table": lambda ctx: ctx.get("order_table", "DY_ORDER_INFO"),
            "date_condition": lambda ctx: ctx.get("date_condition", "1=1")
        }
    ),
]


def match_template(query: str) -> Optional[QueryTemplate]:
    """根据用户查询匹配模板"""
    for template in QUERY_TEMPLATES:
        if re.search(template.pattern, query, re.IGNORECASE):
            return template
    return None


def apply_template(template: QueryTemplate, context: Dict) -> str:
    """应用模板，填入参数"""
    params = {}
    for param_name in template.required_params:
        extractor = template.param_extractors.get(param_name)
        if extractor:
            params[param_name] = extractor(context)
        else:
            params[param_name] = context.get(param_name, "")

    sql = template.sql_template.format(**params)
    # 清理多余空白
    lines = [line.strip() for line in sql.strip().split('\n') if line.strip()]
    return ' '.join(lines)
