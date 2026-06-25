# conversation/workflow_definition.py
"""
WorkflowDefinition —— 统一流程定义
Table 操作不再硬编码字段, 由 table_agent 动态拉取
"""

from dataclasses import dataclass, field


@dataclass
class WorkflowDefinition:
    """单个 workflow 的定义"""
    required_slots: list = field(default_factory=list)
    slot_prompts: dict = field(default_factory=dict)
    agent_name: str = "mock"


WORKFLOWS = {
    # ── RPA (固定参数) ──
    "rpa_execution": WorkflowDefinition(
        required_slots=["rpa_date"],
        slot_prompts={"rpa_date": "请提供执行日期"},
        agent_name="rpa",
    ),

    # ── Table (字段动态拉取, 不再硬编码) ──
    "table_query": WorkflowDefinition(
        required_slots=[],
        slot_prompts={},
        agent_name="table",
    ),
    "table_insert": WorkflowDefinition(
        required_slots=[],
        slot_prompts={},
        agent_name="table",
    ),
    "table_update": WorkflowDefinition(
        required_slots=[],
        slot_prompts={},
        agent_name="table",
    ),
    "table_delete": WorkflowDefinition(
        required_slots=[],
        slot_prompts={},
        agent_name="table",
    ),

    # ── KB / CHAT ──
    "kb_search": WorkflowDefinition(
        required_slots=[],
        slot_prompts={},
        agent_name="kb",
    ),
    "chat": WorkflowDefinition(
        required_slots=[],
        slot_prompts={},
        agent_name="mock",
    ),
}


def get_workflow(action_value: str) -> WorkflowDefinition:
    return WORKFLOWS.get(action_value, WorkflowDefinition())
