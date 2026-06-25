# Tool/fsTable/bitable_service.py
"""
飞书多维表格服务封装
Token 由 APP_ID/APP_SECRET 自动获取 (lark SDK 内置)
"""

import os
import re
import lark_oapi as lark
from lark_oapi.api.bitable.v1 import (
    AppTableRecord,
    CreateAppTableRecordRequest,
    SearchAppTableRecordRequest,
    SearchAppTableRecordRequestBody,
    UpdateAppTableRecordRequest,
    DeleteAppTableRecordRequest,
    ListAppTableFieldRequest,
    ListAppTableRequest,
)
from dotenv import load_dotenv

load_dotenv()

APP_ID = os.getenv("APP_ID")
APP_SECRET = os.getenv("APP_SECRET")

def _get_client():
    return (
        lark.Client.builder()
        .app_id(APP_ID)
        .app_secret(APP_SECRET)
        .build()
    )


class BitableService:

    def __init__(self, app_token: str):
        self.app_token = app_token
        self.client = _get_client()

    # ─── 字段查询 ────────────────────────────────

    def get_table_fields(self, table_id: str) -> list:
        req = (
            ListAppTableFieldRequest.builder()
            .app_token(self.app_token)
            .table_id(table_id)
            .page_size(100)
            .build()
        )
        resp = self.client.bitable.v1.app_table_field.list(req)
        if not resp.success():
            raise RuntimeError(f"获取字段失败: {resp.code} {resp.msg}")

        items = resp.data.items or []
        return [
            {
                "name": getattr(it, "field_name", ""),
                "type": str(getattr(it, "type", "?")),
                "desc": getattr(it, "description", "") or "",
            }
            for it in items
        ]

    # ─── 表格列表 ────────────────────────────────

    def list_tables(self) -> list:
        """
        获取 base 下所有表格
        返回: [{"table_id": "tblxxx", "name": "员工表"}, ...]
        """
        req = (
            ListAppTableRequest.builder()
            .app_token(self.app_token)
            .page_size(100)
            .build()
        )
        resp = self.client.bitable.v1.app_table.list(req)
        if not resp.success():
            raise RuntimeError(f"获取表格列表失败: {resp.code} {resp.msg}")

        items = resp.data.items or []
        return [
            {"table_id": getattr(t, "table_id", ""), "name": getattr(t, "name", "")}
            for t in items
        ]

    def find_table(self, keyword: str) -> dict:
        """
        按名称模糊查找表格
        返回匹配的 {"table_id": "...", "name": "..."} 或 None
        """
        tables = self.list_tables()
        keyword_lower = keyword.strip().lower()
        for t in tables:
            if t["name"].lower() in keyword_lower:
                return t
        return None

    # ─── URL 解析 ────────────────────────────────

    @staticmethod
    def parse_table_url(text: str) -> dict:
        m = re.search(r'/base/([A-Za-z0-9]+)', text)
        app_token = m.group(1) if m else ""
        m = re.search(r'table=([A-Za-z0-9]+)', text)
        table_id = m.group(1) if m else ""
        if not app_token:
            m = re.search(r'([A-Za-z0-9]{20,})', text)
            if m:
                app_token = m.group(1)
        return {"app_token": app_token, "table_id": table_id}

    # ─── CRUD ────────────────────────────────────

    def create_record(self, table_id: str, fields: dict) -> dict:
        record = AppTableRecord.builder().fields(fields).build()
        req = (
            CreateAppTableRecordRequest.builder()
            .app_token(self.app_token)
            .table_id(table_id)
            .request_body(record)
            .build()
        )
        resp = self.client.bitable.v1.app_table_record.create(req)
        if not resp.success():
            raise RuntimeError(f"create 失败: {resp.code} {resp.msg}")
        return {
            "record_id": resp.data.record.record_id,
            "fields": resp.data.record.fields,
        }

    def query_records(
        self, table_id: str, filter_str: str = None, field_names: list = None
    ) -> list:
        bb = SearchAppTableRecordRequestBody.builder().automatic_fields(True)
        if filter_str:
            bb = bb.filter(filter_str)
        if field_names:
            # 指定返回字段, 否则可能为空
            bb = bb.field_names(field_names)
        req = (
            SearchAppTableRecordRequest.builder()
            .app_token(self.app_token)
            .table_id(table_id)
            .request_body(bb.build())
            .build()
        )
        resp = self.client.bitable.v1.app_table_record.search(req)
        if not resp.success():
            raise RuntimeError(f"query 失败: {resp.code} {resp.msg}")
        return [
            {"record_id": r.record_id, "fields": r.fields}
            for r in (resp.data.items or [])
        ]

    def update_record(
        self, table_id: str, record_id: str, fields: dict
    ) -> dict:
        record = AppTableRecord.builder().fields(fields).build()
        req = (
            UpdateAppTableRecordRequest.builder()
            .app_token(self.app_token)
            .table_id(table_id)
            .record_id(record_id)
            .request_body(record)
            .build()
        )
        resp = self.client.bitable.v1.app_table_record.update(req)
        if not resp.success():
            raise RuntimeError(f"update 失败: {resp.code} {resp.msg}")
        return {
            "record_id": resp.data.record.record_id,
            "fields": resp.data.record.fields,
        }

    def delete_record(self, table_id: str, record_id: str) -> bool:
        req = (
            DeleteAppTableRecordRequest.builder()
            .app_token(self.app_token)
            .table_id(table_id)
            .record_id(record_id)
            .build()
        )
        resp = self.client.bitable.v1.app_table_record.delete(req)
        if not resp.success():
            raise RuntimeError(f"delete 失败: {resp.code} {resp.msg}")
        return resp.data.deleted
