# router/action_intent.py

from enum import Enum


class ActionIntent(str, Enum):

    # RPA
    RPA_EXECUTION = "rpa_execution"

    # TABLE
    TABLE_QUERY = "table_query"
    TABLE_INSERT = "table_insert"
    TABLE_UPDATE = "table_update"
    TABLE_DELETE = "table_delete"

    # KB
    KB_SEARCH = "kb_search"

    # CHAT
    CHAT = "chat"

    UNKNOWN = "unknown"