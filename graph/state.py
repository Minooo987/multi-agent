"""
团队状态定义
等效 Claude Code Agent Teams 的状态管理
"""

from typing import TypedDict, List, Dict, Any, Optional, Literal
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import uuid


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class AgentRole(str, Enum):
    """Agent 角色"""
    TASK_MANAGER = "task_manager"
    PASSENGER_PROCESSOR = "passenger_processor"
    OPERATION_SCHEDULER = "operation_scheduler"


@dataclass
class Message:
    """
    消息定义
    等效 Claude Code 的 SendMessage
    """
    from_agent: str
    to_agent: str
    content: str
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    message_type: Literal["task", "result", "error", "retry", "system"] = "task"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "message_type": self.message_type,
            "metadata": self.metadata
        }


@dataclass
class Task:
    """任务定义"""
    id: str
    type: Literal["passenger", "operation", "coordination", "analysis"]
    description: str
    status: TaskStatus = TaskStatus.PENDING
    assigned_to: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    mcp_calls: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "description": self.description,
            "status": self.status.value,
            "assigned_to": self.assigned_to,
            "result": self.result,
            "error": self.error,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class TeamState(TypedDict):
    """
    团队状态
    等效 Claude Code Agent Teams 的完整状态
    """
    # 会话标识
    session_id: str
    user_id: Optional[str]

    # 用户输入
    user_request: str

    # 任务管理
    tasks: List[Task]
    current_task: Optional[Task]

    # 消息系统（等效 SendMessage）
    messages: List[Message]
    unread_messages: Dict[str, List[Message]]

    # Agent 状态
    agent_status: Dict[str, Dict[str, Any]]

    # 处理结果
    passenger_result: Optional[Dict[str, Any]]
    operation_result: Optional[Dict[str, Any]]
    final_result: Optional[str]

    # 错误处理
    errors: List[Dict[str, Any]]
    retry_queue: List[Task]

    # 人机交互
    human_feedback: Optional[str]
    interrupt_reason: Optional[str]
    require_human_review: bool

    # 路由控制
    next_step: Literal[
        "analyze", "route", "parallel",
        "passenger_only", "operation_only",
        "aggregate", "human_review",
        "finalize", "retry", "error"
    ]

    # MCP 工具调用记录
    mcp_calls: List[Dict[str, Any]]
    mcp_results: List[Dict[str, Any]]

    # 元数据
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]


def create_initial_state(user_request: str, session_id: str = None, user_id: str = None) -> TeamState:
    """创建初始状态"""
    now = datetime.now()
    return TeamState(
        session_id=session_id or str(uuid.uuid4()),
        user_id=user_id,
        user_request=user_request,
        tasks=[],
        current_task=None,
        messages=[],
        unread_messages={},
        agent_status={},
        passenger_result=None,
        operation_result=None,
        final_result=None,
        errors=[],
        retry_queue=[],
        human_feedback=None,
        interrupt_reason=None,
        require_human_review=False,
        next_step="analyze",
        mcp_calls=[],
        mcp_results=[],
        created_at=now,
        updated_at=now,
        completed_at=None
    )
