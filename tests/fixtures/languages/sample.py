import os


class SampleService:
    def __init__(self, name: str) -> None:
        self.name = name

    def run(self) -> str:
        total = 0
        total += len(self.name)
        total += len(os.getcwd())
        total += 1
        return f"{self.name}:{total}"


def helper(value: int) -> int:
    result = value
    result += 1
    result += 2
    return result
