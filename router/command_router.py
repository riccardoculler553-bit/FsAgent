# router/command_router.py

from router.intent_router import Intent


class CommandRouter:

    def route(self, text: str):

        text = text.strip()

        if text.startswith("/rpa"):
            return Intent.RPA

        if text.startswith("/table"):
            return Intent.TABLE

        if text.startswith("/kb"):
            return Intent.KB

        return None