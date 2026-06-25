# agents/table_agent.py
"""
TableAgent v3 — AI 自适应写入
==============================
流程:
  1. 清洗消息 (@_user_1)
  2. 解析表格(URL/名称) → 拉取真实字段
  3. 一次性输入: 用 AI 解析自然语言 → 字段映射 → 直接执行
  4. 分步输入: 展示字段 → 收集条件 → 执行
"""

import json
import re
import os

import httpx

from conversation.workflow_state import WorkflowState
from conversation.conversation_manager import ConversationManager
from conversation.slot_manager import SlotManager
from Tool.fsTable.bitable_service import BitableService

conv_mgr: ConversationManager = None
slot_mgr: SlotManager = None

# 内部状态键
_STEP = "_table_step"
_TABLE_ID = "table_id"
_FIELDS = "_fields"
_APP_TOKEN = "app_token"
_OPERATION = "_operation"
_PENDING = "_pending_fields"

# 确认关键词
_CONFIRM_YES = {"确认", "是", "好", "确认", "yes", "y", "ok", "确定"}
_CONFIRM_NO = {"取消", "不行", "不要", "no", "n", "终止", "结束"}

def _clean(text: str) -> str:
    """统一清洗"""
    text = text.replace("@_user_1", "").strip()
    text = re.sub(r'^/\w+(\s+\w+)?\s*', '', text).strip()
    return text

