"""
结果验证与修正系统 (Harness Engineering)
确保分析结果的数据质量和完整性
"""

import json
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from enum import Enum

from schema.column_registry import ColumnRegistry


class ValidationSeverity(Enum):
    """验证严重程度"""
    CRITICAL = "critical"    # 必须修复
    WARNING = "warning"     # 建议修复
    INFO = "info"           # 仅供参考


@dataclass
class ValidationIssue:
    """验证问题"""
    severity: ValidationSeverity
    field: str
    message: str
    suggestion: str


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    issues: List[ValidationIssue]
    fixed_data: Optional[Dict[str, Any]] = None


class ResultValidator:
    """
    结果验证器
    检查分析结果的完整性和正确性
    """

    def __init__(self):
        self.validators: Dict[str, Callable] = {
            "passenger": self._validate_passenger_result,
            "operation": self._validate_operation_result,
            "general": self._validate_general_result
        }

    def validate(self, result_type: str, result: Dict[str, Any], raw_data: Optional[Dict] = None) -> ValidationResult:
        """
        验证结果

        Args:
            result_type: 结果类型 (passenger/operation/general)
            result: 要验证的结果字典
            raw_data: 原始数据（用于验证统计是否正确）

        Returns:
            ValidationResult: 验证结果
        """
        validator = self.validators.get(result_type, self._validate_general_result)
        return validator(result, raw_data)

    def _validate_passenger_result(self, result: Dict[str, Any], raw_data: Optional[Dict] = None) -> ValidationResult:
        """验证里程分析结果"""
        issues = []
        fixed_data = result.copy()

        statistics = result.get("statistics", {})
        if not statistics:
            statistics = result.get("analysis", {}).get("statistics", {})

        # 检查关键字段
        required_fields = {
            "total_mileage_km": ("总里程", float, lambda x: x > 0),
            "carry_mileage_km": ("载客里程", float, lambda x: x >= 0),
            "mileage_utilization_rate": ("里程利用率", float, lambda x: 0 <= x <= 100)
        }

        for field, (name, type_, validator_fn) in required_fields.items():
            value = statistics.get(field)

            if value is None:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.CRITICAL,
                    field=field,
                    message=f"缺少{name}数据",
                    suggestion=f"从原始数据重新计算 {name}"
                ))
            elif not isinstance(value, (int, float)):
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.CRITICAL,
                    field=field,
                    message=f"{name}数据类型错误: {type(value)}",
                    suggestion=f"转换为数字类型"
                ))
            elif not validator_fn(value):
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    field=field,
                    message=f"{name}数值异常: {value}",
                    suggestion=f"检查计算逻辑"
                ))

        # 检查逻辑一致性
        if all(f in statistics for f in ["total_mileage_km", "carry_mileage_km"]):
            total = float(statistics.get("total_mileage_km", 0))
            carry = float(statistics.get("carry_mileage_km", 0))

            if carry > total:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.CRITICAL,
                    field="carry_mileage_km",
                    message=f"载客里程({carry})大于总里程({total})",
                    suggestion="修正载客里程值"
                ))
                # 自动修正
                fixed_data["statistics"] = fixed_data.get("statistics", {})
                fixed_data["statistics"]["carry_mileage_km"] = total * 0.5
                fixed_data["statistics"]["empty_mileage_km"] = total * 0.5

        # 检查关键发现
        key_findings = result.get("key_findings", [])
        if not key_findings:
            key_findings = result.get("analysis", {}).get("key_findings", [])

        if not key_findings:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                field="key_findings",
                message="缺少关键发现",
                suggestion="基于统计数据生成关键发现"
            ))

        # 如果原始数据可用，验证统计是否正确
        if raw_data and "rows" in raw_data:
            calculated = self._calculate_passenger_stats(raw_data["rows"], raw_data.get("columns", []))
            if calculated.get("total_mileage", 0) > 0:
                expected_total = calculated["total_mileage"]
                actual_total = statistics.get("total_mileage_km", 0)
                if abs(expected_total - actual_total) > 0.01 * expected_total:
                    issues.append(ValidationIssue(
                        severity=ValidationSeverity.CRITICAL,
                        field="total_mileage_km",
                        message=f"总里程不匹配: 期望 {expected_total}, 实际 {actual_total}",
                        suggestion="使用预计算值替换"
                    ))
                    fixed_data["statistics"] = fixed_data.get("statistics", {})
                    fixed_data["statistics"]["total_mileage_km"] = expected_total
                    fixed_data["statistics"]["carry_mileage_km"] = calculated.get("carry_mileage", 0)
                    fixed_data["statistics"]["empty_mileage_km"] = calculated.get("empty_mileage", 0)

        return ValidationResult(
            is_valid=len([i for i in issues if i.severity == ValidationSeverity.CRITICAL]) == 0,
            issues=issues,
            fixed_data=fixed_data if issues else None
        )

    def _validate_operation_result(self, result: Dict[str, Any], raw_data: Optional[Dict] = None) -> ValidationResult:
        """验证订单分析结果"""
        issues = []
        fixed_data = result.copy()

        statistics = result.get("statistics", {})
        if not statistics:
            statistics = result.get("analysis", {}).get("statistics", {})

        # 检查关键字段
        required_fields = {
            "total_orders": ("总订单数", int, lambda x: x > 0),
            "completed_orders": ("完成订单数", int, lambda x: x >= 0),
            "cancelled_orders": ("取消订单数", int, lambda x: x >= 0),
            "completion_rate": ("完成率", float, lambda x: 0 <= x <= 100)
        }

        for field, (name, type_, validator_fn) in required_fields.items():
            value = statistics.get(field)

            if value is None or value == 0:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.CRITICAL,
                    field=field,
                    message=f"{name}为0或缺失",
                    suggestion=f"从原始数据重新计算 {name}"
                ))
            elif not isinstance(value, (int, float)):
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.CRITICAL,
                    field=field,
                    message=f"{name}数据类型错误: {type(value)}",
                    suggestion=f"转换为数字类型"
                ))
            elif not validator_fn(value):
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    field=field,
                    message=f"{name}数值异常: {value}",
                    suggestion=f"检查计算逻辑"
                ))

        # 检查逻辑一致性
        total = int(statistics.get("total_orders", 0))
        completed = int(statistics.get("completed_orders", 0))
        cancelled = int(statistics.get("cancelled_orders", 0))
        if all(f in statistics for f in ["total_orders", "completed_orders", "cancelled_orders"]):

            if completed + cancelled != total:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    field="order_consistency",
                    message=f"订单数不一致: 完成({completed}) + 取消({cancelled}) ≠ 总计({total})",
                    suggestion="重新计算完成订单数"
                ))

        # 验证完成率计算
        if total > 0:
            expected_rate = round(completed / total * 100, 2)
            actual_rate = statistics.get("completion_rate", 0)
            if abs(expected_rate - actual_rate) > 1:  # 允许1%误差
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    field="completion_rate",
                    message=f"完成率计算错误: 期望 {expected_rate}%, 实际 {actual_rate}%",
                    suggestion=f"修正为 {expected_rate}%"
                ))
                fixed_data["statistics"] = fixed_data.get("statistics", {})
                fixed_data["statistics"]["completion_rate"] = expected_rate

        # 如果原始数据可用，验证统计是否正确
        if raw_data and "rows" in raw_data:
            calculated = self._calculate_operation_stats(raw_data["rows"], raw_data.get("columns", []))
            if calculated.get("total_orders", 0) > 0:
                expected_total = calculated["total_orders"]
                actual_total = statistics.get("total_orders", 0)
                if abs(expected_total - actual_total) > 0.01 * expected_total:
                    issues.append(ValidationIssue(
                        severity=ValidationSeverity.CRITICAL,
                        field="total_orders",
                        message=f"总订单数不匹配: 期望 {expected_total}, 实际 {actual_total}",
                        suggestion="使用预计算值替换"
                    ))
                    fixed_data["statistics"] = fixed_data.get("statistics", {})
                    fixed_data["statistics"]["total_orders"] = expected_total
                    fixed_data["statistics"]["completed_orders"] = calculated.get("completed_orders", 0)
                    fixed_data["statistics"]["cancelled_orders"] = calculated.get("cancelled_orders", 0)
                    fixed_data["statistics"]["completion_rate"] = calculated.get("completion_rate", 0)

        # 检查关键发现
        key_findings = result.get("key_findings", [])
        if not key_findings:
            key_findings = result.get("analysis", {}).get("key_findings", [])

        if not key_findings:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                field="key_findings",
                message="缺少关键发现",
                suggestion="基于统计数据生成关键发现"
            ))

        return ValidationResult(
            is_valid=len([i for i in issues if i.severity == ValidationSeverity.CRITICAL]) == 0,
            issues=issues,
            fixed_data=fixed_data if issues else None
        )

    def _validate_general_result(self, result: Dict[str, Any], raw_data: Optional[Dict] = None) -> ValidationResult:
        """通用结果验证"""
        issues = []

        if not result:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.CRITICAL,
                field="result",
                message="结果为空",
                suggestion="检查数据处理流程"
            ))

        if "error" in result:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.CRITICAL,
                field="error",
                message=f"结果包含错误: {result['error']}",
                suggestion="修复错误后重新分析"
            ))

        return ValidationResult(
            is_valid=len([i for i in issues if i.severity == ValidationSeverity.CRITICAL]) == 0,
            issues=issues,
            fixed_data=result if issues else None
        )

    def _find_col(self, col_map: Dict[str, str], *keys: str) -> Optional[str]:
        """在列映射中查找列名（支持英文 key 和中文 label）"""
        for key in keys:
            # 尝试原始 key
            if key in col_map:
                return col_map[key]
            # 尝试 ColumnRegistry 中文 label
            label = ColumnRegistry.get_label(key)
            if label and label in col_map:
                return col_map[label]
            # 尝试 ColumnRegistry 反查
            eng = ColumnRegistry.key_from_label(key)
            if eng and eng in col_map:
                return col_map[eng]
        return None

    def _calculate_passenger_stats(self, rows: List[Dict], columns: List[str]) -> Dict[str, Any]:
        """从原始数据计算里程统计"""
        stats = {}

        # 查找列名（大小写不敏感）
        col_map = {c.upper(): c for c in columns}

        mileage_col = self._find_col(col_map, "MILEAGE", "TOTAL_MILEAGE")
        carry_col = self._find_col(col_map, "CARRY_MILEAGE", "TOTAL_CARRY_MILEAGE")

        if mileage_col:
            total = sum(float(r.get(mileage_col, 0) or 0) for r in rows)
            stats["total_mileage"] = round(total, 2)

        if carry_col:
            carry = sum(float(r.get(carry_col, 0) or 0) for r in rows)
            stats["carry_mileage"] = round(carry, 2)

        if "total_mileage" in stats and "carry_mileage" in stats:
            stats["empty_mileage"] = round(stats["total_mileage"] - stats["carry_mileage"], 2)
            if stats["total_mileage"] > 0:
                stats["utilization_rate"] = round(stats["carry_mileage"] / stats["total_mileage"] * 100, 2)

        # 车辆数和天数
        bus_agg = col_map.get("UNIQUE_BUSES")
        bus_col = self._find_col(col_map, "BUS_NO", "BUS_ID")
        if bus_agg:
            try:
                stats["unique_buses"] = max(int(float(r.get(bus_agg, 0) or 0)) for r in rows)
            except:
                pass
        elif bus_col:
            try:
                stats["unique_buses"] = len(set(r.get(bus_col) for r in rows if r.get(bus_col)))
            except:
                pass

        date_col = self._find_col(col_map, "JS_DATE", "OPERATE_DATE")
        if date_col:
            try:
                stats["unique_days"] = len(set(str(r.get(date_col))[:10] for r in rows if r.get(date_col)))
            except:
                pass

        return stats

    def _calculate_operation_stats(self, rows: List[Dict], columns: List[str]) -> Dict[str, Any]:
        """从原始数据计算订单统计"""
        stats = {}

        # 查找列名（大小写不敏感）
        col_map = {c.upper(): c for c in columns}

        total_col = self._find_col(col_map, "TOTAL_ORDERS", "FINISH_ORDER_COUNT", "订单数", "总订单数")
        completed_col = self._find_col(col_map, "COMPLETED_ORDERS", "TOTAL_FINISH_ORDERS", "完成订单数", "FINISHED_ORDERS")
        cancelled_col = self._find_col(col_map, "CANCELLED_ORDERS", "TOTAL_CANCEL_ORDERS", "取消订单数", "CANCEL_ORDERS")
        passenger_col = self._find_col(col_map, "TOTAL_PASSENGER", "PASSENGER", "乘客数", "总乘客数")

        if total_col:
            total = sum(float(r.get(total_col, 0) or 0) for r in rows)
            stats["total_orders"] = int(round(total, 0))

        if completed_col:
            completed = sum(float(r.get(completed_col, 0) or 0) for r in rows)
            stats["completed_orders"] = int(round(completed, 0))

        if cancelled_col:
            cancelled = sum(float(r.get(cancelled_col, 0) or 0) for r in rows)
            stats["cancelled_orders"] = int(round(cancelled, 0))

        if passenger_col:
            passengers = sum(float(r.get(passenger_col, 0) or 0) for r in rows)
            stats["total_passengers"] = int(round(passengers, 0))

        # 计算完成率
        if "completed_orders" in stats and "total_orders" in stats and stats["total_orders"] > 0:
            stats["completion_rate"] = round(stats["completed_orders"] / stats["total_orders"] * 100, 2)

        return stats


