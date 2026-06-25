# -*- coding: utf-8 -*-
"""
feishu.py —— 飞书消息接收 + 回复
================================
WebSocket 长连接接收群消息 → 解析 → dispatcher.dispatch() → 回复飞书
"""

import os
import json
import asyncio
import concurrent.futures
import threading
from datetime import datetime

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    ReplyMessageRequest, ReplyMessageRequestBody,
    CreateMessageRequest, CreateMessageRequestBody,
)
from dotenv import load_dotenv

from models.message import ChatMessage

load_dotenv()

APP_ID = os.getenv("APP_ID")
APP_SECRET = os.getenv("APP_SECRET")

# ─── 异步桥接 (线程池 + 独立事件循环) ────────────
_dispatch_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def _run_async_dispatch(msg):
    """在独立线程的新事件循环中运行异步 dispatcher"""
    loop = asyncio.new_event_loop()
    try:
        from services.dispatcher import dispatch as dispatcher_dispatch
        return loop.run_until_complete(dispatcher_dispatch(msg))
    finally:
        loop.close()

# ─── 回复用 API Client (REST) ──────────────────
_api_client = None


def _get_api_client():
    """懒加载 lark.Client (REST API), 用于发送回复消息"""
    global _api_client
    if _api_client is None:
        _api_client = (
            lark.Client.builder()
            .app_id(APP_ID)
            .app_secret(APP_SECRET)
            .build()
        )
    return _api_client


# ─── 消息监听器 ────────────────────────────────────


# ─── 消息去重 ────────────────────────────────────
_seen_ids = set()
_MAX_SEEN = 500

def _is_duplicate(message_id):
    if message_id in _seen_ids:
        return True
    _seen_ids.add(message_id)
    if len(_seen_ids) > _MAX_SEEN:
        _seen_ids.clear()
    return False

class FeishuMessageListener:
    """
    飞书事件回调 —— 同步方法, 线程池桥接异步 dispatcher
    """

    @staticmethod
    def handle_message(data):
        try:
            event = data.event
            sender_id = event.sender.sender_id.open_id
            msg = event.message

            # ── 去重: 相同 message_id 不重复处理 ──
            if _is_duplicate(msg.message_id):
                print(f"[飞书] 重复消息 {msg.message_id}, 跳过")
                return

            print(f"\n{'='*50}")
            print(f"[飞书] 收到消息 @ {datetime.now().isoformat(timespec='seconds')}")
            print(f"{'='*50}")

            # ── 解析消息体 ──
            text = ""
            try:
                content = json.loads(msg.content)
                print(f"[飞书] 消息内容: {json.dumps(content, ensure_ascii=False, indent=2)}")
                text = content.get("text", "")
            except Exception:
                print(f"[飞书] 原始内容: {msg.content}")
                text = msg.content

            if not text.strip():
                print("[飞书] 空消息, 跳过")
                return

            # ── 群聊只处理 @机器人 的消息 ──
            if msg.chat_type == "group" and "@_user_1" not in text:
                print("[飞书] 群聊非@机器人消息, 跳过")
                return

            # ── 清洗消息: 去除 @_user_1 ──
            text = text.replace("@_user_1", "").strip()
            if not text:
                print("[飞书] 清洗后空消息, 跳过")
                return

            # ── 构造 ChatMessage ──
            chat_msg = ChatMessage(
                message_id=msg.message_id,
                group_id=msg.chat_id,
                user_id=sender_id,
                text=text,
                chat_type=msg.chat_type,
                timestamp=int(datetime.now().timestamp() * 1000),
            )

            # ── 调用 dispatcher (线程池 + 独立事件循环) ──
            action, result, session = _dispatch_pool.submit(
                _run_async_dispatch, chat_msg
            ).result(timeout=30)

            print(f"[飞书] 意图={action.value} 回复={result[:80]}")
            print(f"session_detail ={session}")

            # ── 发送回复到飞书 ──
            _reply_message(msg.message_id, result)

        except Exception as e:
            print(f"[飞书] 处理异常: {e}")
            import traceback
            traceback.print_exc()

        print(f"{'='*50}\n")


# ─── 回复工具 ──────────────────────────────────────
def _reply_message(message_id: str, text: str):
    """回复飞书消息 (线程安全)"""
    try:
        client = _get_api_client()

        body = (
            ReplyMessageRequestBody.builder()
            .content(json.dumps({"text": text}))
            .msg_type("text")
            .build()
        )
        request = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(body)
            .build()
        )

        resp = client.im.v1.message.reply(request)
        if resp.success():
            print(f"[飞书] 回复成功 → {message_id}")
        else:
            print(f"[飞书] 回复失败: code={resp.code} msg={resp.msg}")

    except Exception as e:
        print(f"[飞书] 回复异常: {e}")


def send_to_chat(chat_id: str, text: str):
    """发送消息到指定群聊 (非回复)"""
    try:
        client = _get_api_client()

        body = (
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .content(json.dumps({"text": text}))
            .msg_type("text")
            .build()
        )
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(body)
            .build()
        )

        resp = client.im.v1.message.create(request)
        if resp.success():
            print(f"[飞书] 发送成功 → chat={chat_id}")
        else:
            print(f"[飞书] 发送失败: code={resp.code} msg={resp.msg}")

    except Exception as e:
        print(f"[飞书] 发送异常: {e}")


# ─── 启动入口 ──────────────────────────────────────
def start_listener():
    """启动飞书 WebSocket 监听 (阻塞)"""
    if not APP_ID or not APP_SECRET:
        print("[飞书] 缺少 APP_ID 或 APP_SECRET, 请在 .env 中配置")
        print("[飞书] 将进入测试模式 (不连接飞书)")
        return

    print(f"[飞书] APP_ID = {APP_ID}")
    print(f"[飞书] APP_SECRET = {APP_SECRET[:8]}***")

    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(FeishuMessageListener.handle_message)
        .build()
    )

    client = lark.ws.Client(
        APP_ID, APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )

    print("[飞书] WebSocket 监听启动成功")
    print("[飞书] 等待群消息中...\n")
    client.start()


if __name__ == "__main__":
    start_listener()