class TableAgent:

    async def query(self, message, session=None):
        return await self._handle("table_query", message, session)

    async def insert(self, message, session=None):
        return await self._handle("table_insert", message, session)

    async def update(self, message, session=None):
        return await self._handle("table_update", message, session)

    async def delete(self, message, session=None):
        return await self._handle("table_delete", message, session)

    async def _handle(self, workflow_key, message, session):
        if session is None:
            return "[TABLE] 无 session"

        # 清洗
        raw = message.text
        message.text = _clean(message.text)
        print(f"  [TableAgent] {workflow_key}: raw={repr(raw)} clean={repr(message.text)}")

        if session.workflow_state == WorkflowState.IDLE:
            return await self._init_table(workflow_key, message, session)

        if session.workflow_state == WorkflowState.WAITING_INPUT:
            return await self._collect_conditions(workflow_key, message, session)

        if session.workflow_state == WorkflowState.RUNNING:
            return await self._execute(workflow_key, session, message.text)

        return "[TABLE] 未知状态"

    # ═══════════════════════════════════════════════
    #  首次: URL/名称解析 → 拉字段 → AI解析或提示
    # ═══════════════════════════════════════════════

    async def _init_table(self, workflow_key, message, session):
        text = message.text

        # 1. URL解析
        url_info = BitableService.parse_table_url(text)
        app_token = url_info["app_token"]
        table_id = url_info["table_id"]

        # 2. 用缓存/环境变量兜底
        if not app_token:
            app_token = slot_mgr.get(session, _APP_TOKEN) or os.getenv("BITABLE_APP_TOKEN", "")
        if not app_token:
            conv_mgr.set_workflow_state(session, WorkflowState.WAITING_INPUT)
            slot_mgr.set(session, _STEP, "need_url")
            return "请提供多维表格链接, 或设置 BITABLE_APP_TOKEN"

        slot_mgr.set(session, _APP_TOKEN, app_token)
        svc = BitableService(app_token=app_token)

        # 3. 没 table_id → 优先用 AI Stage2 给的 table_name
        if not table_id:
            ai_table = session.slots.get("table_name", "")
            if ai_table:
                found = svc.find_table(ai_table)
                if found:
                    table_id = found["table_id"]
                    slot_mgr.set(session, "_found_name", found["name"])

        # 仍未找到 → 关键词查找 → 列出所有表
        if not table_id:
            found = svc.find_table(text)
            if found:
                table_id = found["table_id"]
                slot_mgr.set(session, "_found_name", found["name"])
            else:
                tables = svc.list_tables()
                if tables:
                    lines = ["找到以下表格, 请选择:"]
                    for t in tables:
                        lines.append(f"  • {t['name']}")
                    conv_mgr.set_workflow_state(session, WorkflowState.WAITING_INPUT)
                    slot_mgr.set(session, _STEP, "need_table_name")
                    return "\n".join(lines)
                return "未找到表格, 请提供表名或链接"

        slot_mgr.set(session, _TABLE_ID, table_id)

        # 4. 拉取字段
        try:
            fields = svc.get_table_fields(table_id)
            slot_mgr.set(session, _FIELDS, fields)
        except RuntimeError as e:
            conv_mgr.set_workflow_state(session, WorkflowState.FAILED)
            return f"❌ 获取表格信息失败: {e}"

        if not fields:
            return "表格无字段数据, 请确认表ID"

        slot_mgr.set(session, _OPERATION, workflow_key)
        field_names = [f["name"] for f in fields]
        field_list = ", ".join(field_names)
        table_name = slot_mgr.get(session, "_found_name") or table_id

        # 5. 用 AI Stage2 已有的结构化数据 (search/update)
        ai_search = session.slots.get("search", {})
        ai_update = session.slots.get("update", {})

        if workflow_key in ("table_query", "table_delete") and ai_search:
            # 查询/删除: 用 search 作为条件
            slot_mgr.set(session, _PENDING, ai_search)
            conv_mgr.set_workflow_state(session, WorkflowState.WAITING_INPUT)
            slot_mgr.set(session, _STEP, "confirming")
            items = [f"  {k}={v}" for k, v in ai_search.items() if v]
            return (f"即将向「{table_name}」{self._op_name(workflow_key)}:\n"
                    + "\n".join(items)
                    + "\n\n确认回复「确认」, 取消回复「取消」")

        if workflow_key in ("table_insert", "table_update") and ai_update:
            # 新增: 只用 update。修改: search+update 都存
            pending = {}
            if workflow_key == "table_update" and ai_search:
                pending["_search"] = ai_search
            pending.update(ai_update)
            slot_mgr.set(session, _PENDING, pending)
            conv_mgr.set_workflow_state(session, WorkflowState.WAITING_INPUT)
            slot_mgr.set(session, _STEP, "confirming")
            items = []
            if "_search" in pending:
                items.append(f"  查找: " + ", ".join(f"{k}={v}" for k, v in pending["_search"].items()))
            items.append(f"  {self._op_name(workflow_key)}: " + ", ".join(f"{k}={v}" for k, v in ai_update.items()))
            return (f"即将向「{table_name}」{self._op_name(workflow_key)}:\n"
                    + "\n".join(items)
                    + "\n\n确认回复「确认」, 取消回复「取消」")

        # 6. AI 无结构化数据 → 分步交互
        conv_mgr.set_workflow_state(session, WorkflowState.WAITING_INPUT)
        slot_mgr.set(session, _STEP, "collecting")
        return self._ask_conditions(workflow_key, field_names, field_list)

    # ═══════════════════════════════════════════════
    #  续任务
    # ═══════════════════════════════════════════════

    async def _collect_conditions(self, workflow_key, message, session):
        text = message.text
        step = slot_mgr.get(session, _STEP)

        # 通用取消/结束 (任何步骤都生效)
        if text in _CONFIRM_NO or text in {"结束", "end", "exit", "quit", "/cancel", "/end"}:
            conv_mgr.set_workflow_state(session, WorkflowState.FAILED)
            conv_mgr.reset(session)
            return "已取消当前操作"

        if step == "need_url":
            # 重新走 init
            return await self._init_table(workflow_key, message, session)

        if step == "need_table_name":
            return await self._resolve_table_name(message, session, workflow_key)

        if step == "need_table_id":
            return await self._resolve_table_id(message, session, workflow_key)

        # confirming → 确认/取消 (必须在 AI 解析之前!)
        if step == "confirming":
            return await self._handle_confirm(workflow_key, message, session)

        # collecting → 尝试 AI 一次性解析
        fields_info = slot_mgr.get(session, _FIELDS) or []
        field_names = [f["name"] for f in fields_info]

        fields_dict = await self._ai_parse(text, field_names)
        if fields_dict:
            # 展示解析结果, 等待确认
            slot_mgr.set(session, _PENDING, fields_dict)
            slot_mgr.set(session, _STEP, "confirming")
            items = [f"  {k}={v}" for k, v in fields_dict.items()]
            return f"即将{self._op_name(workflow_key)}:\n" + "\n".join(items) + "\n\n确认请回复「确认」, 取消请回复「取消」"

        # AI 解析失败 → 回退到格式提示
        return await self._execute(workflow_key, session, text)

    # ═══════════════════════════════════════════════
    #  子步骤: 解析表名/ID
    # ═══════════════════════════════════════════════

    async def _resolve_table_name(self, message, session, workflow_key):
        text = message.text
        svc = BitableService(app_token=slot_mgr.get(session, _APP_TOKEN))
        found = svc.find_table(text)
        if not found:
            return f"未找到表格「{text}」, 请重新输入"
        return await self._finish_table_setup(svc, found["table_id"], session, workflow_key)

    async def _resolve_table_id(self, message, session, workflow_key):
        text = message.text
        svc = BitableService(app_token=slot_mgr.get(session, _APP_TOKEN))
        if re.match(r'^tbl\w+$', text):
            table_id = text
        else:
            found = svc.find_table(text)
            table_id = found["table_id"] if found else text
        return await self._finish_table_setup(svc, table_id, session, workflow_key)

    async def _finish_table_setup(self, svc, table_id, session, workflow_key):
        try:
            fields = svc.get_table_fields(table_id)
        except RuntimeError as e:
            return f"❌ 获取表格信息失败: {e}"

        slot_mgr.set(session, _TABLE_ID, table_id)
        slot_mgr.set(session, _FIELDS, fields)
        slot_mgr.set(session, _STEP, "collecting")
        field_names = [f["name"] for f in fields]
        field_list = ", ".join(field_names)
        return self._ask_conditions(workflow_key, field_names, field_list)

    # ═══════════════════════════════════════════════
    #  执行 CRUD
    # ═══════════════════════════════════════════════

    async def _execute(self, workflow_key, session, user_input=""):
        svc = BitableService(app_token=slot_mgr.get(session, _APP_TOKEN))
        table_id = slot_mgr.get(session, _TABLE_ID)
        fields_info = slot_mgr.get(session, _FIELDS) or []
        field_names = [f["name"] for f in fields_info]

        try:
            if workflow_key == "table_query":
                return self._do_query(svc, session, table_id, user_input)
            elif workflow_key == "table_insert":
                return self._do_insert(svc, session, table_id, user_input, field_names)
            elif workflow_key == "table_update":
                return self._do_update(svc, table_id, user_input)
            elif workflow_key == "table_delete":
                return self._do_delete(svc, table_id, user_input)
            return "[TABLE] 未知操作"
        except RuntimeError as e:
            conv_mgr.set_workflow_state(session, WorkflowState.FAILED)
            return f"❌ 操作失败: {e}"

    # ── 具体操作 ────────────────────────────────

    def _do_query(self, svc, session, table_id, user_input):
        fields_info = slot_mgr.get(session, _FIELDS) or []
        fnames = [f["name"] for f in fields_info]
        clean = user_input.strip()
        if not clean or clean in ("全部", "all", "所有"):
            records = svc.query_records(table_id, field_names=fnames)
        elif "=" in clean or "CurrentValue" in clean:
            records = svc.query_records(table_id, filter_str=clean, field_names=fnames)
        else:
            records = svc.query_records(table_id, field_names=fnames)
        conv_mgr.set_workflow_state(session, WorkflowState.SUCCESS)
        return self._format_records(records)

    def _do_query_direct(self, svc, session, table_id, fields_dict):
        """查询所有记录, 客户端按条件过滤"""
        fields_info = slot_mgr.get(session, _FIELDS) or []
        fnames = [f["name"] for f in fields_info]
        records = svc.query_records(table_id, field_names=fnames)

        # 客户端过滤: 匹配 fields_dict 中的值
        if fields_dict:
            filtered = []
            for r in records:
                match = True
                for k, v in fields_dict.items():
                    if v:
                        rv = r.get("fields", {}).get(k)
                        # fields 可能是 [{"text": "xxx"}] 结构
                        if isinstance(rv, list) and rv:
                            rv = rv[0].get("text", "") if isinstance(rv[0], dict) else str(rv[0])
                        rv = str(rv) if rv else ""
                        if v not in rv:
                            match = False
                            break
                if match:
                    filtered.append(r)
            records = filtered

        conv_mgr.set_workflow_state(session, WorkflowState.SUCCESS)
        return self._format_records(records)

    def _do_insert(self, svc, session, table_id, user_input, field_names):
        fields = self._parse_kv(user_input)
        if not fields:
            conv_mgr.set_workflow_state(session, WorkflowState.WAITING_INPUT)
            slot_mgr.set(session, _STEP, "collecting")
            return f"请按格式输入: 字段名=值, 字段名=值\n可用字段: {', '.join(field_names)}"
        return self._do_insert_direct(svc, session, table_id, fields)

    def _do_insert_direct(self, svc, session, table_id, fields):
        result = svc.create_record(table_id, fields)
        conv_mgr.set_workflow_state(session, WorkflowState.SUCCESS)
        table_name = slot_mgr.get(session, "_found_name") or table_id
        return (
            f"✅ 已向「{table_name}」新增成功\n"
            f"record_id: {result['record_id']}\n"
            f"字段: {json.dumps(result['fields'], ensure_ascii=False)}"
        )

    def _do_update(self, svc, table_id, user_input):
        parts = self._parse_kv(user_input)
        record_id = parts.pop("record_id", None) or parts.pop("_record_id", None)
        if not record_id:
            parts_list = user_input.strip().split(None, 1)
            if len(parts_list) >= 2:
                record_id = parts_list[0]
                parts = self._parse_kv(parts_list[1])
        if not record_id:
            return "请提供: record_id 字段=值,字段=值"
        if not parts:
            return "请提供要修改的字段"
        try:
            result = svc.update_record(table_id, record_id, parts)
            return f"✅ 修改成功\nrecord_id: {result['record_id']}"
        except RuntimeError as e:
            return f"❌ 修改失败: {e}"

    def _do_delete(self, svc, table_id, user_input):
        record_id = user_input.strip()
        if not record_id:
            return "请提供要删除的 record_id"
        try:
            ok = svc.delete_record(table_id, record_id)
            return "✅ 删除成功" if ok else "⚠️ 删除失败"
        except RuntimeError as e:
            return f"❌ 删除失败: {e}"

    def _do_batch_delete(self, svc, session, table_id, fields_dict, table_name):
        """按条件批量删除: 先查询匹配记录 → 逐条删除"""
        fields_info = slot_mgr.get(session, _FIELDS) or []
        fnames = [f["name"] for f in fields_info]
        records = svc.query_records(table_id, field_names=fnames)

        # 客户端过滤
        matched = []
        for r in records:
            match = True
            for k, v in fields_dict.items():
                if v:
                    rv = r.get("fields", {}).get(k)
                    if isinstance(rv, list) and rv:
                        rv = rv[0].get("text", "") if isinstance(rv[0], dict) else str(rv[0])
                    rv = str(rv) if rv else ""
                    if v not in rv:
                        match = False
                        break
            if match:
                matched.append(r)

        if not matched:
            return f"未找到匹配「{table_name}」中条件的记录, 无需删除"

        deleted = 0
        failed = 0
        for r in matched:
            try:
                ok = svc.delete_record(table_id, r["record_id"])
                if ok:
                    deleted += 1
                else:
                    failed += 1
            except RuntimeError:
                failed += 1

        return f"✅ 已从「{table_name}」删除 {deleted} 条记录" + (f", {failed} 条失败" if failed else "")

    def _do_batch_update(self, svc, session, table_id, search, update_fields, table_name):
        """search=找哪些记录, update_fields=改成什么"""
        fields_info = slot_mgr.get(session, _FIELDS) or []
        fnames = [f["name"] for f in fields_info]
        records = svc.query_records(table_id, field_names=fnames)

        matched = []
        for r in records:
            match = True
            for k, v in search.items():
                if v:
                    rv = r.get("fields", {}).get(k)
                    if isinstance(rv, list) and rv:
                        rv = rv[0].get("text", "") if isinstance(rv[0], dict) else str(rv[0])
                    rv = str(rv) if rv else ""
                    if v not in rv:
                        match = False
                        break
            if match:
                matched.append(r)

        if not matched:
            return f"未找到匹配「{table_name}」中条件的记录"

        updated = 0
        failed = 0
        for r in matched:
            try:
                svc.update_record(table_id, r["record_id"], update_fields)
                updated += 1
            except RuntimeError:
                failed += 1

        return f"✅ 已修改「{table_name}」中 {updated} 条记录" + (f", {failed} 条失败" if failed else "")

    # ─── AI 解析 ──────────────────────────────────

    def _op_name(self, workflow_key):
        return {"table_insert": "新增", "table_query": "查询",
                "table_update": "修改", "table_delete": "删除"}.get(workflow_key, "操作")

    async def _ai_extract_table(self, text: str, table_names: list) -> dict:
        """用 AI 从自然语言中提取表名, 返回 {table_id, name} 或 None"""
        if not table_names:
            return None

        tables_info = []
        # 需要查 table_id 映射
        svc = BitableService(app_token=os.getenv("BITABLE_APP_TOKEN", ""))
        all_tables = svc.list_tables()
        name_to_id = {t["name"]: t["table_id"] for t in all_tables}

        prompt = f"""从用户输入中提取表格名称。仅在用户明确提到表格时匹配。

可用表格: {', '.join(table_names)}

用户输入: {text}

规则:
- 用户明确说"登记表"/"员工表"等 → 匹配最接近的表格
- 用户只说"新增"/"查询"/"写入"没提表名 → 返回空
- 不要猜测

只输出 JSON: {{"table_name": "匹配的表名"}}
如果用户没提到表格, 输出: {{"table_name": ""}}"""

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {os.getenv('DEEPSEEK_API_KEY', '')}", "Content-Type": "application/json"},
                    json={"model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"), "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "max_tokens": 100},
                )
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                m = re.search(r'"table_name"\s*:\s*"([^"]+)"', content)
                if m:
                    name = m.group(1)
                    tid = name_to_id.get(name)
                    if tid:
                        print(f"  [AI Extract] 表名: {name} → {tid}")
                        return {"table_id": tid, "name": name}
        except Exception as e:
            import traceback
            print(f"  [AI Extract] 失败: {e}")
            traceback.print_exc()
        return None

    async def _handle_confirm(self, workflow_key, message, session):
        text = _clean(message.text).strip()
        if text in _CONFIRM_YES:
            # 确认 → 执行
            fields_dict = slot_mgr.get(session, _PENDING) or {}
            svc = BitableService(app_token=slot_mgr.get(session, _APP_TOKEN))
            table_id = slot_mgr.get(session, _TABLE_ID)
            table_name = slot_mgr.get(session, "_found_name") or table_id
            try:
                if workflow_key == "table_insert":
                    result = self._do_insert_direct(svc, session, table_id, fields_dict)
                elif workflow_key == "table_query":
                    result = self._do_query_direct(svc, session, table_id, fields_dict)
                elif workflow_key == "table_update":
                    search = fields_dict.pop("_search", {})
                    update_fields = {k: v for k, v in fields_dict.items()
                                     if k not in ("record_id", "_search")}
                    record_id = fields_dict.get("record_id", "")
                    if record_id and update_fields:
                        try:
                            result = svc.update_record(table_id, record_id, update_fields)
                            result = f"✅ 修改成功\nrecord_id: {result['record_id']}"
                        except RuntimeError as e:
                            result = f"❌ 修改失败: {e}"
                    else:
                        result = self._do_batch_update(
                            svc, session, table_id, search, update_fields, table_name)
                elif workflow_key == "table_delete":
                    record_id = fields_dict.get("record_id", "")
                    if record_id:
                        try:
                            ok = svc.delete_record(table_id, record_id)
                            result = "✅ 删除成功" if ok else "⚠️ 删除失败"
                        except RuntimeError as e:
                            result = f"❌ 删除失败: {e}"
                    else:
                        # 无 record_id → 按条件批量删除: 先查后删
                        result = self._do_batch_delete(svc, session, table_id, fields_dict, table_name)
                else:
                    result = f"操作完成: {json.dumps(fields_dict, ensure_ascii=False)}"
                conv_mgr.set_workflow_state(session, WorkflowState.SUCCESS)
                return result
            except RuntimeError as e:
                conv_mgr.set_workflow_state(session, WorkflowState.FAILED)
                return f"❌ 操作失败: {e}"

        if text in _CONFIRM_NO:
            # 取消 → 重新询问
            slot_mgr.set(session, _PENDING, {})
            conv_mgr.set_workflow_state(session, WorkflowState.WAITING_INPUT)
            slot_mgr.set(session, _STEP, "collecting")
            fields_info = slot_mgr.get(session, _FIELDS) or []
            field_names = [f["name"] for f in fields_info]
            return self._ask_conditions(workflow_key, field_names, ", ".join(field_names))

        # 其他输入 → 重新 AI 解析（可能是修改了数据）
        fields_info = slot_mgr.get(session, _FIELDS) or []
        field_names = [f["name"] for f in fields_info]
        fields_dict = await self._ai_parse(text, field_names)
        if fields_dict:
            slot_mgr.set(session, _PENDING, fields_dict)
            items = [f"  {k}={v}" for k, v in fields_dict.items()]
            return f"已更新:\n" + "\n".join(items) + "\n\n确认请回复「确认」"
        return "请回复「确认」执行, 或回复「取消」放弃, 或重新输入数据"

    async def _ai_parse(self, text: str, field_names: list) -> dict:
        """
        用 DeepSeek 将自然语言 → 字段值映射
        "李逸，13488888888" + ["姓名","手机号"] → {"姓名":"李逸","手机号":"13488888888"}
        返回 {} 表示解析失败
        """
        if not text or not field_names:
            return {}

        prompt = f"""你是一个数据录入助手。将用户输入解析为JSON字段映射。

可用字段: {', '.join(field_names)}

用户输入: {text}

规则:
1. 按顺序将值匹配到字段
2. 手机号、电话 → 匹配到手机/电话相关字段
3. 中文姓名 → 匹配到姓名/名称字段
4. 仅返回JSON, 无其他文字

只输出:
{{"字段名": "值", ...}}"""

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {os.getenv('DEEPSEEK_API_KEY', 'sk-d14...097e')}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.0,
                        "max_tokens": 200,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()

                # 提取 JSON
                m = re.search(r'\{[^}]+\}', content)
                if m:
                    result = json.loads(m.group())
                    # 过滤只保留有效字段
                    return {k: v for k, v in result.items() if k in field_names and v}
        except Exception as e:
            print(f"  [AI Parse] 失败: {e}")

        return {}

    # ── 工具 ────────────────────────────────────

    def _parse_kv(self, text: str) -> dict:
        result = {}
        for part in text.split(","):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                result[k.strip()] = v.strip()
        return result

    def _format_records(self, records: list) -> str:
        if not records:
            return "✅ 未找到匹配记录"
        lines = [f"✅ 查询到 {len(records)} 条记录:"]
        for r in records[:10]:
            fields_str = json.dumps(r["fields"], ensure_ascii=False)
            lines.append(f"  [{r['record_id']}] {fields_str}")
        if len(records) > 10:
            lines.append(f"  ... 共 {len(records)} 条, 仅显示前10条")
        return "\n".join(lines)

    def _ask_conditions(self, workflow_key, field_names, field_list):
        if workflow_key == "table_query":
            return (
                f"表格字段: {field_list}\n\n"
                "请提供查询条件:\n"
                "  • 全部 (查看所有)\n"
                "  • CurrentValue.[字段名]=\"值\""
            )
        elif workflow_key == "table_insert":
            return (
                f"表格字段: {field_list}\n\n"
                "请提供新记录 (可直接说: 张三,138xxxx):\n"
                f"  或格式: {field_names[0] if field_names else '字段'}=xxx"
            )
        elif workflow_key in ("table_update", "table_delete"):
            return (
                f"表格字段: {field_list}\n\n"
                "请提供 record_id + 内容"
            )
        return f"可用字段: {field_list}"