class ResultFixer:
    """
    结果修正器
    自动修复验证发现的问题
    """

    def __init__(self):
        self.validator = ResultValidator()

    def fix_and_validate(self, result_type: str, result: Dict[str, Any],
                          raw_data: Optional[Dict] = None,
                          max_retries: int = 2) -> Dict[str, Any]:
        """
        修正并验证结果

        Args:
            result_type: 结果类型
            result: 原始结果
            raw_data: 原始数据
            max_retries: 最大重试次数

        Returns:
            修正后的结果
        """
        current_result = result.copy()

        for attempt in range(max_retries + 1):
            validation = self.validator.validate(result_type, current_result, raw_data)

            if validation.is_valid and not validation.issues:
                print(f"[ResultFixer] {result_type} 验证通过，无需修复")
                return current_result

            if validation.fixed_data:
                print(f"[ResultFixer] {result_type} 应用自动修复 (尝试 {attempt + 1})")
                current_result = validation.fixed_data

                # 记录修复日志
                for issue in validation.issues:
                    print(f"[ResultFixer] {issue.severity.value}: {issue.field} - {issue.message}")

            # 如果没有关键问题，返回结果
            critical_issues = [i for i in validation.issues if i.severity == ValidationSeverity.CRITICAL]
            if not critical_issues:
                print(f"[ResultFixer] {result_type} 修复完成")
                return current_result

        # 超过最大重试次数，添加错误标记
        print(f"[ResultFixer] {result_type} 超过最大重试次数，标记为需要人工检查")
        current_result["_validation_errors"] = [
            {"field": i.field, "message": i.message}
            for i in validation.issues if i.severity == ValidationSeverity.CRITICAL
        ]

        return current_result


