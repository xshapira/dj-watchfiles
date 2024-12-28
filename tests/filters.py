from watchfiles import Change


def only_added(change: Change, path: str) -> bool:
    return change == Change.added
