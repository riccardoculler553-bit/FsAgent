# agents/mock_agent.py
"""
MockAgent — 轻任务调度中心
===========================
负责三类场景:
  1. 低复杂度闲聊 / 简单问答  → DeepSeek 多轮对话
  2. 简单工具调用入口         → Skill Layer 分流
  3. 无需复杂推理的任务       → 直接处理后返回

Skill 分流规则 (关键词触发, MVP 阶段):
  file_skill  → 上传 / 读取 / 解析文件
  text_skill  → 文本处理 (翻译 / 摘要 / 格式化)
  ocr_skill   → 图片识别 (暂为 stub, Phase 2 接入)
"""

import os
import json
import httpx

DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY", "sk-d14c8f313d2f436cbe5c4f3503e7097e")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL    = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# 系统人设 —— 企业助手角色
SYSTEM_PROMPT = """你是一个企业内部智能助手，部署在飞书群中。

你的能力范围:
- 回答一般性问题、闲聊、安抚情绪
- 协助文本处理（翻译、摘要、格式转换）
- 引导用户使用系统功能（表格查询、流程执行、知识检索）

回答风格:
- 简洁专业，不啰嗦
- 遇到超出能力范围的问题，明确说明并引导用户使用正确功能
- 不捏造信息，不确定时直接说不确定

可用功能提示（当用户需要时告知）:
- 查询/新增/修改/删除表格数据：直接说"查询 XXX"
- 检索公司制度/流程文档：说"查找 XXX 制度"
- 执行自动化流程：说"执行 XXX 流程"
"""

# ── Skill 关键词路由表 ────────────────────────────
SKILL_ROUTES = {
    "file_skill": ["上传", "文件", "excel", "csv", "pdf", "附件", "表格文件", "下载"],
    "text_skill": ["翻译", "摘要", "总结", "格式化", "提取", "转换", "改写", "润色"],
    "ocr_skill":  ["识别", "图片", "截图", "扫描", "OCR"],
}

MAX_HISTORY_TURNS = 10  # 保留最近 N 轮，控制 context 长度


def _detect_skill(text: str) -> str | None:
    """关键词命中 → 返回 skill 名称，否则 None"""
    text_lower = text.lower()
    for skill, keywords in SKILL_ROUTES.items():
        if any(k in text_lower for k in keywords):
            return skill
    return None


def _trim_history(history: list) -> list:
    """只保留最近 MAX_HISTORY_TURNS 轮 user+assistant 对"""
    if len(history) <= MAX_HISTORY_TURNS * 2:
        return history
    return history[-(MAX_HISTORY_TURNS * 2):]


async def _call_deepseek(messages: list) -> str:
    """调用 DeepSeek Chat API，返回回复文本"""
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 800,
    }
    try:
        async with httpx.AsyncClient(
            base_url=DEEPSEEK_BASE_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=20.0,
        ) as client:
            resp = await client.post("/v1/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  [MockAgent] DeepSeek 调用失败: {e}")
        return "抱歉，我现在无法回答，请稍后再试。"


# ── Skill 执行（MVP stub，后续接真实实现）────────────
async def _run_file_skill(text: str) -> str:
    # Phase 2: 接入真实文件解析（Excel/CSV/PDF）
    return "📎 文件处理功能即将上线，目前请直接在飞书中操作文件。"


async def _run_text_skill(text: str, session=None) -> str:
    """文本处理 Skill：直接让 DeepSeek 处理，不走闲聊路径"""
    messages = [
        {"role": "system", "content": "你是一个文本处理专家。直接完成用户要求，不要解释，直接输出结果。"},
        {"role": "user",   "content": text},
    ]
    return await _call_deepseek(messages)


async def _run_ocr_skill(text: str) -> str:
    # Phase 2: 接入视觉模型
    return "🔍 图片识别功能正在开发中，敬请期待。"


SKILL_HANDLERS = {
    "file_skill": _run_file_skill,
    "text_skill": _run_text_skill,
    "ocr_skill":  _run_ocr_skill,
}


class MockAgent:
    """闲聊 & 轻任务调度 — 带多轮上下文的真实 LLM 回复"""

    async def run(self, action, message, session=None):
        text = message.text
        print(f"  [MockAgent] action={action} text={repr(text)}")

        # 1. Skill 分流
        skill = _detect_skill(text)
        if skill:
            print(f"  [MockAgent] → Skill 分流: {skill}")
            handler = SKILL_HANDLERS[skill]
            try:
                if skill == "text_skill":
                    return await handler(text, session)
                return await handler(text)
            except Exception as e:
                print(f"  [MockAgent] Skill 执行失败: {e}")
                return "技能执行出错，请稍后重试。"

        # 2. 多轮闲聊
        # 从 session.history 构建上下文
        history = []
        if session and session.history:
            raw = _trim_history(session.history)
            for entry in raw:
                role = entry.get("role")
                content = entry.get("content", "")
                if role in ("user", "assistant") and content:
                    history.append({"role": role, "content": content})

        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history + [
            {"role": "user", "content": text}
        ]

        reply = await _call_deepseek(messages)

        # 写入历史（由外层 dispatcher 负责 append_history，此处不重复写）
        print(f"  [MockAgent] 回复: {reply[:80]}")
        return reply