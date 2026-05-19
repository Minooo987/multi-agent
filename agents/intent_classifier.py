"""
查询意图分类器
使用 LLM 结合历史上下文理解用户真实意图
"""

import json
from typing import Dict, Any, List
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import settings


class IntentClassifier:
    """
    基于 LLM 的查询意图分类器
    结合历史上下文理解用户真实意图
    """

    def __init__(self):
        self.llm = ChatAnthropic(
            model=settings.model_name,
            anthropic_api_url=settings.model_base_url,
            anthropic_api_key=settings.model_api_key,
            temperature=0.3,  # 低温度确保一致性
            max_tokens=1024
        )

    async def classify_intent(
        self,
        current_query: str,
        conversation_history: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        分类用户查询意图

        Args:
            current_query: 当前查询（原始查询，不含上下文标记）
            conversation_history: 对话历史

        Returns:
            {
                "intent": "mileage_only|orders_only|both|unknown",
                "reasoning": "分类理由",
                "date_range": {"start": "2026-03-05", "end": "2026-03-20"},
                "confidence": 0.95
            }
        """

        # 构建历史摘要
        history_summary = []
        for turn in conversation_history[-3:]:  # 最近3轮
            history_summary.append({
                "query": turn.get("user_message", "")[:100],
                "analysis_type": turn.get("context", {}).get("analysis_type", "unknown")
            })

        prompt = f"""你是一个查询意图分类器。请分析用户的当前查询，结合历史对话理解真实意图。

## 当前查询
"{current_query}"

## 历史对话
{json.dumps(history_summary, ensure_ascii=False, indent=2)}

## 分析要求
1. 如果当前查询是简写（只有日期、数字等），参考历史对话补全意图
2. 判断需要查询哪些数据：
   - 里程数据（车辆行驶里程、载客里程、司机工作时长）
   - 订单数据（订单数、完成率、乘客数、取消订单）
3. 提取日期范围

## 输出格式
{json.dumps({
    "intent": "mileage_only|orders_only|both|unknown",
    "reasoning": "分类理由，特别是如何结合历史上下文推断的",
    "date_range": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
    "needs_passenger": True,
    "needs_operation": True,
    "confidence": 0.95
}, ensure_ascii=False, indent=2)}

请只输出 JSON，不要有其他内容。"""

        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            content = response.content

            # 提取 JSON
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                result = json.loads(content[json_start:json_end])
            else:
                result = {"intent": "unknown", "error": "无法解析响应"}

            # 确保返回布尔值
            result["needs_passenger"] = result.get("needs_passenger", True)
            result["needs_operation"] = result.get("needs_operation", True)

            return result

        except Exception as e:
            print(f"[IntentClassifier] 分类失败: {e}")
            # 降级到关键词匹配
            return self._fallback_classification(current_query)

    def _fallback_classification(self, query: str) -> Dict[str, Any]:
        """降级方案：关键词匹配"""
        mileage_keywords = ["里程", "mileage", "司机", "工作时长", "行驶"]
        order_keywords = ["订单", "order", "乘客数", "完成率", "取消", "客流"]

        has_mileage = any(kw in query for kw in mileage_keywords)
        has_order = any(kw in query for kw in order_keywords)

        if has_mileage and has_order:
            intent = "both"
        elif has_mileage:
            intent = "mileage_only"
        elif has_order:
            intent = "orders_only"
        else:
            intent = "unknown"

        return {
            "intent": intent,
            "reasoning": "基于关键词匹配的降级方案",
            "needs_passenger": has_mileage or not has_order,
            "needs_operation": has_order or not has_mileage,
            "confidence": 0.5
        }


# 全局实例
intent_classifier = IntentClassifier()
