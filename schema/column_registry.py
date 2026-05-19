"""
列元数据注册中心
集中管理所有列名 → 中文标签/类型/单位的映射
"""

import re
from typing import Dict, List, Optional


class ColumnRegistry:
    """集中式列元数据注册中心 — 所有列名映射的唯一来源"""

    _entries: Dict[str, Dict] = {
        # ===== 里程/乘客域 (JS_DAY_DY_OP) =====
        "MILEAGE":            {"label": "总里程",       "type": "number", "unit": "km",   "domain": "passenger"},
        "TOTAL_MILEAGE":      {"label": "总里程",       "type": "number", "unit": "km",   "domain": "passenger"},
        "CARRY_MILEAGE":      {"label": "载客里程",     "type": "number", "unit": "km",   "domain": "passenger"},
        "TOTAL_CARRY_MILEAGE":{"label": "载客里程",     "type": "number", "unit": "km",   "domain": "passenger"},
        "INOUT_MILEAGE":      {"label": "进场里程",     "type": "number", "unit": "km",   "domain": "passenger"},
        "AVG_DAILY_MILEAGE":  {"label": "日均里程",     "type": "number", "unit": "km/天", "domain": "passenger"},
        "AVG_PER_BUS_MILEAGE":{"label": "单车均里程",   "type": "number", "unit": "km/辆", "domain": "passenger"},
        "AVG_MILEAGE":        {"label": "平均里程",     "type": "number", "unit": "km",   "domain": "passenger"},
        "EMPTY_MILEAGE":      {"label": "空驶里程",     "type": "number", "unit": "km",   "domain": "passenger"},
        "MILEAGE_UTILIZATION_RATE": {"label": "里程利用率", "type": "number", "unit": "%", "domain": "passenger"},
        "REVENUE":            {"label": "营收",         "type": "number", "unit": "元",   "domain": "passenger"},
        "REVENUE2":           {"label": "营收2",        "type": "number", "unit": "元",   "domain": "passenger"},

        # 时间字段
        "INOUT_MIN":          {"label": "进场时长",     "type": "number", "unit": "分钟", "domain": "passenger"},
        "WAIT_MIN":           {"label": "等待时长",     "type": "number", "unit": "分钟", "domain": "passenger"},
        "CARRY_MIN":          {"label": "载客时长",     "type": "number", "unit": "分钟", "domain": "passenger"},
        "PAUSE_MIN":          {"label": "停歇时长",     "type": "number", "unit": "分钟", "domain": "passenger"},

        # ===== 订单域 (DY_ORDER_INFO) =====
        "TOTAL_ORDERS":       {"label": "总订单数",     "type": "number", "unit": "单",   "domain": "operation"},
        "COMPLETED_ORDERS":   {"label": "完成订单",     "type": "number", "unit": "单",   "domain": "operation"},
        "CANCELLED_ORDERS":   {"label": "取消订单",     "type": "number", "unit": "单",   "domain": "operation"},
        "TOTAL_PASSENGERS":   {"label": "乘客数",       "type": "number", "unit": "人",   "domain": "operation"},
        "COMPLETION_RATE":    {"label": "完成率",       "type": "number", "unit": "%",    "domain": "operation"},
        "TOTAL_REVENUE":      {"label": "总营收",       "type": "number", "unit": "元",   "domain": "operation"},
        "PAY_AMOUNT":         {"label": "支付金额",     "type": "number", "unit": "元",   "domain": "operation"},
        "ORDER_COUNT":        {"label": "订单数",       "type": "number", "unit": "单",   "domain": "operation"},
        "PASSENGER":          {"label": "乘客数",       "type": "number", "unit": "人",   "domain": "operation"},
        "AVG_PASSENGERS_PER_ORDER": {"label": "单均乘客", "type": "number", "unit": "人/单", "domain": "operation"},

        # ===== 公共维度 =====
        "DRIVER_NAME":        {"label": "司机",         "type": "string", "unit": "",     "domain": "both"},
        "DRIVER_ID":          {"label": "司机ID",       "type": "string", "unit": "",     "domain": "both"},
        "JOB_NUMBER":         {"label": "工号",         "type": "string", "unit": "",     "domain": "both"},
        "BUS_NO":             {"label": "车辆编号",     "type": "string", "unit": "",     "domain": "both"},
        "BUS_ID":             {"label": "车辆ID",       "type": "string", "unit": "",     "domain": "both"},
        "BUS_SELF_ID":        {"label": "车辆自编号",   "type": "string", "unit": "",     "domain": "both"},
        "ROUTE_NAME":         {"label": "线路",         "type": "string", "unit": "",     "domain": "both"},
        "ROUTE_ID":           {"label": "线路ID",       "type": "string", "unit": "",     "domain": "both"},
        "REGION_NAME":        {"label": "区域",         "type": "string", "unit": "",     "domain": "both"},
        "REGION_ID":          {"label": "区域ID",       "type": "string", "unit": "",     "domain": "both"},

        # 日期/时间
        "JS_DATE":            {"label": "结算日期",     "type": "date",   "unit": "",     "domain": "passenger"},
        "OPERATE_DATE":       {"label": "运营日期",     "type": "date",   "unit": "",     "domain": "passenger"},
        "CREATE_DATE":        {"label": "创建日期",     "type": "date",   "unit": "",     "domain": "operation"},

        # 统计辅助
        "DAYS_COUNT":         {"label": "运营天数",     "type": "number", "unit": "天",   "domain": "passenger"},
        "DAY_COUNT":          {"label": "运营天数",     "type": "number", "unit": "天",   "domain": "passenger"},
        "UNIQUE_DAYS":        {"label": "运营天数",     "type": "number", "unit": "天",   "domain": "passenger"},
        "UNIQUE_BUSES":       {"label": "车辆数",       "type": "number", "unit": "辆",   "domain": "passenger"},
        "BUS_COUNT":          {"label": "车辆数",       "type": "number", "unit": "辆",   "domain": "passenger"},
        "RECORD_COUNT":       {"label": "记录数",       "type": "number", "unit": "条",   "domain": "both"},

        # 订单维度
        "STATUS_NAME":        {"label": "订单状态",     "type": "string", "unit": "",     "domain": "operation"},
        "START_STATION_NAME": {"label": "上车站点",     "type": "string", "unit": "",     "domain": "operation"},
        "END_STATION_NAME":   {"label": "下车站点",     "type": "string", "unit": "",     "domain": "operation"},
        "STATION_NAME":       {"label": "站点",         "type": "string", "unit": "",     "domain": "operation"},
        "ORDER_PAY_TYPE_NAME":{"label": "支付方式",     "type": "string", "unit": "",     "domain": "operation"},
    }

    # 反向映射：中文标签 → 英文列名（用于 SQL 别名规范化）
    _label_to_key: Dict[str, str] = {}

    @classmethod
    def _build_reverse_map(cls):
        if cls._label_to_key:
            return
        for key, entry in cls._entries.items():
            label = entry["label"]
            # 保留第一个映射
            if label not in cls._label_to_key:
                cls._label_to_key[label] = key

    @classmethod
    def get(cls, col_key: str) -> Optional[Dict]:
        return cls._entries.get(col_key.upper())

    @classmethod
    def get_label(cls, col_key: str) -> str:
        entry = cls._entries.get(col_key.upper())
        return entry["label"] if entry else col_key

    @classmethod
    def get_label_with_unit(cls, col_key: str) -> str:
        entry = cls._entries.get(col_key.upper())
        if not entry:
            return col_key
        label = entry["label"]
        unit = entry.get("unit", "")
        return f"{label}({unit})" if unit else label

    @classmethod
    def key_from_label(cls, chinese_label: str) -> Optional[str]:
        """反向查找：中文标签 → 英文列名"""
        cls._build_reverse_map()
        return cls._label_to_key.get(chinese_label)

    @classmethod
    def get_all_for_domain(cls, domain: str) -> Dict:
        return {k: v for k, v in cls._entries.items() if v["domain"] in (domain, "both")}

    @classmethod
    def get_metadata_dict(cls, columns: List[str]) -> Dict[str, Dict]:
        """为一组列名构建 column_metadata 字典（供前端使用）"""
        result = {}
        for col in columns:
            col_upper = col.upper()
            entry = cls._entries.get(col_upper)
            # 如果直接查找失败，尝试去掉常见后缀再查找
            if not entry:
                for suffix in ['_KM', '_RATE', '_COUNT', '_NUM', '_AMOUNT']:
                    if col_upper.endswith(suffix):
                        base_key = col_upper[:-len(suffix)]
                        entry = cls._entries.get(base_key)
                        if entry:
                            break
            if entry:
                result[col] = {
                    "label": entry["label"],
                    "type": entry["type"],
                    "unit": entry["unit"],
                }
            else:
                result[col] = {"label": col, "type": "string", "unit": ""}
        return result


