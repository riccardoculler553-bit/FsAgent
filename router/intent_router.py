# router/intent.py

from enum import Enum


class Intent(str, Enum):

    RPA = "rpa"
    TABLE = "table"
    KB = "kb"
    CHAT = "chat"
    UNKNOWN = "unknown"