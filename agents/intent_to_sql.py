"""
意图到 SQL 转换器
将结构化意图转换为 SQL 语句（无需 LLM）
"""

from agents.intent_parser import QueryIntent, AggregationType, GroupByDimension, DataSource


# ===== 列名映射 =====

# 里程域: 分组维度 → 列名
_MILEAGE_GROUP_COLS = {
    GroupByDimension.DRIVER:  ("DRIVER_NAME", ["DRIVER_NAME", "DRIVER_ID"]),
    GroupByDimension.BUS:     ("BUS_NO",      ["BUS_NO", "BUS_ID"]),
    GroupByDimension.ROUTE:   ("ROUTE_NAME",  ["ROUTE_NAME", "ROUTE_ID"]),
    GroupByDimension.REGION:  ("REGION_NAME", ["REGION_NAME", "REGION_ID"]),
    GroupByDimension.DATE:    ("TRUNC(JS_DATE) AS OPERATE_DATE", ["TRUNC(JS_DATE)"]),
}

# 订单域: 分组维度 → 列名
_ORDER_GROUP_COLS = {
    GroupByDimension.DRIVER:  ("DRIVER_NAME",       ["DRIVER_NAME", "DRIVER_ID"]),
    GroupByDimension.BUS:     ("BUS_NO",            ["BUS_NO", "BUS_ID"]),
    GroupByDimension.ROUTE:   ("ROUTE_NAME",        ["ROUTE_NAME", "ROUTE_ID"]),
    GroupByDimension.REGION:  ("REGION_NAME",       ["REGION_NAME"]),
    GroupByDimension.DATE:    ("TRUNC(CREATE_DATE) AS ORDER_DATE", ["TRUNC(CREATE_DATE)"]),
    GroupByDimension.STATION: ("START_STATION_NAME", ["START_STATION_NAME"]),
    GroupByDimension.STATUS:  ("STATUS_NAME",       ["STATUS_NAME"]),
}

# 里程域: 指标 → SQL 表达式
_MILEAGE_METRIC_EXPR = {
    "MILEAGE": {
        AggregationType.SUM:       "SUM(MILEAGE) AS TOTAL_MILEAGE",
        AggregationType.AVG_DAILY: "SUM(MILEAGE) / COUNT(DISTINCT TRUNC(JS_DATE)) AS AVG_DAILY_MILEAGE",
        AggregationType.AVG_PER_BUS: "SUM(MILEAGE) / COUNT(DISTINCT BUS_ID) AS AVG_PER_BUS_MILEAGE",
        AggregationType.AVG_RECORD: "AVG(MILEAGE) AS AVG_MILEAGE",
    },
    "CARRY_MILEAGE": {
        AggregationType.SUM:       "SUM(CARRY_MILEAGE) AS TOTAL_CARRY_MILEAGE",
        AggregationType.AVG_DAILY: "SUM(CARRY_MILEAGE) / COUNT(DISTINCT TRUNC(JS_DATE)) AS AVG_DAILY_CARRY_MILEAGE",
        AggregationType.AVG_PER_BUS: "SUM(CARRY_MILEAGE) / COUNT(DISTINCT BUS_ID) AS AVG_PER_BUS_CARRY_MILEAGE",
    },
    "INOUT_MILEAGE": {
        AggregationType.SUM: "SUM(INOUT_MILEAGE) AS TOTAL_INOUT_MILEAGE",
    },
    "REVENUE": {
        AggregationType.SUM: "SUM(REVENUE) AS TOTAL_REVENUE",
    },
}

# 订单域: 指标 → SQL 表达式
_ORDER_METRIC_EXPR = {
    "ORDER_COUNT": {
        AggregationType.SUM:   "COUNT(*) AS TOTAL_ORDERS",
        AggregationType.COUNT: "COUNT(*) AS TOTAL_ORDERS",
    },
    "COMPLETED_ORDER": {
        AggregationType.SUM:   "COUNT(CASE WHEN STATUS_NAME = '已完成' THEN 1 END) AS COMPLETED_ORDERS",
        AggregationType.COUNT: "COUNT(CASE WHEN STATUS_NAME = '已完成' THEN 1 END) AS COMPLETED_ORDERS",
    },
    "CANCELLED_ORDER": {
        AggregationType.SUM:   "COUNT(CASE WHEN STATUS_NAME = '已取消' THEN 1 END) AS CANCELLED_ORDERS",
        AggregationType.COUNT: "COUNT(CASE WHEN STATUS_NAME = '已取消' THEN 1 END) AS CANCELLED_ORDERS",
    },
    "PASSENGER": {
        AggregationType.SUM:       "SUM(PASSENGER) AS TOTAL_PASSENGERS",
        AggregationType.AVG_DAILY: "SUM(PASSENGER) / COUNT(DISTINCT TRUNC(CREATE_DATE)) AS AVG_DAILY_PASSENGERS",
    },
    "PAY_AMOUNT": {
        AggregationType.SUM: "SUM(PAY_AMOUNT) AS TOTAL_REVENUE",
    },
}

