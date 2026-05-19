"""
对话历史存储
支持多轮对话的上下文管理
"""

import json
import os
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class ConversationTurn:
    """单轮对话"""
    turn_id: str
    session_id: str
    user_message: str
    agent_response: Any
    timestamp: str
    context: Dict[str, Any]


class ConversationStore:
    """
    对话历史存储管理器
    支持持久化和检索多轮对话
    """

    def __init__(self, storage_dir: str = None):
        if storage_dir is None:
            storage_dir = os.path.join(os.path.dirname(__file__), "conversations")
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # 内存缓存
        self._cache: Dict[str, List[ConversationTurn]] = {}

    def _get_session_file(self, session_id: str) -> Path:
        """获取会话文件路径"""
        return self.storage_dir / f"{session_id}.json"

    def _load_session(self, session_id: str) -> List[ConversationTurn]:
        """从文件加载会话历史"""
        if session_id in self._cache:
            return self._cache[session_id]

        file_path = self._get_session_file(session_id)
        if not file_path.exists():
            return []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            turns = []
            for turn_data in data.get('turns', []):
                turns.append(ConversationTurn(**turn_data))

            self._cache[session_id] = turns
            return turns

        except Exception as e:
            print(f"[ConversationStore] 加载会话失败: {e}")
            return []

    def _save_session(self, session_id: str, turns: List[ConversationTurn]):
        """保存会话历史到文件"""
        try:
            file_path = self._get_session_file(session_id)
            data = {
                'session_id': session_id,
                'created_at': datetime.now().isoformat(),
                'turn_count': len(turns),
                'turns': [asdict(turn) for turn in turns]
            }

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            self._cache[session_id] = turns

        except Exception as e:
            print(f"[ConversationStore] 保存会话失败: {e}")

    def add_turn(self, session_id: str, user_message: str,
                 agent_response: Any, context: Dict[str, Any] = None) -> ConversationTurn:
        """添加一轮对话"""
        turn = ConversationTurn(
            turn_id=f"{session_id}_{datetime.now().timestamp()}",
            session_id=session_id,
            user_message=user_message,
            agent_response=agent_response,
            timestamp=datetime.now().isoformat(),
            context=context or {}
        )

        turns = self._load_session(session_id)
        turns.append(turn)

        # 最多保留 50 轮对话
        if len(turns) > 50:
            turns = turns[-50:]

        self._save_session(session_id, turns)
        print(f"[ConversationStore] 添加对话轮次: session={session_id}, turn={len(turns)}")

        return turn

    def update_last_turn(self, session_id: str, agent_response: Any,
                        context: Dict[str, Any] = None) -> Optional[ConversationTurn]:
        """更新最后一轮对话的 agent_response"""
        turns = self._load_session(session_id)

        if not turns:
            print(f"[ConversationStore] 更新失败: 会话 {session_id} 为空")
            return None

        # 更新最后一轮的 agent_response 和 context
        last_turn = turns[-1]
        last_turn.agent_response = agent_response
        if context:
            last_turn.context.update(context)
        last_turn.timestamp = datetime.now().isoformat()

        self._save_session(session_id, turns)
        print(f"[ConversationStore] 更新最后一轮: session={session_id}, turn={len(turns)}")

        return last_turn

    def get_history(self, session_id: str, limit: int = 10) -> List[ConversationTurn]:
        """获取会话历史"""
        turns = self._load_session(session_id)
        return turns[-limit:] if turns else []

    def get_context_summary(self, session_id: str) -> Dict[str, Any]:
        """获取上下文摘要（用于传递给 Agent）"""
        turns = self._load_session(session_id)

        if not turns:
            return {}

        # 提取关键信息
        recent_queries = [t.user_message for t in turns[-5:]]
        recent_date_ranges = []
        recent_analysis_types = []

        for turn in turns[-5:]:
            context = turn.context or {}
            if 'date_range' in context:
                recent_date_ranges.append(context['date_range'])
            if 'analysis_type' in context:
                recent_analysis_types.append(context['analysis_type'])

        return {
            'session_id': session_id,
            'total_turns': len(turns),
            'recent_queries': recent_queries,
            'recent_date_ranges': recent_date_ranges,
            'recent_analysis_types': list(set(recent_analysis_types)),
            'last_query': turns[-1].user_message if turns else None,
            'last_response_summary': self._summarize_response(turns[-1].agent_response) if turns else None
        }

    def _summarize_response(self, response: Any) -> str:
        """简要总结响应内容"""
        if isinstance(response, dict):
            if 'analysis' in response:
                analysis = response['analysis']
                if isinstance(analysis, dict):
                    stats = analysis.get('statistics', {})
                    findings = analysis.get('key_findings', [])
                    return f"分析完成，找到 {len(findings)} 条关键发现"
            return "响应完成"
        return str(response)[:50]

    def clear_session(self, session_id: str):
        """清空会话历史"""
        file_path = self._get_session_file(session_id)
        if file_path.exists():
            file_path.unlink()

        if session_id in self._cache:
            del self._cache[session_id]

        print(f"[ConversationStore] 清空会话: {session_id}")

    def get_all_sessions(self) -> List[Dict[str, Any]]:
        """获取所有会话列表"""
        sessions = []
        for file_path in self.storage_dir.glob("*.json"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    sessions.append({
                        'session_id': data.get('session_id'),
                        'created_at': data.get('created_at'),
                        'turn_count': data.get('turn_count', 0)
                    })
            except:
                pass
        return sorted(sessions, key=lambda x: x['created_at'], reverse=True)


# 全局实例
conversation_store = ConversationStore()
