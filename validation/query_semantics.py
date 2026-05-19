"""
查询语义验证器
验证生成的 SQL 是否符合用户意图
"""

from typing import List, Dict
from dataclasses import dataclass


@dataclass
class SemanticIssue:
    severity: str  # "error", "warning"
    message: str
    suggestion: str


class QuerySemanticsValidator:
    """查询语义验证器"""

    def validate(self, user_query: str, sql: str) -> List[SemanticIssue]:
        """验证 SQL 是否符合用户查询意图"""
        issues = []
        sql_upper = sql.upper()

        # 1. 检查"平均"语义
        if "平均" in user_query and "AVG(MILEAGE)" in sql_upper:
            issues.append(SemanticIssue(
                severity="error",
                message="用户要求'平均里程'，但SQL使用了AVG(MILEAGE)。"
                        "业务上的'平均'通常指'总里程÷天数'，而非'记录平均值'",
                suggestion="改用 SUM(MILEAGE) / COUNT(DISTINCT TRUNC(JS_DATE))"
            ))

        # 2. 检查分组维度
        if "每个司机" in user_query and "DRIVER_NAME" not in sql_upper:
            issues.append(SemanticIssue(
                severity="error",
                message="用户要求按司机分组，但SQL中缺少 DRIVER_NAME",
                suggestion="添加 GROUP BY DRIVER_NAME, DRIVER_ID"
            ))

        if "每辆车" in user_query and "BUS_NO" not in sql_upper:
            issues.append(SemanticIssue(
                severity="error",
                message="用户要求按车辆分组，但SQL中缺少 BUS_NO",
                suggestion="添加 GROUP BY BUS_NO, BUS_ID"
            ))

        # 3. 检查日期范围
        if any(kw in user_query for kw in ["3月", "昨天", "上周", "今天", "明天", "日", "月"]):
            if "TO_DATE" not in sql_upper and "SYSDATE" not in sql_upper:
                issues.append(SemanticIssue(
                    severity="warning",
                    message="查询包含日期条件，但SQL中未找到日期过滤",
                    suggestion="添加 WHERE JS_DATE >= ..."
                ))

        # 4. 检查"日/天"关键词
        if ("每天" in user_query or "日均" in user_query) and "TRUNC(JS_DATE)" not in sql_upper:
            issues.append(SemanticIssue(
                severity="warning",
                message="用户提到'每天'或'日均'，但SQL未按天分组",
                suggestion="考虑添加 GROUP BY TRUNC(JS_DATE)"
            ))

        # 5. 检查聚合函数与查询意图匹配
        if "总" in user_query and "SUM(" not in sql_upper:
            issues.append(SemanticIssue(
                severity="error",
                message="用户要求'总计/累计'，但SQL未使用 SUM",
                suggestion="使用 SUM() 聚合函数"
            ))

        # 6. 检查是否包含必要的聚合
        if ("每个" in user_query or "各" in user_query) and "GROUP BY" not in sql_upper:
            issues.append(SemanticIssue(
                severity="error",
                message="用户要求按维度分组统计，但SQL缺少 GROUP BY",
                suggestion="添加适当的 GROUP BY 子句"
            ))

        return issues


# 全局实例
semantics_validator = QuerySemanticsValidator()
