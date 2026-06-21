class ChallengeNotFoundError(Exception):
    """当未找到挑战时引发。"""

    pass


class ChallengeStorageError(Exception):
    """当读取或写入挑战时发生错误时引发。"""

    pass