# 全局实例
result_fixer = ResultFixer()
result_validator = ResultValidator()


def validate_and_fix_result(result_type: str, result: Dict[str, Any],
                           raw_data: Optional[Dict] = None) -> Dict[str, Any]:
    """
    便捷函数：验证并修正结果

    Args:
        result_type: 结果类型 (passenger/operation)
        result: 分析结果
        raw_data: 原始查询数据

    Returns:
        验证并修正后的结果
    """
    return result_fixer.fix_and_validate(result_type, result, raw_data)


def generate_key_findings_from_stats(result_type: str, statistics: Dict[str, Any]) -> List[str]:
    """
    从统计数据自动生成关键发现 - 增强版，提供更详细的分析洞察

    Args:
        result_type: 结果类型
        statistics: 统计数据

    Returns:
        关键发现列表
    """
    findings = []

    if result_type == "passenger":
        total = statistics.get("total_mileage_km", 0)
        carry = statistics.get("carry_mileage_km", 0)
        rate = statistics.get("mileage_utilization_rate", 0)
        empty = statistics.get("empty_mileage_km", 0) or (total - carry if total > 0 else 0)
        unique_buses = statistics.get("unique_buses", 0)
        unique_days = statistics.get("unique_days", 0)

        if total > 0:
            # 1. 基础运营数据概览
            avg_mileage_per_bus = total / unique_buses if unique_buses > 0 else 0
            avg_mileage_per_day = total / unique_days if unique_days > 0 else 0

            findings.append(
                f"统计期间共运营 {unique_buses} 辆车，总里程 {total:.2f} km，"
                f"日均运营 {avg_mileage_per_day:.1f} km/天，单车平均 {avg_mileage_per_bus:.1f} km/辆"
            )

            # 2. 里程结构分析
            empty_rate = 100 - rate if rate > 0 else 0
            if rate > 0:
                findings.append(
                    f"载客里程 {carry:.2f} km（占比{rate:.1f}%），空驶里程 {empty:.2f} km（占比{empty_rate:.1f}%）"
                )

            # 3. 运营效率评估
            if rate >= 60:
                findings.append(f"里程利用率{rate:.1f}%，运营效率优秀，车辆资源得到充分利用")
            elif rate >= 40:
                findings.append(
                    f"里程利用率{rate:.1f}%，运营效率中等，空驶里程占比{empty_rate:.1f}%，"
                    f"建议优化线路调度减少空驶"
                )
            else:
                if carry > 0:
                    empty_ratio = empty / carry
                    findings.append(
                        f"里程利用率偏低（{rate:.1f}%），空驶里程占比高达{empty_rate:.1f}%，"
                        f"超过载客里程{empty_ratio:.2f}倍，存在显著优化空间"
                    )
                else:
                    findings.append(
                        f"里程利用率偏低（{rate:.1f}%），空驶里程占比高达{empty_rate:.1f}%，"
                        f"存在显著优化空间"
                    )

            # 4. 运营天数分析
            if unique_days > 1:
                findings.append(f"数据覆盖 {unique_days} 个运营日，日均总里程 {avg_mileage_per_day:.1f} km")

            # 5. 效率改进建议
            if rate < 50:
                findings.append(
                    "建议：优化车辆调度策略，减少空驶等待时间；"
                    "分析高峰时段运力配置，提升车辆载客率"
                )
            elif rate > 70:
                findings.append(
                    "建议：当前运营效率良好，可考虑适当增加班次或扩展服务区域；"
                    "关注司机工作时长，确保合规运营"
                )

    elif result_type == "operation":
        total = statistics.get("total_orders", 0)
        completed = statistics.get("completed_orders", 0)
        cancelled = statistics.get("cancelled_orders", 0)
        rate = statistics.get("completion_rate", 0)
        passengers = statistics.get("total_passengers", 0)
        avg_passengers = statistics.get("avg_passengers_per_order", 0)

        if total > 0:
            # 1. 订单规模概览
            findings.append(f"总订单数 {total} 单，完成订单 {completed} 单，取消订单 {cancelled} 单")

            # 2. 完成率评估
            if rate >= 95:
                findings.append(f"订单完成率 {rate:.1f}%，服务质量优秀，用户满意度高")
            elif rate >= 80:
                findings.append(f"订单完成率 {rate:.1f}%，服务质量良好，仍有提升空间")
            elif rate >= 60:
                findings.append(f"订单完成率 {rate:.1f}%，服务质量一般，建议关注取消原因")
            else:
                findings.append(f"订单完成率 {rate:.1f}%偏低，取消率高达{100-rate:.1f}%，需紧急排查问题")

            # 3. 客流分析
            if passengers > 0:
                findings.append(f"服务乘客总数 {passengers} 人，平均每单 {avg_passengers:.2f} 人")

            # 4. 改进建议
            if rate < 80:
                findings.append("建议：分析订单取消原因，优化车辆调度响应速度；提升服务可靠性")
            elif passengers > 0 and avg_passengers < 1.5:
                findings.append("建议：探索拼单模式或推广多人乘车优惠，提升单车载客效率")

    return findings
