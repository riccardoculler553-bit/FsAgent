# core/logger.py

import json
from datetime import datetime


def log_trace(trace_id, message, action):

    log = {
        "trace_id": trace_id,
        "time": datetime.now().isoformat(),
        "group_id": message.group_id,
        "user_id": message.user_id,
        "text": message.text,
        "action_intent": str(action)
    }

    print("[TRACE]", json.dumps(log, ensure_ascii=False))