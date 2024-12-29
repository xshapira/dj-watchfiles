from watchfiles import Change


def only_added(change: Change, path: str) -> bool:
    return change == Change.added


def only_added_factory():
    """Factory function that returns the filter function"""

    def only_added(change: Change, path: str) -> bool:
        return change == Change.added

    return only_added
