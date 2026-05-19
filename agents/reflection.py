"""
自我反思模块
实现 Agent 的自我评估、错误检测和策略调整
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_anthropic import ChatAnthropic

from config.settings import settings


@dataclass
class ReflectionResult:
    """反思结果"""
    should_backtrack: bool          # 是否需要回退
    backtrack_to_step: int          # 回退到哪个步骤
    reflection_reason: str          # 反思原因
    improvement_suggestion: str     # 改进建议
    confidence_score: float         # 信心分数 (0-1)


class ReflectionModule:
    """
    自我反思模块
    用于评估当前思考过程，检测错误并建议改进
    """

    def __init__(self):
        self.llm = ChatAnthropic(
            model=settings.model_name,
            anthropic_api_url=settings.model_base_url,
            anthropic_api_key=settings.model_api_key,
            temperature=0.2,  # 低温度确保反思的稳定性
            max_tokens=2048
        )

        self.reflection_history: List[Dict] = []

    async def reflect(
        self,
        current_step: Any,  # ThoughtAction
        thought_history: List[Any],
        expected_outcome: Optional[str] = None
    ) -> ReflectionResult:
        """
        对当前步骤进行反思
        """
        # 构建反思 prompt
        reflection_prompt = self._build_reflection_prompt(
            current_step, thought_history, expected_outcome
        )

        messages = [
            SystemMessage(content="""你是一个严格的自我反思系统。你的任务是评估AI助手的思考过程，检测潜在错误并提出改进建议。

反思原则:
1. 检查逻辑一致性：当前步骤是否与之前步骤矛盾？
2. 检查信息充分性：是否有足够信息支持当前结论？
3. 检查效率：是否存在重复或冗余的思考？
4. 检查目标对齐：当前步骤是否朝着解决问题推进？
5. 检查错误累积：之前的错误是否被带到当前步骤？"""),
            HumanMessage(content=reflection_prompt)
        ]

        response = await self.llm.ainvoke(messages)

        # 解析反思结果
        return self._parse_reflection(response.content, current_step.step_number)

    def _build_reflection_prompt(
        self,
        current_step: Any,
        thought_history: List[Any],
        expected_outcome: Optional[str]
    ) -> str:
        """构建反思 prompt"""

        # 构建历史步骤文本
        history_text = ""
        for step in thought_history[-5:]:
            history_text += f"""
Step {step.step_number}:
- Thought: {step.thought}
- Action: {step.action.value}
- Input: {json.dumps(step.action_input, ensure_ascii=False)}
- Observation: {step.observation or 'N/A'}
"""

        current_text = f"""
当前步骤 (Step {current_step.step_number}):
- Thought: {current_step.thought}
- Action: {current_step.action.value}
- Input: {json.dumps(current_step.action_input, ensure_ascii=False)}
- Observation: {current_step.observation or '等待中'}
"""

        expected_text = f"\n预期目标: {expected_outcome}" if expected_outcome else ""

        return f"""请对以下思考过程进行深度反思。

问题背景:
这是一个数据分析任务，Agent 正在通过多步骤推理来回答用户查询。

历史步骤:
{history_text}

{current_text}
{expected_text}

请按以下格式输出反思结果:

## 逻辑一致性检查
- 一致性评估: [高/中/低]
- 发现的矛盾: [如有]

## 信息充分性评估
- 信息充分性: [充分/不足/不确定]
- 缺失信息: [列出缺失的关键信息]

## 错误检测
- 检测到的错误: [如有，描述具体错误]
- 错误严重程度: [轻微/中等/严重]

## 改进建议
- 是否需要回退: [是/否]
- 如需回退，回退到步骤: [步骤编号或保持当前]
- 改进建议: [具体建议]

## 信心分数
- 当前步骤信心: [0.0-1.0]

