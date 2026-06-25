# -*- coding: utf-8 -*-
"""
dispatcher.py —— 消息分发核心 (v3 — WorkflowDefinition 集成)
============================================================
管道:
  Message → Session → CANCEL? → WAITING_INPUT? → RUNNING? → Router
          → WorkflowDefinition(slot检查) → Agent(只做执行)
          → Session更新 → 回复

关键修复:
  ✔ HybridRouter 接入 DeepSeek LLM
  ✔ slot_mgr / conv_mgr 注入到 agent 模块
  ✔ WorkflowDefinition 统一参数定义
  ✔ Agent 只负责执行, state/slot 由 dispatcher 统一管理
"""

import os
import uuid
import asyncio
from datetime import datetime

import httpx
from dotenv import load_dotenv

from router.hybrid_router import HybridRouter
from router.action_intent import ActionIntent
from router.intent_resolver import IntentResolver
from router.action_resolver import ActionResolver
from core.logger import log_trace

from conversation.session import Session
from conversation.workflow_state import WorkflowState
from conversation.conversation_manager import ConversationManager
from conversation.slot_manager import SlotManager
from conversation.workflow_definition import get_workflow

load_dotenv()

# ─── DeepSeek 配置 ────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-d14c8f313d2f436cbe5c4f3503e7097e")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


# ═══════════════════════════════════════════════════
#  DeepSeek LLM 包装器
# ═══════════════════════════════════════════════════
class DeepSeekLLM:

    async def ainvoke(self, prompt: str) -> str:
        payload = {
            "model": DEEPSEEK_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 300,
        }
        try:
            async with httpx.AsyncClient(
                base_url=DEEPSEEK_BASE_URL,
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=15.0,
            ) as client:
                resp = await client.post("/v1/chat/completions", json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return content.strip() if content else "chat"
        except Exception as e:
            import traceback
            print(f"[DeepSeek] API 调用失败: {e}")
            traceback.print_exc()
            return "chat"


# ═══════════════════════════════════════════════════
#  初始化所有模块
# ═══════════════════════════════════════════════════
llm = DeepSeekLLM()
router = HybridRouter(llm=llm)
intent_resolver = IntentResolver()
action_resolver = ActionResolver()

conv_mgr = ConversationManager()
slot_mgr = SlotManager()

# ── 注入依赖到 agent 模块 ──
import agents.rpa_agent as rpa_mod
import agents.table_agent as table_mod
import agents.kb_agent as kb_mod

rpa_mod.conv_mgr = conv_mgr
rpa_mod.slot_mgr = slot_mgr
table_mod.conv_mgr = conv_mgr
table_mod.slot_mgr = slot_mgr
kb_mod.conv_mgr = conv_mgr

from agents.rpa_agent import RPAAgent
from agents.table_agent import TableAgent
from agents.kb_agent import KBAgent
from agents.mock_agent import MockAgent

kb_agent = KBAgent()
rpa_agent = RPAAgent()
table_agent = TableAgent()
mock_agent = MockAgent()

# ─── Cancel 命令 ──────────────────────────────────
CANCEL_SET = {"/cancel", "/cancel", "/end", "/end",
              "/reset", "/reset"}


def is_cancel(text: str) -> bool:
    return text.strip().lower() in CANCEL_SET


# ═══════════════════════════════════════════════════
#  核心调度
# ═══════════════════════════════════════════════════
async def dispatch(message):
    """ChatMessage → (action, result, session)"""
    trace_id = str(uuid.uuid4())[:8]
    t_start = datetime.now()

    print(f"\n{'='*60}")
    print(f"[DISPATCH][{trace_id}] {message.text}")

    # ── 1. Session ──
    session = conv_mgr.get_session(message.group_id, message.user_id)
    print(f"[SESSION] state={session.workflow_state} "
          f"action={session.current_action}")

    # ── 2. CANCEL (最高优先级) ──
    if is_cancel(message.text):
        conv_mgr.reset(session)
        print(f"[DISPATCH] CANCEL → reset")
        return ActionIntent.CHAT, "OK", session

    # ── 3. WAITING_INPUT → 续任务 ──
    if session.workflow_state == WorkflowState.WAITING_INPUT:
        action = _to_action(session.current_action)
        result = await _agent_run(action, message, session)
        _finalize(session)
        return action, result, session

    # ── 4. RUNNING → 续任务 ──
    if session.workflow_state == WorkflowState.RUNNING:
        action = _to_action(session.current_action)
        result = await _agent_run(action, message, session)
        _finalize(session)
        return action, result, session

    # ── 5. IDLE → Router → 新任务 ──

    clean_text = message.text.replace("@_user_1", "").strip()
    route_result = await router.route(clean_text)

    # 双层决策: IntentResolver → ActionResolver
    route_result = intent_resolver.resolve(route_result)
    action = action_resolver.resolve(route_result, message.text)

    print(f"[ROUTER] → source={route_result.source} intent={route_result.intent} action={action.value}")

    # 写入 session
    conv_mgr.set_action(session, action.value)
    conv_mgr.set_agent(session, _agent_name(action))

    session.slots = session.slots or {}
    session.slots.update({
        "intent": route_result.intent,
        "source": route_result.source,
        "confidence": route_result.confidence,
        "table_name": route_result.table_name,
        "entity": route_result.entity,
        "condition": route_result.condition,
        "search": route_result.search,
        "update": route_result.update,
    })
    session.context["last_route"] = {
        "intent": route_result.intent,
        "action": action.value,
        "source": route_result.source,
        "confidence": route_result.confidence,
        "reason": route_result.reason,
    }

    # 执行 Agent
    result = await _agent_run(action, message, session)
    _finalize(session)

    elapsed = (datetime.now() - t_start).total_seconds()
    print(f"[DISPATCH][{trace_id}] ({elapsed:.1f}s) → {result[:80]}")

    log_trace(trace_id=trace_id, message=message, action=action)

    return action, result, session


# ═══════════════════════════════════════════════════
#  Agent 调用
# ═══════════════════════════════════════════════════
async def _agent_run(action, message, session):
    """统一 Agent 入口, 传入 message + session"""

    if action == ActionIntent.TABLE_INSERT:
        return await table_agent.insert(message, session)
    if action == ActionIntent.TABLE_QUERY:
        return await table_agent.query(message, session)
    if action == ActionIntent.TABLE_UPDATE:
        return await table_agent.update(message, session)
    if action == ActionIntent.TABLE_DELETE:
        return await table_agent.delete(message, session)
    if action == ActionIntent.KB_SEARCH:
        return await kb_agent.search(message, session)
    if action == ActionIntent.RPA_EXECUTION:
        return await rpa_agent.run(message, session)
    # CHAT
    return await mock_agent.run(action, message, session)


# ═══════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════
def _finalize(session):
    """任务结束自动 reset"""
    if session.workflow_state in (WorkflowState.SUCCESS, WorkflowState.FAILED):
        print(f"[SESSION] {session.workflow_state.value} → RESET")
        conv_mgr.reset(session)


def _to_action(action_str: str):
    mapping = {a.value: a for a in ActionIntent}
    return mapping.get(action_str, ActionIntent.CHAT)


def _agent_name(action) -> str:
    wf = get_workflow(action.value)
    return wf.agent_name
