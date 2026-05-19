"""
评估框架
实现自动化评估和性能监控
"""

from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
import json
import asyncio

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_anthropic import ChatAnthropic

from config.settings import settings


@dataclass
class EvaluationResult:
    """评估结果"""
    metric_name: str
    score: float  # 0-1
    details: str
    threshold: float
    passed: bool


@dataclass
class TestCase:
    """测试用例"""
    id: str
    name: str
    query: str
    expected_result: Dict[str, Any]
    evaluation_criteria: List[str]
    tags: List[str]


class EvaluationFramework:
    """
    评估框架
    自动化测试和性能评估
    """

    def __init__(self):
        self.llm = ChatAnthropic(
            model=settings.model_name,
            anthropic_api_url=settings.model_base_url,
            anthropic_api_key=settings.model_api_key,
            temperature=0.1,
            max_tokens=1024
        )

        self.test_cases: List[TestCase] = []
        self.evaluation_history: List[Dict] = []
        self.custom_metrics: Dict[str, Callable] = {}

    def register_test_case(
        self,
        name: str,
        query: str,
        expected_result: Dict[str, Any],
        criteria: List[str] = None,
        tags: List[str] = None
    ) -> str:
        """
        注册测试用例
        """
        test_id = f"test_{datetime.now().timestamp()}"

        test_case = TestCase(
            id=test_id,
            name=name,
            query=query,
            expected_result=expected_result,
            evaluation_criteria=criteria or ["accuracy", "completeness"],
            tags=tags or []
        )

        self.test_cases.append(test_case)
        print(f"[Eval] 注册测试用例: {name}")
        return test_id

    def register_metric(self, name: str, evaluator: Callable):
        """注册自定义评估指标"""
        self.custom_metrics[name] = evaluator

    async def evaluate_response(
        self,
        query: str,
        actual_response: Dict[str, Any],
        expected_response: Dict[str, Any] = None,
        criteria: List[str] = None
    ) -> List[EvaluationResult]:
        """
        评估单个响应
        """
        results = []
        criteria = criteria or ["accuracy", "completeness", "relevance"]

        for criterion in criteria:
            if criterion in self.custom_metrics:
                # 使用自定义评估器
                score = await self.custom_metrics[criterion](
                    query, actual_response, expected_response
                )
                results.append(EvaluationResult(
                    metric_name=criterion,
                    score=score,
                    details=f"Custom {criterion} evaluation",
                    threshold=0.7,
                    passed=score >= 0.7
                ))
            else:
                # 使用 LLM 评估
                result = await self._llm_evaluate(
                    criterion, query, actual_response, expected_response
                )
                results.append(result)

        # 记录评估历史
        self.evaluation_history.append({
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "criteria": criteria,
            "results": [
                {
                    "metric": r.metric_name,
                    "score": r.score,
                    "passed": r.passed
                }
                for r in results
            ]
        })

        return results

    async def _llm_evaluate(
        self,
        criterion: str,
        query: str,
        actual: Dict[str, Any],
        expected: Dict[str, Any]
    ) -> EvaluationResult:
        """使用 LLM 评估"""

        prompt = f"""请评估以下回答的 {criterion}。

查询: {query}

实际回答:
{json.dumps(actual, ensure_ascii=False, indent=2)[:1000]}

{f"期望回答:\n{json.dumps(expected, ensure_ascii=False, indent=2)[:500]}" if expected else ""}

请给出 0-1 的分数（1为最好），并简要说明理由。

输出格式:
分数: [0.0-1.0]
理由: [简要说明]
通过: [是/否，基于阈值0.7]"""

        messages = [
            SystemMessage(content=f"你是一个严格的评估专家，评估回答的 {criterion}。"),
            HumanMessage(content=prompt)
        ]

        try:
            response = await self.llm.ainvoke(messages)
            content = response.content

            # 解析分数
            score = 0.5
            if "分数:" in content:
                score_str = content.split("分数:")[1].split("\n")[0].strip()
                try:
                    score = float(score_str)
                except:
                    pass

            # 解析通过状态
            passed = score >= 0.7
            if "通过:" in content:
                passed_str = content.split("通过:")[1].strip().lower()
                passed = "是" in passed_str or "yes" in passed_str or "true" in passed_str

            return EvaluationResult(
                metric_name=criterion,
                score=score,
                details=content,
                threshold=0.7,
                passed=passed
            )

        except Exception as e:
            return EvaluationResult(
                metric_name=criterion,
                score=0.0,
                details=f"评估失败: {e}",
                threshold=0.7,
                passed=False
            )

    async def run_test_suite(
        self,
        test_function: Callable,
        test_cases: List[TestCase] = None
    ) -> Dict[str, Any]:
        """
        运行测试套件
        """
        cases = test_cases or self.test_cases

        if not cases:
            return {"error": "没有测试用例"}

        results = []

        for test_case in cases:
            print(f"[Eval] 运行测试: {test_case.name}")

            try:
                # 执行测试
                actual_result = await test_function(test_case.query)

                # 评估结果
                eval_results = await self.evaluate_response(
                    test_case.query,
                    actual_result,
                    test_case.expected_result,
                    test_case.evaluation_criteria
                )

                results.append({
                    "test_id": test_case.id,
                    "name": test_case.name,
                    "passed": all(r.passed for r in eval_results),
                    "evaluations": [
                        {
                            "metric": r.metric_name,
                            "score": r.score,
                            "passed": r.passed
                        }
                        for r in eval_results
                    ]
                })

            except Exception as e:
                results.append({
                    "test_id": test_case.id,
                    "name": test_case.name,
                    "passed": False,
                    "error": str(e)
                })

        # 计算总体统计
        total = len(results)
        passed = sum(1 for r in results if r["passed"])

        return {
            "total_tests": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": passed / total if total > 0 else 0,
            "results": results,
            "run_at": datetime.now().isoformat()
        }

    def get_performance_report(self) -> Dict[str, Any]:
        """获取性能报告"""
        if not self.evaluation_history:
            return {"message": "暂无评估数据"}

        # 按指标聚合
        by_metric = {}
        for eval_record in self.evaluation_history:
            for result in eval_record["results"]:
                metric = result["metric"]
                if metric not in by_metric:
                    by_metric[metric] = []
                by_metric[metric].append(result["score"])

        # 计算统计
        stats = {}
        for metric, scores in by_metric.items():
            stats[metric] = {
                "count": len(scores),
                "avg_score": sum(scores) / len(scores),
                "min_score": min(scores),
                "max_score": max(scores),
                "recent_avg": sum(scores[-10:]) / min(len(scores), 10) if scores else 0
            }

        return {
            "total_evaluations": len(self.evaluation_history),
            "metric_stats": stats,
            "trend": "improving" if self._is_improving() else "stable"
        }

    def _is_improving(self) -> bool:
        """判断是否正在改进"""
        if len(self.evaluation_history) < 20:
            return False

        recent = self.evaluation_history[-10:]
        earlier = self.evaluation_history[-20:-10]

        recent_scores = [
            sum(r["score"] for r in e["results"]) / len(e["results"])
            for e in recent
        ]
        earlier_scores = [
            sum(r["score"] for r in e["results"]) / len(e["results"])
            for e in earlier
        ]

        return sum(recent_scores) / len(recent_scores) > sum(earlier_scores) / len(earlier_scores)

    def export_results(self, filepath: str):
        """导出评估结果"""
        data = {
            "test_cases": [
                {
                    "id": tc.id,
                    "name": tc.name,
                    "query": tc.query,
                    "criteria": tc.evaluation_criteria,
                    "tags": tc.tags
                }
                for tc in self.test_cases
            ],
            "evaluation_history": self.evaluation_history,
            "performance_report": self.get_performance_report()
        }

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[Eval] 评估结果已导出: {filepath}")
        except Exception as e:
            print(f"[Eval] 导出失败: {e}")
            raise


# 全局评估框架实例
evaluator = EvaluationFramework()
