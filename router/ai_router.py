# router/ai_router.py
"""
AIRouter —— 两级 AI 路由
  Stage 1: 粗粒度意图识别 (RPA/TABLE/KB/CHAT)   ~100 tokens
  Stage 2: 领域细化 (action + search + update)     ~200 tokens
"""

import json
from models.routeResult import RouteResult


# ═══════════════════════════════════════════════════
#  Stage 1: 意图分类 (轻量)
# ═══════════════════════════════════════════════════
STAGE1_PROMPT = """你是意图分类器。从以下选择一个: RPA TABLE KB CHAT

只输出 JSON: {{"intent": "TABLE"}}

示例:
"新增张三到登记表" → {{"intent": "TABLE"}}
"今天天气" → {{"intent": "CHAT"}}
"公司制度是什么" → {{"intent": "KB"}}
"执行自动化流程" → {{"intent": "RPA"}}

用户输入: {text}"""


# ═══════════════════════════════════════════════════
#  Stage 2: 领域细化 (按 domain 分派 prompt)
# ═══════════════════════════════════════════════════
STAGE2_TABLE = """你是表格操作专家。分析用户意图并提取结构化信息。必须提取表格名称。

规则:
- table_name 必须填写, 从用户输入中提取表格名(如"人员登记表"→"人员登记表")
- 用户没提表格名时填""

动作只能是: TABLE_INSERT TABLE_DELETE TABLE_UPDATE TABLE_QUERY

可用字段: {field_names}

动作只能是: TABLE_INSERT TABLE_DELETE TABLE_UPDATE TABLE_QUERY

关键规则:
- 查询用 TABLE_QUERY, 只填 search
- 新增用 TABLE_INSERT, 只填 update
- 修改用 TABLE_UPDATE, search=找哪些记录, update=改成什么
- 删除用 TABLE_DELETE, 只填 search

示例:
"查李逸的信息" → {{"action":"TABLE_QUERY","search":{{"姓名":"李逸"}},"update":{{}}}}
"新增张三,138xxxx" → {{"action":"TABLE_INSERT","search":{{}},"update":{{"姓名":"张三","手机号":"138xxxx"}}}}
"将姓名=李逸的资产设为9999" → {{"action":"TABLE_UPDATE","search":{{"姓名":"李逸"}},"update":{{"资产":"9999"}}}}
"删除李逸" → {{"action":"TABLE_DELETE","search":{{"姓名":"李逸"}},"update":{{}}}}
"查询全部" → {{"action":"TABLE_QUERY","search":{{}},"update":{{}}}}

用户输入: {text}
只输出 JSON: {{"action":"...","search":{{...}},"update":{{...}}}}"""

STAGE2_RPA = """你是RPA执行专家。提取流程名和参数。

用户输入: {text}
只输出 JSON: {{"action":"RPA_EXECUTION","flow_name":"流程名","params":{{}}}}"""

STAGE2_KB = """你是知识库检索专家。提取搜索关键词。

用户输入: {text}
只输出 JSON: {{"action":"KB_SEARCH","keywords":"关键词"}}"""


class AIRouter:

    def __init__(self, llm):
        self.llm = llm

    async def route(self, text: str) -> RouteResult:
        """
        Stage 1 → Stage 2 (按需)
        返回完整 RouteResult
        """

        # ── Stage 1: 意图分类 ──
        stage1 = await self._call_ai(STAGE1_PROMPT.format(text=text))
        intent = stage1.get("intent", "CHAT")
        print(f"  [AI S1] intent={intent}")

        # CHAT 直接返回，不调 Stage 2
        if intent == "CHAT":
            return RouteResult(intent="CHAT", action="", source="ai",
                              reason="stage1: chat", confidence=0.8)

        # ── Stage 2: 领域细化 ──
        if intent == "TABLE":
            return await self._stage2_table(text)
        if intent == "RPA":
            return await self._stage2_rpa(text)
        if intent == "KB":
            return await self._stage2_kb(text)

        return RouteResult(intent="CHAT", source="ai", reason="fallback")

    # ── Stage 2 各领域 ──

    async def _stage2_table(self, text: str) -> RouteResult:
        prompt = STAGE2_TABLE.format(field_names="待agent注入", text=text)
        data = await self._call_ai(prompt)
        print(f"  [AI S2] table → action={data.get('action','?')}")

        return RouteResult(
            intent="TABLE",
            action=data.get("action", "TABLE_QUERY"),
            source="ai",
            confidence=0.9,
            table_name=data.get("table_name", ""),
            search=data.get("search", {}),
            update=data.get("update", {}),
            reason="stage2: table",
        )

    async def _stage2_rpa(self, text: str) -> RouteResult:
        prompt = STAGE2_RPA.format(text=text)
        data = await self._call_ai(prompt)
        return RouteResult(
            intent="RPA",
            action=data.get("action", "RPA_EXECUTION"),
            source="ai",
            confidence=0.9,
            search=data.get("params", {}),
            reason="stage2: rpa",
        )

    async def _stage2_kb(self, text: str) -> RouteResult:
        prompt = STAGE2_KB.format(text=text)
        data = await self._call_ai(prompt)
        return RouteResult(
            intent="KB",
            action="KB_SEARCH",
            source="ai",
            confidence=0.9,
            reason="stage2: kb",
        )

    # ── LLM 调用 ──

    async def _call_ai(self, prompt: str) -> dict:
        try:
            resp = await self.llm.ainvoke(prompt)
            # 清理可能的 markdown 包裹
            resp = resp.strip().removeprefix("```json").removesuffix("```").strip()
            return json.loads(resp)
        except Exception as e:
            print(f"  [AI] parse error: {e} | raw: {resp[:100] if 'resp' in dir() else 'N/A'}")
            return {}
