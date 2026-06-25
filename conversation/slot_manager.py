class SlotManager:
    """统一参数槽位管理器"""

    def set(self, session, key, value):
        session.slots[key] = value

    def get(self, session, key):
        return session.slots.get(key)

    def has_all_required(self, session, required_keys):
        return all(
            k in session.slots and session.slots[k] is not None
            for k in required_keys
        )

    def missing_keys(self, session, required_keys):
        return [k for k in required_keys if not session.slots.get(k)]

    def clear(self, session, key):
        """清除单个 slot"""
        if key in session.slots:
            del session.slots[key]

    def clear_all(self, session):
        """清除所有 slots"""
        session.slots = {}

    def to_dict(self, session):
        """返回 slots 副本"""
        return dict(session.slots)
