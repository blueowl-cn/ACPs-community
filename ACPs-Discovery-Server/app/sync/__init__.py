"""
DRC (Discovery Registry Coordination) 同步模块。

此模块实现使用 DRC 协议从注册中心服务器同步数据的客户端逻辑。
"""

from .client import DRCClient
from .model import Envelope, DRCState
from .api import router

__all__ = ["DRCClient", "Envelope", "DRCState", "router"]
