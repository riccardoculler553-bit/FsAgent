# models/message.py

from dataclasses import dataclass


@dataclass
class ChatMessage:

    message_id: str
    group_id: str
    user_id: str
    text: str
    chat_type: str
    timestamp: int
