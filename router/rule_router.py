# router/rule_router.py

from router.intent_router import Intent


class RuleRouter:

    KB_KEYWORDS = ["知识库"]

    TABLE_KEYWORDS = []

    RPA_KEYWORDS = ["RPA", "自动化"]

    def route(self, text: str):

        for k in self.KB_KEYWORDS:
            if k in text:
                return Intent.KB

        for k in self.TABLE_KEYWORDS:
            if k in text:
                return Intent.TABLE

        for k in self.RPA_KEYWORDS:
            if k in text:
                return Intent.RPA

        return None