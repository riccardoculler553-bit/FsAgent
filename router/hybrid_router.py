# router/hybrid_router.py
"""
HybridRouter —— 三层分类器
职责: 只做分类 (command/rule/ai)，不参与业务判断
输出: RouteResult(intent + source)
"""

from router.intent_router import Intent
from router.command_router import CommandRouter
from router.rule_router import RuleRouter
from router.ai_router import AIRouter
from models.routeResult import RouteResult


class HybridRouter:

    def __init__(self, llm):
        self.command_router = CommandRouter()
        self.rule_router = RuleRouter()
        self.ai_router = AIRouter(llm)

    async def route(self, text: str) -> RouteResult:
        """
        三层路由 → RouteResult
        L1 command → RouteResult(intent, source="command")
        L2 rule    → RouteResult(intent, source="rule")
        L3 AI      → RouteResult (已含 intent + action)
        """

        # L1: Command
        intent = self.command_router.route(text)
        if intent:
            return RouteResult(
                intent=intent.value,
                source="command",
                reason=f"command matched: {text[:30]}",
            )

        # L2: Rule
        intent = self.rule_router.route(text)
        if intent:
            return RouteResult(
                intent=intent.value,
                source="rule",
                reason=f"rule matched",
            )

        # L3: AI
        try:
            result = await self.ai_router.route(text)
            return result
        except Exception as e:
            return RouteResult(
                intent="CHAT",
                source="ai",
                reason=f"ai_error: {e}",
            )
