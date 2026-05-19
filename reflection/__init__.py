"""
自我反思与修正系统 (Self-Reflection System)
实现 Agent 的自我检查、错误发现和自动修正能力
"""

import json
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class ReflectionSeverity(Enum):
    """反思发现的严重程度"""
    CRITICAL = "critical"    # 必须重新执行
    WARNING = "warning"      # 建议验证
    INFO = "info"            # 仅供参考


class ReflectionAction(Enum):
    """反思后的行动类型"""
    RETRY = "retry"                    # 重新执行
    REQUERY = "requery"                # 重新查询数据
    CROSS_VALIDATE = "cross_validate"  # 交叉验证
    ACCEPT = "accept"                  # 接受结果
    ADJUST_PARAMS = "adjust_params"    # 调整参数


@dataclass
class ReflectionIssue:
    """反思发现的问题"""
    severity: ReflectionSeverity
    category: str                      # 问题类别: data/anomaly/logic/consistency
    description: str
    evidence: Dict[str, Any]           # 证据数据
    suggested_action: ReflectionAction
    adjustment_params: Optional[Dict] = None  # 调整建议参数


@dataclass
class ReflectionResult:
    """反思结果"""
    has_issues: bool
    issues: List[ReflectionIssue]
    confidence: float                  # 0-1，结果可信度
    recommendation: ReflectionAction
    adjusted_plan: Optional[Dict] = None


class DataAnomalyDetector:
    """数据异常检测器"""

    def detect_anomalies(self, data: Dict[str, Any],
                        context: Optional[Dict] = None) -> List[ReflectionIssue]:
        """
        检测数据中的异常

        检测维度：
        1. 数值异常（突变、离群值）
        2. 逻辑异常（自相矛盾）
        3. 完整性异常（缺失、重复）
        4. 时序异常（时间序列的不连续）
        """
        issues = []
        rows = data.get("rows", [])
        columns = data.get("columns", [])

        if not rows:
            return issues

        # 1. 检测数值异常
        numeric_cols = self._get_numeric_columns(rows, columns)
        for col in numeric_cols:
            values = [float(r.get(col, 0) or 0) for r in rows if r.get(col) is not None]
            if values:
                issues.extend(self._check_outliers(col, values))

        # 2. 检测逻辑一致性
        issues.extend(self._check_logical_consistency(rows, columns, context))

        # 3. 检测数据完整性
        issues.extend(self._check_completeness(rows, columns))

        return issues

    def _get_numeric_columns(self, rows: List[Dict], columns: List[str]) -> List[str]:
        """识别数值型列"""
        numeric_cols = []
        if not rows:
            return numeric_cols

        sample_row = rows[0]
        for col in columns:
            val = sample_row.get(col)
            if isinstance(val, (int, float)):
                numeric_cols.append(col)
            elif isinstance(val, str):
                # 尝试解析为数字
                try:
                    float(val)
                    numeric_cols.append(col)
                except:
                    pass
        return numeric_cols

    def _check_outliers(self, column: str, values: List[float]) -> List[ReflectionIssue]:
        """使用IQR方法检测离群值"""
        issues = []
        if len(values) < 4:
            return issues

        sorted_vals = sorted(values)
        q1_idx = len(sorted_vals) // 4
        q3_idx = q1_idx * 3
        q1, q3 = sorted_vals[q1_idx], sorted_vals[q3_idx]
        iqr = q3 - q1

        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr

        outliers = [v for v in values if v < lower_bound or v > upper_bound]
        if outliers:
            # 检查是否是正常业务波动还是数据错误
            outlier_ratio = len(outliers) / len(values)
            if outlier_ratio > 0.2:  # 超过20%是异常值
                issues.append(ReflectionIssue(
                    severity=ReflectionSeverity.WARNING,
                    category="anomaly",
                    description=f"列 {column} 存在 {len(outliers)} 个离群值，占比 {outlier_ratio:.1%}",
                    evidence={
                        "column": column,
                        "outlier_count": len(outliers),
                        "outlier_ratio": outlier_ratio,
                        "sample_outliers": outliers[:5]
                    },
                    suggested_action=ReflectionAction.CROSS_VALIDATE
                ))

        return issues

    def _check_logical_consistency(self, rows: List[Dict], columns: List[str],
                                   context: Optional[Dict]) -> List[ReflectionIssue]:
        """检查逻辑一致性"""
        issues = []

        # 检查里程数据：载客里程不应超过总里程
        mileage_col = next((c for c in columns if c.upper() in ['MILEAGE', '总里程']), None)
        carry_col = next((c for c in columns if c.upper() in ['CARRY_MILEAGE', '载客里程']), None)

        if mileage_col and carry_col:
            inconsistent = 0
            for row in rows:
                total = float(row.get(mileage_col, 0) or 0)
                carry = float(row.get(carry_col, 0) or 0)
                if carry > total:
                    inconsistent += 1

            if inconsistent > 0:
                issues.append(ReflectionIssue(
                    severity=ReflectionSeverity.CRITICAL,
                    category="logic",
                    description=f"发现 {inconsistent} 条记录载客里程大于总里程",
                    evidence={
                        "inconsistent_count": inconsistent,
                        "total_records": len(rows)
                    },
                    suggested_action=ReflectionAction.REQUERY
                ))

        return issues

    def _check_completeness(self, rows: List[Dict], columns: List[str]) -> List[ReflectionIssue]:
        """检查数据完整性"""
        issues = []

        # 检查关键字段缺失
        key_fields = ['MILEAGE', 'CARRY_MILEAGE', 'JS_DATE', 'BUS_NO']
        for field in key_fields:
            field_col = next((c for c in columns if c.upper() == field), None)
            if field_col:
                missing = sum(1 for r in rows if r.get(field_col) is None)
                if missing > len(rows) * 0.1:  # 缺失超过10%
                    issues.append(ReflectionIssue(
                        severity=ReflectionSeverity.WARNING,
                        category="completeness",
                        description=f"字段 {field_col} 缺失 {missing}/{len(rows)} 条记录",
                        evidence={
                            "field": field_col,
                            "missing_count": missing,
                            "missing_ratio": missing / len(rows)
                        },
                        suggested_action=ReflectionAction.REQUERY
                    ))

        return issues


