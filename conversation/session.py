from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Session:

    session_id: str
    group_id: str
    user_id: str

    #支持会话多任务
    workflow_id: str = ""

    # 当前执行Agent
    current_agent: str | None = None

    # 当前动作
    current_action: str | None = None

    # 会话状态（是否在执行任务）
    workflow_state: str = "idle"

    # 参数槽位（最关键）
    slots: dict = field(default_factory=dict)

    # 上下文（扩展用）
    context: dict = field(default_factory=dict)

    # 历史（轻量记录）
    history: list = field(default_factory=list)

    updated_at: datetime = field(default_factory=datetime.utcnow)