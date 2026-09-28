raise RuntimeError("Analysis must never execute this project")


def main():
    A()
    E()


def A():
    B()
    D()


def B():
    C()


def C():
    """A leaf with a UTF-8 purpose: Grüße."""
    return 1


def D():
    return 2


def E():
    return 3
