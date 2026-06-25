# router/action_mapper.py

from router.action_intent import ActionIntent


class ActionMapper:

    def map(self, route_result):

        """
        route_result: AI Router 输出的 RouteResult
        """

        if route_result is None:
            return ActionIntent.CHAT

        action = getattr(route_result, "action", None)

        if not action:
            return ActionIntent.CHAT

        return self._map_action(action)

    def _map_action(self, action: str):

        mapping = {

            # TABLE 系列
            "TABLE_INSERT": ActionIntent.TABLE_INSERT,
            "TABLE_DELETE": ActionIntent.TABLE_DELETE,
            "TABLE_UPDATE": ActionIntent.TABLE_UPDATE,
            "TABLE_QUERY": ActionIntent.TABLE_QUERY,

            # RPA
            "RPA_EXECUTION": ActionIntent.RPA_EXECUTION,

            # KB
            "KB_SEARCH": ActionIntent.KB_SEARCH,
        }

        return mapping.get(action, ActionIntent.CHAT)