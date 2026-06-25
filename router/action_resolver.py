# router/action_resolver.py
"""
ActionResolver —— 执行决策层
RouteResult + 原始文本 → ActionIntent
统一处理: AI action / command 关键词 / rule 关键词
"""

from router.action_intent import ActionIntent
from models.routeResult import RouteResult


class ActionResolver:

    def resolve(self, rr: RouteResult, text: str = "") -> ActionIntent:
        """
        RouteResult → ActionIntent
        优先级: AI action > 关键词匹配 > intent 默认
        """

        # ── 1. AI 给出了具体 action → 直接映射 ──
        if rr.source == "ai" and rr.action:
            return self._map_action(rr.action)

        # ── 2. Command/Rule → 关键词匹配细分 ──
        if rr.intent == "TABLE" or rr.intent == "table":
            return self._resolve_table_action(text)

        if rr.intent == "RPA" or rr.intent == "rpa":
            return ActionIntent.RPA_EXECUTION

        if rr.intent == "KB" or rr.intent == "kb":
            return ActionIntent.KB_SEARCH

        # CHAT / unknown
        return ActionIntent.CHAT

    # ── 关键词 → TABLE 子动作 ──

    def _resolve_table_action(self, text: str) -> ActionIntent:
        if "新增" in text or "写入" in text or "插入" in text or "添加" in text:
            return ActionIntent.TABLE_INSERT
        if "删除" in text or "移除" in text:
            return ActionIntent.TABLE_DELETE
        if "修改" in text or "更新" in text:
            return ActionIntent.TABLE_UPDATE
        # 默认 TABLE_QUERY（最安全的默认值）
        return ActionIntent.TABLE_QUERY

    # ── action 字符串 → ActionIntent ──

    def _map_action(self, action: str) -> ActionIntent:
        mapping = {
            "TABLE_INSERT": ActionIntent.TABLE_INSERT,
            "TABLE_DELETE": ActionIntent.TABLE_DELETE,
            "TABLE_UPDATE": ActionIntent.TABLE_UPDATE,
            "TABLE_QUERY": ActionIntent.TABLE_QUERY,
            "RPA_EXECUTION": ActionIntent.RPA_EXECUTION,
            "KB_SEARCH": ActionIntent.KB_SEARCH,
        }
        return mapping.get(action, ActionIntent.CHAT)
