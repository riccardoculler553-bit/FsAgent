# agents/rpa_agent.py

import json

from conversation.workflow_state import WorkflowState
from conversation.conversation_manager import ConversationManager
from conversation.slot_manager import SlotManager
from conversation.workflow_definition import get_workflow

# 模块级引用 (由 dispatcher 注入)
conv_mgr: ConversationManager = None
slot_mgr: SlotManager = None


class RPAAgent:
    """RPA 执行 — Slot 由 WorkflowEngine 统一管理, Agent 只做执行"""

    async def run(self, message, session=None):
        print(f"  [RPAAgent] 执行: {message.text}")

        # 新任务首次调用 → 检查 slots
        if session and session.workflow_state == WorkflowState.IDLE:
            return self._start(message, session)

        # 续任务 → 收集用户补充的参数
        if session and session.workflow_state == WorkflowState.WAITING_INPUT:
            return self._collect(message, session)

        # 已就绪 → 直接执行
        return self._execute(session)

    def _start(self, message, session):
        wf = get_workflow("rpa_execution")
        missing = slot_mgr.missing_keys(session, wf.required_slots)
        if missing:
            conv_mgr.set_workflow_state(session, WorkflowState.WAITING_INPUT)
            return wf.slot_prompts.get(missing[0], f"请提供: {missing[0]}")
        return self._execute(session)

    def _collect(self, message, session):
        wf = get_workflow("rpa_execution")
        missing = slot_mgr.missing_keys(session, wf.required_slots)
        if missing:
            key = missing[0]
            slot_mgr.set(session, key, message.text.strip())
            print(f"  [RPAAgent] slot {key} = {message.text.strip()}")

        if slot_mgr.has_all_required(session, wf.required_slots):
            conv_mgr.set_workflow_state(session, WorkflowState.SUCCESS)
            return self._execute(session)

        missing = slot_mgr.missing_keys(session, wf.required_slots)
        return wf.slot_prompts.get(missing[0], f"请提供: {missing[0]}")

    def _execute(self, session):
        slots_str = json.dumps(slot_mgr.to_dict(session), ensure_ascii=False)
        return f"[RPA] 执行完成 {slots_str}"
