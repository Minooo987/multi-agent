"""
Enhanced Memory Manager
Integrate short-term conversation memory and long-term vector memory
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import json

# Import existing conversation store
try:
    from memory.conversation_store import conversation_store
except ImportError:
    conversation_store = None
    print("[MemoryManager] Conversation store not available")

from memory.vector_store import vector_store, MemoryEntry


class EnhancedMemoryManager:
    """
    Enhanced memory manager
    Unified management of short-term conversation memory and long-term semantic memory
    """

    def __init__(self):
        self.conversation_store = conversation_store
        self.vector_store = vector_store

    async def add_experience(
        self,
        session_id: str,
        query: str,
        response: Dict[str, Any],
        success: bool = True,
        importance: float = None
    ) -> str:
        """Add experience to long-term memory"""
        if importance is None:
            importance = self._calculate_importance(query, response, success)

        memory_content = f"Query: {query}\nResponse: {json.dumps(response, ensure_ascii=False)[:500]}\nSuccess: {success}"

        memory_type = "successful_experience" if success else "failed_attempt"

        memory_id = await self.vector_store.add_memory(
            content=memory_content,
            memory_type=memory_type,
            metadata={
                "session_id": session_id,
                "query": query,
                "success": success,
                "importance": importance
            },
            importance_score=importance
        )

        return memory_id

    def _calculate_importance(
        self,
        query: str,
        response: Dict[str, Any],
        success: bool
    ) -> float:
        """Calculate memory importance"""
        importance = 1.0

        if not success:
            importance += 0.5

        query_length = len(query)
        if query_length > 50:
            importance += 0.3
        if query_length > 100:
            importance += 0.2

        if isinstance(response, dict):
            if len(response) > 5:
                importance += 0.2

        return min(importance, 3.0)

    async def retrieve_relevant_context(
        self,
        query: str,
        session_id: str = None,
        top_k: int = 5
    ) -> Dict[str, Any]:
        """Retrieve relevant context"""
        context = {
            "short_term": [],
            "long_term": [],
            "facts": [],
            "similar_experiences": []
        }

        # 1. Get short-term conversation history
        if session_id and self.conversation_store:
            recent_turns = self.conversation_store.get_history(session_id, limit=3)
            context["short_term"] = [
                {
                    "query": turn.user_message,
                    "response_summary": self._summarize_response(turn.agent_response)
                }
                for turn in recent_turns
            ]

        # 2. Semantic search long-term memory
        semantic_results = await self.vector_store.search(
            query=query,
            top_k=top_k,
            min_similarity=0.6
        )

        for result in semantic_results:
            memory_type = result["metadata"].get("memory_type", "unknown")

            if memory_type == "fact":
                context["facts"].append(result)
            elif memory_type in ["successful_experience", "failed_attempt"]:
                context["similar_experiences"].append(result)
            else:
                context["long_term"].append(result)

        return context

    def _summarize_response(self, response: Any) -> str:
        """Briefly summarize response"""
        if isinstance(response, dict):
            if "analysis" in response:
                return "Analysis complete"
            if "error" in response:
                return f"Error: {response['error'][:50]}"
            return json.dumps(response, ensure_ascii=False)[:100]
        return str(response)[:100]

    async def add_fact(self, fact: str, source: str = "analysis") -> str:
        """Add fact to knowledge base"""
        return await self.vector_store.add_memory(
            content=fact,
            memory_type="fact",
            metadata={"source": source, "added_at": datetime.now().isoformat()},
            importance_score=2.0
        )

    async def learn_from_feedback(
        self,
        session_id: str,
        query: str,
        original_response: Dict[str, Any],
        feedback: str,
        rating: int = None
    ) -> str:
        """Learn from feedback"""
        is_positive = self._is_positive_feedback(feedback)

        learning_content = f"Query: {query}\nOriginal response: {json.dumps(original_response, ensure_ascii=False)[:300]}\nFeedback: {feedback}\nRating: {rating}"

        memory_type = "positive_feedback" if is_positive else "negative_feedback"
        importance = 2.5 if not is_positive else 1.5

        memory_id = await self.vector_store.add_memory(
            content=learning_content,
            memory_type=memory_type,
            metadata={
                "session_id": session_id,
                "query": query,
                "rating": rating,
                "feedback_type": "positive" if is_positive else "negative"
            },
            importance_score=importance
        )

        return memory_id

    def _is_positive_feedback(self, feedback: str) -> bool:
        """Check if feedback is positive"""
        positive_keywords = ["good", "great", "excellent", "accurate", "correct", "satisfied", "approve"]
        negative_keywords = ["wrong", "incorrect", "bad", "poor", "error", "reject"]

        feedback_lower = feedback.lower()

        pos_count = sum(1 for kw in positive_keywords if kw in feedback_lower)
        neg_count = sum(1 for kw in negative_keywords if kw in feedback_lower)

        return pos_count >= neg_count

    async def get_similar_successful_cases(
        self,
        query: str,
        limit: int = 3
    ) -> List[Dict[str, Any]]:
        """Get similar successful cases"""
        results = await self.vector_store.search(
            query=query,
            top_k=limit * 2,
            min_similarity=0.5
        )

        successful_cases = [
            r for r in results
            if r["metadata"].get("memory_type") == "successful_experience"
        ]

        return successful_cases[:limit]

    def build_context_prompt(
        self,
        context: Dict[str, Any],
        max_length: int = 2000
    ) -> str:
        """Build context prompt"""
        parts = []

        if context["short_term"]:
            parts.append("## Recent Conversation")
            for i, turn in enumerate(context["short_term"][-2:], 1):
                parts.append(f"{i}. User: {turn['query'][:100]}...")
                parts.append(f"   Response: {turn['response_summary']}")

        if context["facts"]:
            parts.append("\n## Relevant Knowledge")
            for fact in context["facts"][:3]:
                parts.append(f"- {fact['content'][:150]}...")

        if context["similar_experiences"]:
            parts.append("\n## Reference Cases")
            for exp in context["similar_experiences"][:2]:
                meta = exp.get("metadata", {})
                parts.append(f"- Similar query: {meta.get('query', 'N/A')[:100]}...")
                parts.append(f"  Result: {'Success' if meta.get('success') else 'Failed'}")

        result = "\n".join(parts)

        if len(result) > max_length:
            result = result[:max_length] + "\n... (context truncated)"

        return result


# Global instance
try:
    memory_manager = EnhancedMemoryManager()
except Exception as e:
    print(f"[MemoryManager] Initialization failed: {e}")
    memory_manager = None