# 默认表名
_TABLE_MAP = {
    DataSource.MILEAGE: "JS_DAY_DY_OP",
    DataSource.ORDER:   "DY_ORDER_INFO",
}

# 日期列
_DATE_COL_MAP = {
    DataSource.MILEAGE: "JS_DATE",
    DataSource.ORDER:   "CREATE_DATE",
}


class IntentToSQLConverter:
    """意图到 SQL 转换器"""

    def convert(self, intent: QueryIntent, table_name: str = None) -> str:
        """将意图转换为 SQL"""
        data_source = intent.data_source
        if table_name is None:
            table_name = _TABLE_MAP.get(data_source, "JS_DAY_DY_OP")

        # SELECT 部分
        select_parts = []
        metric_exprs = _ORDER_METRIC_EXPR if data_source == DataSource.ORDER else _MILEAGE_METRIC_EXPR
        group_cols_map = _ORDER_GROUP_COLS if data_source == DataSource.ORDER else _MILEAGE_GROUP_COLS

        for metric in intent.metrics:
            expr_map = metric_exprs.get(metric.upper(), {})
            expr = expr_map.get(intent.aggregation) or expr_map.get(AggregationType.SUM)
            if expr:
                select_parts.append(expr)

        # 分组维度
        group_by_cols = []
        for dim in intent.group_by:
            if dim == GroupByDimension.NONE:
                continue
            col_info = group_cols_map.get(dim)
            if col_info:
                select_col, gb_cols = col_info
                select_parts.insert(0, select_col)
                group_by_cols.extend(gb_cols)

        # 概览查询时补充辅助统计
        if not group_by_cols:
            if data_source == DataSource.MILEAGE:
                if not any("BUS_ID" in p for p in select_parts):
                    select_parts.append("COUNT(DISTINCT BUS_ID) AS UNIQUE_BUSES")
                if not any("JS_DATE" in p for p in select_parts):
                    select_parts.append("COUNT(DISTINCT TRUNC(JS_DATE)) AS UNIQUE_DAYS")
            elif data_source == DataSource.ORDER:
                if not any("TOTAL_ORDERS" in p for p in select_parts):
                    select_parts.append("COUNT(*) AS TOTAL_ORDERS")
                if not any("COMPLETED_ORDERS" in p for p in select_parts):
                    select_parts.append("COUNT(CASE WHEN STATUS_NAME = '已完成' THEN 1 END) AS COMPLETED_ORDERS")
                if not any("CANCELLED_ORDERS" in p for p in select_parts):
                    select_parts.append("COUNT(CASE WHEN STATUS_NAME = '已取消' THEN 1 END) AS CANCELLED_ORDERS")
                if not any("TOTAL_PASSENGERS" in p for p in select_parts):
                    select_parts.append("SUM(PASSENGER) AS TOTAL_PASSENGERS")

        # 日期条件
        date_col = _DATE_COL_MAP.get(data_source, "JS_DATE")
        where_parts = []
        if intent.date_range:
            start = intent.date_range["start"]
            end = intent.date_range["end"]
            where_parts.append(
                f"{date_col} >= TO_DATE('{start}', 'YYYY-MM-DD') "
                f"AND {date_col} < TO_DATE('{end}', 'YYYY-MM-DD')"
            )

        # 构建 SQL
        sql = f"SELECT {', '.join(select_parts)} FROM {table_name}"
        if where_parts:
            sql += f" WHERE {' AND '.join(where_parts)}"
        if group_by_cols:
            sql += f" GROUP BY {', '.join(group_by_cols)}"

        # 排序
        if intent.sort:
            field = intent.sort.get("field", "")
            direction = intent.sort.get("direction", "DESC")
            if field:
                sql += f" ORDER BY {field} {direction}"
        elif group_by_cols:
            # 分组查询默认按第一个指标降序
            first_metric_alias = self._get_first_metric_alias(select_parts)
            if first_metric_alias:
                sql += f" ORDER BY {first_metric_alias} DESC"

        return sql

    def _get_first_metric_alias(self, select_parts: list) -> str:
        """从 SELECT 部分提取第一个指标别名"""
        for part in select_parts:
            match = __import__('re').search(r'\bAS\s+(\w+)', part, __import__('re').IGNORECASE)
            if match:
                return match.group(1)
        return ""


# 全局实例
intent_to_sql = IntentToSQLConverter()
