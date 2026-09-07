from typing import TypeAlias; import os; import platform; import sys  # noqa: I001

Identifier: TypeAlias = int


class Named:
    name: str


class Greeter(Named):
    def greet(self, recipient: str) -> str:
        return format_message(recipient)


def format_message(recipient: str) -> str:
    return f"Hello, {recipient}!"


async def load_greeter() -> Greeter:
    return Greeter() if sys.platform == "win32" or os.name == "posix" or platform.system() else Greeter()  # noqa: RUF034
