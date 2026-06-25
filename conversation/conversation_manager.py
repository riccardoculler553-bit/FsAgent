import uuid

from conversation.session import Session
from conversation.memory_store import MemoryStore
from conversation.workflow_state import WorkflowState


class ConversationManager:

    def __init__(self):
        self.memory = MemoryStore()

    def _key(self, group_id, user_id):
        return f"{group_id}:{user_id}"

    # 获取 or 创建 session
    def get_session(self, group_id, user_id):

        key = self._key(group_id, user_id)

        session = self.memory.get(key)

        if session:
            return session

        session = Session(
            session_id=str(uuid.uuid4()),
            group_id=group_id,
            user_id=user_id
        )

        self.memory.set(key, session)

        return session

    # 判断是否在任务中
    def is_in_workflow(self, session):
        return session.workflow_state != WorkflowState.IDLE

    # 设置任务状态
    def set_workflow_state(self, session, state):
        session.workflow_state = state

    # 设置当前Agent
    def set_agent(self, session, agent_name):
        session.current_agent = agent_name

    # 设置当前Action
    def set_action(self, session, action):
        session.current_action = action

    # 设置slot
    def set_slot(self, session, key, value):
        session.slots[key] = value

    # 获取slot
    def get_slot(self, session, key):
        return session.slots.get(key)

    # 写入历史
    def append_history(self, session, role, content):

        session.history.append({
            "role": role,
            "content": content
        })

        session.updated_at = session.updated_at

    # 重置会话（任务完成）
    def reset(self, session):

        session.workflow_state = WorkflowState.IDLE
        session.current_action = None
        session.current_agent = None
        session.slots = {}

