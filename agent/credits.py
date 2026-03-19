class CreditLimitExceeded(Exception):
    pass


class CreditTracker:
    def __init__(self, max_credits: int):
        self.max_credits = max_credits
        self.used = 0

    def add(self, amount: int) -> None:
        if amount <= 0:
            return
        self.used += amount
        if self.used > self.max_credits:
            raise CreditLimitExceeded(
                f"maxCredits exceeded ({self.used} > {self.max_credits})"
            )