class SchemaContext:
    """为 LLM 提供格式化的 Schema 信息"""

    def __init__(self, table_name: str, columns: List[Dict]):
        self.table_name = table_name
        self.columns = columns
        self._col_names_upper = {c.get("COLUMN_NAME", "").upper() for c in columns}
        self._col_by_name = {c.get("COLUMN_NAME", "").upper(): c for c in columns}

    def format_for_prompt(self) -> str:
        """格式化完整 Schema 信息（用于 LLM prompt）"""
        lines = [f"表 {self.table_name} 共 {len(self.columns)} 列:"]
        for c in self.columns:
            name = c.get("COLUMN_NAME", "")
            dtype = c.get("DATA_TYPE", "")
            comment = c.get("COMMENTS", "") or ""
            lines.append(f"  {name} {dtype} -- {comment}")
        return "\n".join(lines)

    def format_aggregation_rules(self, data_source: str) -> str:
        """返回标准聚合模式（防止 LLM 自由发挥）"""
        if data_source == "MILEAGE":
            return """
聚合规则（严格遵守）:
- 总里程: SUM(MILEAGE) AS TOTAL_MILEAGE
- 日均里程: SUM(MILEAGE) / COUNT(DISTINCT TRUNC(JS_DATE)) AS AVG_DAILY_MILEAGE
- 单车平均: SUM(MILEAGE) / COUNT(DISTINCT BUS_ID) AS AVG_PER_BUS_MILEAGE
- 载客里程: SUM(CARRY_MILEAGE) AS TOTAL_CARRY_MILEAGE
- 空驶里程: SUM(MILEAGE) - SUM(CARRY_MILEAGE) AS EMPTY_MILEAGE
- 里程利用率: ROUND(SUM(CARRY_MILEAGE) / SUM(MILEAGE) * 100, 2) AS MILEAGE_UTILIZATION_RATE
- 禁止使用 AVG(MILEAGE) 表示业务平均（应用 SUM/COUNT(DISTINCT ...) 计算）
"""
        elif data_source == "ORDER":
            return """
聚合规则（严格遵守）:
- 总订单: COUNT(*) AS TOTAL_ORDERS
- 完成订单: COUNT(CASE WHEN STATUS_NAME = '已完成' THEN 1 END) AS COMPLETED_ORDERS
- 取消订单: COUNT(CASE WHEN STATUS_NAME = '已取消' THEN 1 END) AS CANCELLED_ORDERS
- 完成率: ROUND(COUNT(CASE WHEN STATUS_NAME = '已完成' THEN 1 END) / COUNT(*) * 100, 2) AS COMPLETION_RATE
- 总乘客: SUM(PASSENGER) AS TOTAL_PASSENGERS
- 总营收: SUM(PAY_AMOUNT) AS TOTAL_REVENUE
"""
        return ""

    def format_constraints(self) -> str:
        """返回 SQL 约束规则"""
        return """
SQL 约束（违反将导致执行失败）:
1. 所有列名必须使用大写（Oracle 默认大写）
2. 禁止使用中文别名（如 AS 总里程），必须用英文（如 AS TOTAL_MILEAGE）
3. 禁止 SELECT *
4. GROUP BY 查询不要加 ROWNUM 限制
5. 日期比较: 开始用 >= TO_DATE('YYYY-MM-DD','YYYY-MM-DD')，结束用 < TO_DATE('YYYY-MM-DD','YYYY-MM-DD')
6. GROUP BY 必须包含 SELECT 中所有非聚合列
"""

    def validate_column(self, col_name: str) -> bool:
        """检查列名是否存在于 Schema 中"""
        return col_name.upper() in self._col_names_upper

    def get_column_names_upper(self) -> set:
        """返回所有大写列名集合"""
        return self._col_names_upper