## 最终决策
- should_backtrack: true/false
- backtrack_to_step: [步骤编号]
- reflection_reason: [简要说明]
- improvement_suggestion: [具体建议]
- confidence_score: [0.0-1.0]
"""

    def _parse_reflection(self, content: str, current_step_number: int) -> ReflectionResult:
        """解析 LLM 的反思结果"""

        # 默认结果
        result = ReflectionResult(
            should_backtrack=False,
            backtrack_to_step=current_step_number,
            reflection_reason="",
            improvement_suggestion="",
            confidence_score=0.8
        )

        # 尝试提取关键字段
        try:
            if "should_backtrack:" in content.lower():
                backtrack_str = content.lower().split("should_backtrack:")[1].split("\n")[0].strip()
                result.should_backtrack = "true" in backtrack_str or "是" in backtrack_str

            if "backtrack_to_step:" in content.lower():
                step_str = content.lower().split("backtrack_to_step:")[1].split("\n")[0].strip()
                # 提取数字
                import re
                numbers = re.findall(r'\d+', step_str)
                if numbers:
                    result.backtrack_to_step = int(numbers[0])

            if "reflection_reason:" in content.lower():
                reason = content.lower().split("reflection_reason:")[1].split("\n")[0].strip()
                result.reflection_reason = reason

            if "improvement_suggestion:" in content.lower():
                suggestion = content.lower().split("improvement_suggestion:")[1].split("\n")[0].strip()
                result.improvement_suggestion = suggestion

            if "confidence_score:" in content.lower():
                score_str = content.lower().split("confidence_score:")[1].split("\n")[0].strip()
                import re
                numbers = re.findall(r'0?\.\d+', score_str)
                if numbers:
                    result.confidence_score = float(numbers[0])

        except Exception as e:
            print(f"[Reflection] 解析反思结果失败: {e}")

        # 记录反思历史
        self.reflection_history.append({
            "step_number": current_step_number,
            "timestamp": datetime.now().isoformat(),
            "should_backtrack": result.should_backtrack,
            "reason": result.reflection_reason,
            "confidence": result.confidence_score
        })

        return result

    async def reflect_on_final_answer(
        self,
        query: str,
        final_answer: str,
        thought_history: List[Any]
    ) -> Dict[str, Any]:
        """
        对最终答案进行反思
        """
        prompt = f"""请对以下最终答案进行质量评估。

原始问题: {query}

最终答案:
{final_answer}

思考过程摘要:
- 总步骤数: {len(thought_history)}
- 主要动作: {[step.action.value for step in thought_history]}

请评估:
1. 答案是否完整回答了问题？
2. 推理过程是否合理？
3. 是否存在过度推断？
4. 是否有遗漏的重要信息？
5. 答案的可信度如何？

输出格式 (JSON):
{{
    "completeness_score": 0.0-1.0,
    "reasoning_quality": "高/中/低",
    "potential_issues": ["问题1", "问题2"],
    "suggested_additions": "建议补充的内容",
    "overall_confidence": 0.0-1.0
}}"""

        messages = [
            SystemMessage(content="你是一个答案质量评估专家。严格评估AI生成的答案。"),
            HumanMessage(content=prompt)
        ]

        response = await self.llm.ainvoke(messages)

        try:
            # 提取 JSON
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            return json.loads(content)
        except:
            return {
                "completeness_score": 0.5,
                "reasoning_quality": "未知",
                "potential_issues": ["解析失败"],
                "overall_confidence": 0.5
            }

    def get_reflection_stats(self) -> Dict[str, Any]:
        """获取反思统计"""
        if not self.reflection_history:
            return {"total_reflections": 0}

        total = len(self.reflection_history)
        backtracks = sum(1 for r in self.reflection_history if r["should_backtrack"])
        avg_confidence = sum(r["confidence"] for r in self.reflection_history) / total

        return {
            "total_reflections": total,
            "backtrack_count": backtracks,
            "backtrack_rate": backtracks / total,
            "average_confidence": avg_confidence,
            "recent_reflections": self.reflection_history[-10:]
        }
