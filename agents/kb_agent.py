# agents/kb_agent.py
"""
KBAgent — Phase 1 完整 RAG 链路
=================================
流程:
  Query
    → KBRetriever.search(top_k=5)
    → 拼接上下文
    → DeepSeek LLM 生成答案（带来源引用）
    → 返回结构化回复

Phase 2 预留:
  - BM25 混合检索
  - metadata filter（按 tags/来源）
  - 多轮追问（跟进上下文）
"""

import os
import httpx

from conversation.workflow_state import WorkflowState
from conversation.conversation_manager import ConversationManager
from kb.retriever import KBRetriever

conv_mgr: ConversationManager = None

DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL    = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# 单例 retriever，进程内复用索引
_retriever: KBRetriever | None = None

def get_retriever() -> KBRetriever:
    global _retriever
    if _retriever is None:
        _retriever = KBRetriever()
    return _retriever


# ── Prompt 模板 ──────────────────────────────────────────────────────────────

KB_ANSWER_PROMPT = """你是企业内部知识库助手。请根据下面提供的参考文档回答用户问题。

规则：
1. 只使用参考文档中的信息作答
2. 如果文档中没有相关信息，明确说"知识库中暂无相关内容"，不要编造
3. 回答简洁，重点突出，使用中文
4. 如果有多个来源，在答案末尾用【来源：XXX】标注

---参考文档---
{context}
---

用户问题：{query}

请直接给出答案："""

NO_RESULT_PROMPT = """用户在知识库中查询：{query}

知识库暂时没有找到相关内容。请用以下方式回复用户：
1. 告知没有找到相关内容
2. 建议用户联系相关负责人
3. 提示用户可以换个关键词重试

直接输出回复内容，不要加任何前缀："""


# ── LLM 调用 ────────────────────────────────────────────────────────────────

async def _llm_answer(prompt: str) -> str:
    try:
        async with httpx.AsyncClient(
            base_url=DEEPSEEK_BASE_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=25.0,
        ) as client:
            resp = await client.post(
                "/v1/chat/completions",
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,   # 知识库回答要保守
                    "max_tokens": 1000,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        import traceback
        print(f"  [KBAgent] LLM 调用失败: {e}")
        traceback.print_exc()
        return "抱歉，知识库服务暂时不可用，请稍后再试。"


# ── 上下文拼接 ───────────────────────────────────────────────────────────────

def _build_context(results: list[dict], min_score: float = 0.1) -> str:
    """
    将检索结果拼接为 LLM 可读的上下文块。
    过滤掉相似度过低的结果（min_score 阈值）。
    """
    filtered = [r for r in results if r.get("_score", 0) >= min_score]
    if not filtered:
        return ""
    blocks = []
    for i, doc in enumerate(filtered, 1):
        title   = doc.get("title", f"文档{i}")
        content = doc.get("content", "")
        source  = doc.get("source", "")
        score   = doc.get("_score", 0)
        source_str = f"（来源：{source}）" if source else ""
        blocks.append(f"[{i}] 《{title}》{source_str} 相关度:{score:.2f}\n{content}")
    return "\n\n".join(blocks)


class KBAgent:
    """知识库检索 + LLM 问答 Agent（Phase 1 RAG 完整链路）"""

    async def search(self, message, session=None):
        query = message.text.strip()
        print(f"  [KBAgent] 检索: {repr(query)}")

        retriever = get_retriever()

        # ── 检查知识库是否为空 ──
        if retriever.doc_count == 0:
            if session:
                conv_mgr.set_workflow_state(session, WorkflowState.SUCCESS)
            return (
                "📚 知识库目前为空。\n\n"
                "请先通过管理接口导入文档：\n"
                "  POST /kb/add  {title, content, source}\n\n"
                "或联系系统管理员初始化知识库内容。"
            )

        # ── 向量检索 ──
        try:
            results = await retriever.search(query, top_k=5)
        except Exception as e:
            print(f"  [KBAgent] 检索失败: {e}")
            if session:
                conv_mgr.set_workflow_state(session, WorkflowState.FAILED)
            return "知识库检索出错，请稍后重试。"

        print(f"  [KBAgent] 检索到 {len(results)} 条，"
              f"最高分: {results[0]['_score'] if results else 0:.3f}")

        # ── 构建上下文 ──
        context = _build_context(results, min_score=0.05)

        # ── LLM 生成答案 ──
        if context:
            prompt = KB_ANSWER_PROMPT.format(context=context, query=query)
        else:
            prompt = NO_RESULT_PROMPT.format(query=query)

        answer = await _llm_answer(prompt)

        if session:
            conv_mgr.set_workflow_state(session, WorkflowState.SUCCESS)

        return answer

    # ── 管理接口（供后续 HTTP/飞书命令调用）────────────────────────────────────

    async def add_documents(self, docs: list[dict]) -> str:
        """添加文档到知识库，返回操作结果"""
        retriever = get_retriever()
        try:
            added = await retriever.add_documents(docs)
            return f"✅ 成功导入 {added} 条文档，知识库共 {retriever.doc_count} 条"
        except Exception as e:
            return f"❌ 导入失败: {e}"

    async def get_status(self) -> str:
        """返回知识库状态"""
        retriever = get_retriever()
        return f"📚 知识库状态：共 {retriever.doc_count} 条文档"