class SelfReflectionEngine:
    """
    自我反思引擎
    实现"发现异常 → 重新查询 → 交叉验证 → 确认结果"的完整流程
    """

    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        self.anomaly_detector = DataAnomalyDetector()
        self.reflection_history: List[ReflectionResult] = []
        self.max_reflection_rounds = 3

    async def reflect_and_correct(self,
                                   agent,
                                   task_description: str,
                                   current_result: Dict[str, Any],
                                   raw_data: Dict[str, Any],
                                   context: Optional[Dict] = None) -> Dict[str, Any]:
        """
        主入口：反思并修正结果

        完整流程：
        1. 分析当前结果和数据，发现问题
        2. 根据问题类型决定行动
        3. 执行修正（重新查询/交叉验证）
        4. 验证修正后的结果
        5. 如果仍有问题，重复最多3次
        """
        print(f"[SelfReflection] 开始反思流程，最大迭代次数: {self.max_reflection_rounds}")

        best_result = current_result
        best_confidence = 0.5

        for round_num in range(self.max_reflection_rounds):
            print(f"[SelfReflection] === 反思轮次 {round_num + 1} ===")

            # 步骤1: 反思当前状态
            reflection = await self._reflect_on_result(
                task_description, best_result, raw_data, context
            )

            self.reflection_history.append(reflection)

            if not reflection.has_issues:
                print(f"[SelfReflection] 结果验证通过，置信度: {reflection.confidence:.2f}")
                best_result["_reflection_meta"] = {
                    "rounds": round_num + 1,
                    "confidence": reflection.confidence,
                    "status": "accepted"
                }
                return best_result

            print(f"[SelfReflection] 发现 {len(reflection.issues)} 个问题，建议行动: {reflection.recommendation.value}")

            # 步骤2: 根据建议采取行动
            corrected_result, new_data = await self._execute_correction(
                agent, task_description, best_result, raw_data, reflection
            )

            if corrected_result:
                best_result = corrected_result
                if new_data:
                    raw_data = new_data

                # 评估置信度提升
                if reflection.confidence > best_confidence:
                    best_confidence = reflection.confidence

        # 超过最大反思次数
        print(f"[SelfReflection] 达到最大反思次数，返回最佳结果（置信度: {best_confidence:.2f}）")
        best_result["_reflection_meta"] = {
            "rounds": len(self.reflection_history),
            "confidence": best_confidence,
            "status": "max_rounds_reached",
            "issues": [i.description for i in self.reflection_history[-1].issues]
        }
        return best_result

    async def _reflect_on_result(self,
                                  task_description: str,
                                  result: Dict[str, Any],
                                  raw_data: Dict[str, Any],
                                  context: Optional[Dict]) -> ReflectionResult:
        """
        对当前结果进行深度反思
        结合统计验证 + LLM判断
        """
        issues = []

        # 1. 统计层面的异常检测
        data_issues = self.anomaly_detector.detect_anomalies(raw_data, context)
        issues.extend(data_issues)

        # 2. 结果内部一致性检查
        consistency_issues = self._check_result_consistency(result)
        issues.extend(consistency_issues)

        # 3. 业务逻辑合理性检查（使用LLM）
        if self.llm_client:
            business_issues = await self._llm_business_check(task_description, result, raw_data)
            issues.extend(business_issues)

        # 4. 计算置信度
        confidence = self._calculate_confidence(result, issues)

        # 5. 决定下一步行动
        recommendation = self._determine_action(issues, confidence)

        return ReflectionResult(
            has_issues=len(issues) > 0,
            issues=issues,
            confidence=confidence,
            recommendation=recommendation
        )

    def _check_result_consistency(self, result: Dict[str, Any]) -> List[ReflectionIssue]:
        """检查结果内部一致性"""
        issues = []
        stats = result.get("statistics", {})

        # 检查统计数据是否匹配
        total = stats.get("total_mileage_km", 0)
        carry = stats.get("carry_mileage_km", 0)
        empty = stats.get("empty_mileage_km", 0)

        if total > 0 and carry > 0 and empty > 0:
            # 检查总和是否匹配
            if abs(total - (carry + empty)) > 0.01:
                issues.append(ReflectionIssue(
                    severity=ReflectionSeverity.CRITICAL,
                    category="consistency",
                    description=f"里程数据不一致: 总里程({total}) ≠ 载客({carry}) + 空驶({empty}) = {carry + empty}",
                    evidence={
                        "total_mileage": total,
                        "carry_mileage": carry,
                        "empty_mileage": empty,
                        "sum": carry + empty
                    },
                    suggested_action=ReflectionAction.RETRY
                ))

        # 检查关键发现是否与统计数据匹配
        findings = result.get("key_findings", [])
        if total > 0 and not findings:
            issues.append(ReflectionIssue(
                severity=ReflectionSeverity.WARNING,
                category="completeness",
                description="有统计数据但缺少关键发现",
                evidence={"statistics": stats},
                suggested_action=ReflectionAction.RETRY
            ))

        return issues

    async def _llm_business_check(self, task_description: str,
                                   result: Dict[str, Any],
                                   raw_data: Dict[str, Any]) -> List[ReflectionIssue]:
        """使用LLM进行业务逻辑合理性检查"""
        issues = []

        stats = result.get("statistics", {})

        # 构建检查prompt
        check_prompt = f"""请检查以下数据分析结果的合理性，从业务角度判断是否有异常。

任务: {task_description}

统计数据:
{json.dumps(stats, ensure_ascii=False, indent=2)}

请检查以下方面并输出JSON格式:
1. 数值范围是否合理（如利用率是否超过100%，里程是否为负数等）
2. 业务逻辑是否合理（如工作日订单是否显著高于周末）
3. 是否有明显的数据质量问题

输出格式:
{{
    "is_reasonable": true/false,
    "issues": [
        {{
            "severity": "critical/warning/info",
            "description": "问题描述",
            "suggestion": "建议"
        }}
    ],
    "confidence": 0-1  # 对结果的信心程度
}}"""

        try:
            response = await self.llm_client(check_prompt)
            # 解析JSON响应
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                check_result = json.loads(response[json_start:json_end])

                if not check_result.get("is_reasonable", True):
                    for issue_data in check_result.get("issues", []):
                        issues.append(ReflectionIssue(
                            severity=ReflectionSeverity(issue_data.get("severity", "warning")),
                            category="business_logic",
                            description=issue_data.get("description", ""),
                            evidence={"llm_check": check_result},
                            suggested_action=ReflectionAction.CROSS_VALIDATE
                        ))
        except Exception as e:
            print(f"[SelfReflection] LLM业务检查失败: {e}")

        return issues

    def _calculate_confidence(self, result: Dict[str, Any], issues: List[ReflectionIssue]) -> float:
        """计算结果置信度"""
        base_confidence = 0.8

        # 根据问题调整
        for issue in issues:
            if issue.severity == ReflectionSeverity.CRITICAL:
                base_confidence -= 0.3
            elif issue.severity == ReflectionSeverity.WARNING:
                base_confidence -= 0.1
            elif issue.severity == ReflectionSeverity.INFO:
                base_confidence -= 0.02

        # 检查结果完整性
        stats = result.get("statistics", {})
        required_fields = ["total_mileage_km", "carry_mileage_km", "mileage_utilization_rate"]
        missing = sum(1 for f in required_fields if f not in stats or stats[f] == 0)
        base_confidence -= missing * 0.1

        return max(0.1, min(1.0, base_confidence))

    def _determine_action(self, issues: List[ReflectionIssue], confidence: float) -> ReflectionAction:
        """根据问题决定行动"""
        critical_count = sum(1 for i in issues if i.severity == ReflectionSeverity.CRITICAL)

        if critical_count > 0:
            return ReflectionAction.REQUERY
        elif confidence < 0.5:
            return ReflectionAction.CROSS_VALIDATE
        elif any(i.suggested_action == ReflectionAction.REQUERY for i in issues):
            return ReflectionAction.REQUERY
        else:
            return ReflectionAction.ACCEPT

    async def _execute_correction(self, agent, task_description: str,
                                   current_result: Dict[str, Any],
                                   raw_data: Dict[str, Any],
                                   reflection: ReflectionResult) -> Tuple[Optional[Dict], Optional[Dict]]:
        """
        执行修正操作
        返回: (修正后的结果, 新查询的数据)
        """
        action = reflection.recommendation

        if action == ReflectionAction.ACCEPT:
            return current_result, None

        elif action == ReflectionAction.REQUERY:
            print(f"[SelfReflection] 执行重新查询...")
            # 调整查询参数（如添加更严格的过滤条件）
            adjusted_params = self._adjust_query_params(reflection.issues)
            return await self._requery_with_adjustment(agent, task_description, adjusted_params)

        elif action == ReflectionAction.CROSS_VALIDATE:
            print(f"[SelfReflection] 执行交叉验证...")
            return await self._cross_validate(agent, task_description, current_result, raw_data)

        elif action == ReflectionAction.RETRY:
            print(f"[SelfReflection] 重新分析现有数据...")
            return await self._retry_analysis(agent, task_description, raw_data)

        return None, None

    def _adjust_query_params(self, issues: List[ReflectionIssue]) -> Dict:
        """根据问题调整查询参数"""
        params = {}

        for issue in issues:
            if issue.category == "completeness":
                # 数据不完整，添加更多过滤条件
                params["strict_mode"] = True
                params["exclude_nulls"] = True
            elif issue.category == "anomaly":
                # 有异常值，添加范围限制
                params["outlier_filter"] = True
                params["iqr_multiplier"] = 2.0  # 更宽松的离群值判定

        return params

    async def _requery_with_adjustment(self, agent, task_description: str,
                                        params: Dict) -> Tuple[Optional[Dict], Optional[Dict]]:
        """使用调整后的参数重新查询"""
        # 构建新的任务描述，包含调整参数
        adjusted_task = f"{task_description}\n[查询优化参数: {json.dumps(params, ensure_ascii=False)}]"

        try:
            # 重新执行查询（调用agent的重新查询方法）
            from graph.state import Message
            msg = Message(
                content=adjusted_task,
                from_agent="task_manager",
                to_agent=agent.name
            )
            new_result = await agent.process_message(msg)

            # 提取新的原始数据
            new_raw_data = {
                "rows": new_result.get("_debug", {}).get("raw_rows", []),
                "columns": new_result.get("_debug", {}).get("columns", [])
            }

            return new_result, new_raw_data
        except Exception as e:
            print(f"[SelfReflection] 重新查询失败: {e}")
            return None, None

    async def _cross_validate(self, agent, task_description: str,
                              current_result: Dict[str, Any],
                              raw_data: Dict[str, Any]) -> Tuple[Optional[Dict], Optional[Dict]]:
        """
        交叉验证：用不同方法验证同一数据
        例如：对比两个不同SQL查询的结果
        """
        print(f"[SelfReflection] 使用替代查询进行交叉验证...")

        # 构建验证查询（简化版本，使用不同的聚合方式）
        verification_task = f"验证以下数据的准确性: {task_description}\n"
        f"原始统计: {json.dumps(current_result.get('statistics', {}), ensure_ascii=False)}"

        try:
            from graph.state import Message
            msg = Message(
                content=verification_task,
                from_agent="task_manager",
                to_agent=agent.name
            )
            verify_result = await agent.process_message(msg)

            # 对比两个结果
            original_stats = current_result.get("statistics", {})
            verify_stats = verify_result.get("statistics", {})

            # 检查关键指标是否一致（允许5%误差）
            match_count = 0
            total_count = 0
            for key in ["total_mileage_km", "carry_mileage_km"]:
                if key in original_stats and key in verify_stats:
                    total_count += 1
                    orig_val = float(original_stats[key])
                    verify_val = float(verify_stats[key])
                    if orig_val > 0:
                        diff_ratio = abs(orig_val - verify_val) / orig_val
                        if diff_ratio < 0.05:
                            match_count += 1

            if total_count > 0 and match_count / total_count >= 0.8:
                print(f"[SelfReflection] 交叉验证通过 ({match_count}/{total_count})")
                # 合并结果，取平均值
                merged = self._merge_results(current_result, verify_result)
                return merged, None
            else:
                print(f"[SelfReflection] 交叉验证未通过，保留原始结果")
                return current_result, None

        except Exception as e:
            print(f"[SelfReflection] 交叉验证失败: {e}")
            return current_result, None

    def _merge_results(self, result1: Dict, result2: Dict) -> Dict:
        """合并两个验证结果"""
        merged = result1.copy()

        stats1 = result1.get("statistics", {})
        stats2 = result2.get("statistics", {})

        # 对数值字段取平均
        merged_stats = {}
        all_keys = set(stats1.keys()) | set(stats2.keys())
        for key in all_keys:
            val1 = stats1.get(key, 0)
            val2 = stats2.get(key, 0)
            if isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
                merged_stats[key] = round((val1 + val2) / 2, 2)
            else:
                merged_stats[key] = val1 or val2

        merged["statistics"] = merged_stats
        merged["_cross_validated"] = True
        return merged

    async def _retry_analysis(self, agent, task_description: str,
                              raw_data: Dict[str, Any]) -> Tuple[Optional[Dict], None]:
        """使用现有数据重新分析"""
        # 直接调用agent的analyze_data方法
        if hasattr(agent, 'analyze_data'):
            try:
                new_analysis = await agent.analyze_data(task_description, raw_data)

                # 更新结果中的分析部分
                result = {
                    "analysis": new_analysis.get("analysis", {}),
                    "statistics": new_analysis.get("analysis", {}).get("statistics", {}),
                    "key_findings": new_analysis.get("analysis", {}).get("key_findings", []),
                    "_reanalyzed": True
                }
                return result, None
            except Exception as e:
                print(f"[SelfReflection] 重新分析失败: {e}")

        return None, None


# 便捷函数
def create_reflection_engine(llm_client=None) -> SelfReflectionEngine:
    """创建反思引擎实例"""
    return SelfReflectionEngine(llm_client)
