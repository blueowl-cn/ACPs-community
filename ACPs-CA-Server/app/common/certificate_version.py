"""证书版本号生成

提供按 AIC 维度生成自增版本号的工具函数。
"""

from typing import Optional

from sqlmodel import Session, select, func

from .certificate_model import Certificate


def get_next_certificate_version(db: Session, aic: str) -> int:
    """获取指定 AIC 的下一个证书版本号。

    版本号按 AIC 维度自增：若该 AIC 尚无证书记录，则返回 1；否则返回 (max(version) + 1)。

    Args:
        db: 数据库会话
        aic: Agent Identify Code

    Returns:
        int: 下一个版本号（从 1 开始）
    """
    if not aic:
        return 1

    statement = select(func.max(Certificate.version)).where(Certificate.aic == aic)
    max_version: Optional[int] = db.exec(statement).one()
    return (max_version or 0) + 1
