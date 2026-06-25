# models/routeResult.py

from dataclasses import dataclass, field


@dataclass
class RouteResult:

    intent: str = "CHAT"
    action: str = ""
    confidence: float = 0.0

    source: str = ""        # "command" | "rule" | "ai"
    reason: str = ""        # 可解释性

    table_name: str = ""
    entity: str = ""
    condition: dict = field(default_factory=dict)

    # Stage2 领域输出
    search: dict = field(default_factory=dict)   # 查询条件
    update: dict = field(default_factory=dict)   # 修改值
