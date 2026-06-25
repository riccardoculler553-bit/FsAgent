# router/intent_resolver.py
"""
IntentResolver —— 语义修正层
根据 source 对 intent 进行修正/确认
当前阶段: 简单透传，预留扩展
"""

from models.routeResult import RouteResult


class IntentResolver:

    def resolve(self, rr: RouteResult) -> RouteResult:
        """修正 RouteResult.intent"""

        # AI 已给出完整判断 → 直接信任
        if rr.source == "ai":
            return rr

        # Command/Rule 给出的是粗粒度 intent, 保持原样
        # 未来可在此处做冲突修正 (如 rule=TABLE 但历史显示是 RPA 场景)
        if rr.source in ("command", "rule"):
            return rr

        # 未知 source → 保持原样
        return rr
