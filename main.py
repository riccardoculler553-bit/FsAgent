# -*- coding: utf-8 -*-
"""
main.py —— feishu-agent 入口
============================
- 有飞书凭证 → 启动 WebSocket 监听 + 意图路由
- 无凭证     → 交互式测试模式
- --test     → 批量自动化测试
- --multi-turn → 多轮演示
"""

import os
import sys
import json
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

APP_ID = os.getenv("APP_ID")
APP_SECRET = os.getenv("APP_SECRET")

# ─── 模式判断 ──────────────────────────────────────
def main():
    if "--test" in sys.argv:
        asyncio.run(run_test_suite())
    elif "--multi-turn" in sys.argv:
        asyncio.run(run_multi_turn_demo())
    elif APP_ID and APP_SECRET:
        from webhook.feishu import start_listener
        start_listener()
    else:
        asyncio.run(interactive_mode())


# ═══════════════════════════════════════════════════
#  批量测试
# ═══════════════════════════════════════════════════
TEST_CASES = [
    "/rpa 执行日报自动化",
    "/table 查询所有记录",
    "/kb 查找考勤制度",
    "帮我执行自动化流程",
    "新增一条员工记录",
    "修改销售数据",
    "删除过期记录",
    "查询制度规范",
    "帮我把上个月的考勤数据导出来",
    "公司年假怎么申请",
    "我想做一个自动发邮件的机器人",
    "今天天气怎么样",
    "帮我查一下张三的工资",
    "执行财务对账流程",
    "你好",
    "帮我写一个Python脚本",
]


async def run_test_suite():
    from services.dispatcher import dispatch as dispatcher_dispatch
    from models.message import ChatMessage

    print("=" * 60)
    print("  feishu-agent 意图路由测试套件")
    print("=" * 60)

    results = []
    for i, text in enumerate(TEST_CASES, 1):
        msg = ChatMessage(
            message_id=f"test-{i}",
            group_id=f"test-group-{i}",
            user_id=f"test-user-{i}",
            text=text,
            chat_type="group",
            timestamp=int(datetime.now().timestamp() * 1000),
        )
        try:
            action, result, session = await dispatcher_dispatch(msg)
            results.append({"index": i, "text": text, "action": action.value, "result": result, "status": "OK"})
        except Exception as e:
            results.append({"index": i, "text": text, "action": "ERROR", "result": str(e), "status": "FAIL"})

    print("\n" + "=" * 60)
    print("  测试汇总")
    print("=" * 60)
    ok = sum(1 for r in results if r["status"] == "OK")
    print(f"  通过: {ok}/{len(results)}")
    for r in results:
        s = "✓" if r["status"] == "OK" else "✗"
        print(f"  {s} [{r['index']:2d}] {r['action']:20s} | {r['text'][:40]}")
    print("\n[JSON]")
    print(json.dumps(results, ensure_ascii=False, indent=2))


# ═══════════════════════════════════════════════════
#  多轮会话演示
# ═══════════════════════════════════════════════════
async def run_multi_turn_demo():
    from services.dispatcher import dispatch as dispatcher_dispatch
    from models.message import ChatMessage

    GROUP, USER = "demo-group", "demo-user"
    turns = [
        (1, "/rpa 执行查验通知", "新任务, 缺参数, 追问日期"),
        (2, "今天", "补参数, 完成执行"),
        (3, "/table 新增记录", "新任务, 缺参数, 追问表名"),
        (4, "员工表", "补参数, 完成新增"),
        (5, "你好", "新会话(CHAT), 因为上个任务已完成"),
    ]

    print("=" * 60)
    print("  多轮会话演示 (同一用户, 连续对话)")
    print("=" * 60)

    for turn, text, expected in turns:
        msg = ChatMessage(
            message_id=f"demo-{turn}", group_id=GROUP, user_id=USER,
            text=text, chat_type="group",
            timestamp=int(datetime.now().timestamp() * 1000),
        )
        print(f"\n{'─'*60}")
        print(f"  [第{turn}轮] 用户: {text}")
        print(f"        预期: {expected}")
        action, result, session = await dispatcher_dispatch(msg)
        print(f"        实际: {action.value} → {result}")

    print(f"\n{'='*60}")
    print("  多轮演示完成")


# ═══════════════════════════════════════════════════
#  交互测试
# ═══════════════════════════════════════════════════
async def interactive_mode():
    from services.dispatcher import dispatch as dispatcher_dispatch
    from models.message import ChatMessage

    print("=" * 60)
    print("  feishu-agent 交互测试模式")
    print("  输入消息测试意图路由, 输入 /quit 退出")
    print("=" * 60)
    print("  支持: /rpa /table /kb 命令路由")
    print("        AI 路由: DeepSeek 自动识别")
    print()

    i = 1
    while True:
        try:
            text = input(f"[{i}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出")
            break

        if not text:
            continue
        if text.lower() in ("/quit", "/exit", "quit", "exit"):
            print("退出")
            break

        msg = ChatMessage(
            message_id=f"cli-{i}", group_id="cli-group", user_id="cli-user",
            text=text, chat_type="group",
            timestamp=int(datetime.now().timestamp() * 1000),
        )
        try:
            action, result, session = await dispatcher_dispatch(msg)
            print(f"  → 意图: {action.value}")
            print(f"  → 回复: {result}")
        except Exception as e:
            print(f"  ✗ 异常: {e}")
            import traceback
            traceback.print_exc()
        i += 1
        print()


if __name__ == "__main__":
    main()
