"""
反馈学习系统
实现从用户反馈中学习和策略优化
支持持久化存储
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
import json
import os
import numpy as np

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_anthropic import ChatAnthropic

from config.settings import settings


@dataclass
class FeedbackRecord:
    """反馈记录"""
    id: str
    session_id: str
    query: str
    agent_response: Dict[str, Any]
    feedback_text: str
    rating: Optional[int] = None  # 1-5 评分
    feedback_type: str = "implicit"  # implicit, explicit, correction
    improvement_areas: List[str] = field(default_factory=list)
    learned_lesson: Optional[str] = None
    applied: bool = False
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        """转换为字典（可JSON序列化）"""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "query": self.query,
            "agent_response": self.agent_response,
            "feedback_text": self.feedback_text,
            "rating": self.rating,
            "feedback_type": self.feedback_type,
            "improvement_areas": self.improvement_areas,
            "learned_lesson": self.learned_lesson,
            "applied": self.applied,
            "timestamp": self.timestamp.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "FeedbackRecord":
        """从字典创建实例"""
        data = data.copy()
        if "timestamp" in data and isinstance(data["timestamp"], str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)


@dataclass
class StrategyAdjustment:
    """策略调整"""
    parameter: str
    old_value: Any
    new_value: Any
    reason: str
    success_rate_before: float
    success_rate_after: Optional[float] = None
    applied_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "parameter": self.parameter,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "reason": self.reason,
            "success_rate_before": self.success_rate_before,
            "success_rate_after": self.success_rate_after,
            "applied_at": self.applied_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "StrategyAdjustment":
        """从字典创建实例"""
        data = data.copy()
        if "applied_at" in data and isinstance(data["applied_at"], str):
            data["applied_at"] = datetime.fromisoformat(data["applied_at"])
        return cls(**data)


class FeedbackLearningSystem:
    """
    反馈学习系统
    收集反馈、识别模式、调整策略
    支持持久化存储
    """

    def __init__(self, persist_path: str = None):
        self.llm = ChatAnthropic(
            model=settings.model_name,
            anthropic_api_url=settings.model_base_url,
            anthropic_api_key=settings.model_api_key,
            temperature=0.3,
            max_tokens=2048
        )

        # 持久化路径
        self.persist_path = persist_path or os.path.join(
            os.path.dirname(__file__), '..', 'data', 'learning_data.json'
        )

        self.feedback_history: List[FeedbackRecord] = []
        self.strategy_adjustments: List[StrategyAdjustment] = []
        self.performance_metrics: Dict[str, List[float]] = {
            "accuracy": [],
            "user_satisfaction": [],
            "task_completion": []
        }

        # 默认策略参数
        self.default_strategy_params = {
            "sql_generation_temperature": 0.3,
            "max_retry_attempts": 3,
            "context_window_size": 5,
            "confidence_threshold": 0.7,
            "ask_user_threshold": 0.5
        }

        # 当前策略参数（从持久化加载或默认值）
        self.strategy_params = self.default_strategy_params.copy()

        # 加载历史数据
        self._load_data()

    def _load_data(self):
        """从磁盘加载学习数据"""
        if os.path.exists(self.persist_path):
            try:
                with open(self.persist_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # 加载策略参数
                if 'strategy_params' in data:
                    self.strategy_params.update(data['strategy_params'])
                    print(f"[Learning] 已加载策略参数: {self.strategy_params}")

                # 加载反馈历史
                if 'feedback_history' in data:
                    self.feedback_history = [
                        FeedbackRecord.from_dict(r)
                        for r in data['feedback_history']
                    ]

                # 加载策略调整历史
                if 'strategy_adjustments' in data:
                    self.strategy_adjustments = [
                        StrategyAdjustment.from_dict(a)
                        for a in data['strategy_adjustments']
                    ]

                # 加载性能指标
                if 'performance_metrics' in data:
                    self.performance_metrics = data['performance_metrics']

                print(f"[Learning] 已加载 {len(self.feedback_history)} 条反馈记录, "
                      f"{len(self.strategy_adjustments)} 条策略调整")

            except Exception as e:
                print(f"[Learning] 加载数据失败: {e}，使用默认值")
                self._reset_to_defaults()
        else:
            print("[Learning] 未找到历史数据，使用默认策略")
            self._reset_to_defaults()

    def _save_data(self):
        """保存学习数据到磁盘"""
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)

            data = {
                'strategy_params': self.strategy_params,
                'feedback_history': [r.to_dict() for r in self.feedback_history],
                'strategy_adjustments': [a.to_dict() for a in self.strategy_adjustments],
                'performance_metrics': self.performance_metrics,
                'saved_at': datetime.now().isoformat()
            }

            with open(self.persist_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"[Learning] 数据已保存: {self.persist_path}")
        except Exception as e:
            print(f"[Learning] 保存数据失败: {e}")

    def _reset_to_defaults(self):
        """重置为默认策略"""
        self.strategy_params = self.default_strategy_params.copy()
        self.feedback_history = []
        self.strategy_adjustments = []
        self.performance_metrics = {
            "accuracy": [],
            "user_satisfaction": [],
            "task_completion": []
        }

    def _persist_if_needed(self):
        """根据条件触发持久化"""
        # 每5条新反馈保存一次
        if len(self.feedback_history) % 5 == 0:
            self._save_data()

    async def process_feedback(
        self,
        session_id: str,
        query: str,
        agent_response: Dict[str, Any],
        feedback: str,
        rating: int = None
    ) -> FeedbackRecord:
        """
        处理用户反馈
        """
        # 生成反馈ID
        feedback_id = f"fb_{datetime.now().timestamp()}"

        # 分析反馈内容
        analysis = await self._analyze_feedback(feedback, agent_response)

        record = FeedbackRecord(
            id=feedback_id,
            session_id=session_id,
            query=query,
            agent_response=agent_response,
            feedback_text=feedback,
            rating=rating,
            feedback_type=analysis.get("type", "implicit"),
            improvement_areas=analysis.get("improvement_areas", []),
            learned_lesson=analysis.get("lesson")
        )

        self.feedback_history.append(record)

        print(f"[Learning] 记录反馈: {feedback_id}")
        print(f"  类型: {record.feedback_type}")
        print(f"  改进领域: {record.improvement_areas}")

        # 检查是否需要调整策略
        await self._evaluate_strategy_adjustment()

        # 触发持久化
        self._persist_if_needed()

        return record

    async def _analyze_feedback(
        self,
        feedback: str,
        agent_response: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        使用 LLM 分析反馈内容
        """
        prompt = f"""分析以下用户反馈，提取关键信息。

Agent 响应:
{json.dumps(agent_response, ensure_ascii=False)[:500]}

用户反馈:
{feedback}

请分析:
1. 反馈类型 (positive/negative/correction/question)
2. 改进领域 (如: sql_generation, analysis, communication, speed)
3. 可学习的经验教训
4. 建议的参数调整

输出格式 (JSON):
{{
    "type": "feedback_type",
    "sentiment": "positive/negative/neutral",
    "improvement_areas": ["area1", "area2"],
    "lesson": "学到的经验教训",
    "suggested_adjustments": {{
        "parameter_name": "suggested_value"
    }}
}}"""

        messages = [
            SystemMessage(content="你是一个反馈分析专家。深入分析用户反馈，提取可学习的知识。"),
            HumanMessage(content=prompt)
        ]

        try:
            response = await self.llm.ainvoke(messages)
            content = response.content

            # 提取 JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            return json.loads(content)
        except Exception as e:
            print(f"[Learning] 反馈分析失败: {e}")
            return {
                "type": "implicit",
                "improvement_areas": ["general"],
                "lesson": None
            }

    async def _evaluate_strategy_adjustment(self):
        """
        评估是否需要调整策略
        """
        # 获取最近的反馈
        recent_feedback = self.feedback_history[-20:]

        if len(recent_feedback) < 10:
            return  # 数据不足

        # 计算满意度趋势
        negative_ratio = sum(
            1 for f in recent_feedback
            if f.feedback_type in ["negative", "correction"]
        ) / len(recent_feedback)

        print(f"[Learning] 近期负面反馈比例: {negative_ratio:.2f}")

        # 如果负面反馈超过阈值，考虑调整策略
        if negative_ratio > 0.3:
            await self._adjust_strategy(recent_feedback)

    async def _adjust_strategy(self, feedback_batch: List[FeedbackRecord]):
        """
        基于反馈调整策略
        """
        # 识别主要问题领域
        area_counts = {}
        for f in feedback_batch:
            for area in f.improvement_areas:
                area_counts[area] = area_counts.get(area, 0) + 1

        if not area_counts:
            return

        # 找出最严重的问题领域
        worst_area = max(area_counts, key=area_counts.get)

        print(f"[Learning] 识别问题领域: {worst_area}")

        # 根据问题领域调整参数
        adjustment = None

        if worst_area == "sql_generation":
            old_temp = self.strategy_params["sql_generation_temperature"]
            new_temp = min(old_temp + 0.1, 0.7)  # 增加温度以增加创造性
            adjustment = StrategyAdjustment(
                parameter="sql_generation_temperature",
                old_value=old_temp,
                new_value=new_temp,
                reason="SQL生成错误率较高，增加创造性",
                success_rate_before=self._calculate_recent_success_rate()
            )
            self.strategy_params["sql_generation_temperature"] = new_temp

        elif worst_area == "analysis":
            old_window = self.strategy_params["context_window_size"]
            new_window = min(old_window + 2, 10)  # 增加上下文窗口
            adjustment = StrategyAdjustment(
                parameter="context_window_size",
                old_value=old_window,
                new_value=new_window,
                reason="分析质量不足，增加上下文信息",
                success_rate_before=self._calculate_recent_success_rate()
            )
            self.strategy_params["context_window_size"] = new_window

        elif worst_area == "confidence":
            old_threshold = self.strategy_params["confidence_threshold"]
            new_threshold = max(old_threshold - 0.1, 0.5)  # 降低阈值，更频繁地询问用户
            adjustment = StrategyAdjustment(
                parameter="confidence_threshold",
                old_value=old_threshold,
                new_value=new_threshold,
                reason="过度自信导致错误，降低阈值增加确认",
                success_rate_before=self._calculate_recent_success_rate()
            )
            self.strategy_params["confidence_threshold"] = new_threshold

        if adjustment:
            self.strategy_adjustments.append(adjustment)
            print(f"[Learning] 策略调整: {adjustment.parameter}")
            print(f"  {adjustment.old_value} -> {adjustment.new_value}")

    def _calculate_recent_success_rate(self) -> float:
        """计算近期成功率"""
        recent = self.feedback_history[-20:]
        if not recent:
            return 1.0

        positive = sum(
            1 for f in recent
            if f.feedback_type in ["positive", "implicit"]
        )
        return positive / len(recent)

    def get_learned_strategies(self) -> Dict[str, Any]:
        """获取学习到的策略"""
        return {
            "current_params": self.strategy_params,
            "adjustment_history": [
                {
                    "parameter": adj.parameter,
                    "change": f"{adj.old_value} -> {adj.new_value}",
                    "reason": adj.reason,
                    "applied_at": adj.applied_at.isoformat()
                }
                for adj in self.strategy_adjustments[-10:]
            ],
            "performance_trends": {
                metric: {
                    "recent_avg": np.mean(values[-10:]) if values else 0,
                    "trend": "up" if len(values) > 5 and np.mean(values[-5:]) > np.mean(values[-10:-5]) else "stable"
                }
                for metric, values in self.performance_metrics.items()
            }
        }

    async def generate_improvement_report(self) -> str:
        """生成改进报告"""
        if len(self.feedback_history) < 5:
            return "反馈数据不足，无法生成报告。"

        # 统计反馈分布
        type_counts = {}
        area_counts = {}

        for f in self.feedback_history:
            type_counts[f.feedback_type] = type_counts.get(f.feedback_type, 0) + 1
            for area in f.improvement_areas:
                area_counts[area] = area_counts.get(area, 0) + 1

        # 计算趋势
        recent_rate = self._calculate_recent_success_rate()

        report = f"""# 学习改进报告

## 反馈统计
- 总反馈数: {len(self.feedback_history)}
- 近期成功率: {recent_rate:.1%}

## 反馈类型分布
{chr(10).join([f"- {t}: {c}" for t, c in type_counts.items()])}

## 主要改进领域
{chr(10).join([f"- {a}: {c}次" for a, c in sorted(area_counts.items(), key=lambda x: x[1], reverse=True)[:5]])}

## 策略调整记录
{chr(10).join([f"- {adj.applied_at.strftime('%Y-%m-%d')}: {adj.parameter} ({adj.old_value} -> {adj.new_value})" for adj in self.strategy_adjustments[-5:]])}

## 当前策略参数
{json.dumps(self.strategy_params, indent=2)}
"""

        return report

    def get_strategy_params(self) -> Dict[str, Any]:
        """获取当前策略参数"""
        return self.strategy_params.copy()

    def update_performance_metric(self, metric: str, value: float):
        """更新性能指标"""
        if metric in self.performance_metrics:
            self.performance_metrics[metric].append(value)
            # 保留最近100条记录
            self.performance_metrics[metric] = self.performance_metrics[metric][-100:]


# 全局学习系统实例
learning_system = FeedbackLearningSystem()
