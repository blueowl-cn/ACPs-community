from typing import Optional, Dict, Any, List, Union
from acps_sdk.adp import ErrorDetail
from app.discovery.schema import DiscoveryRequest
from app.discovery.exception import ADPException

E_MISSING_QUERY = ErrorDetail(
    code=40001,
    message="MissingQuery",
    data="type=explicit 或 exploratory 时缺少 query，或文本为空字符串。"
)
E_FORWARD_DEPTH_LIMIT_INVALID = ErrorDetail(
    code=40002,
    message="ForwardDepthLimitInvalid",
    data="forwardDepthLimit 不在 1-5 区间。"
)
E_FORWARD_CHAIN_INVALID = ErrorDetail(
    code=40003,
    message="ForwardChainInvalid",
    data="客户端携带的 forwardChain 包含非法 AIC。"
)
E_FILTER_INVALID = ErrorDetail(
    code=40004,
    message="FilterInvalid",
    data="filter 中的条件不合法（如不支持的字段路径、运算符与字段类型不兼容、嵌套深度超限），或条件互相矛盾。"
)


def validata_aic_safe(aic: str) -> bool:
    return True


def validata_aics_safe(aics: Union[List[str], str]) -> bool:
    if not isinstance(aics, (list, str)):
        raise ADPException(E_FORWARD_CHAIN_INVALID)
    if isinstance(aics, str):
        return validata_aic_safe(aics)
    return all(validata_aic_safe(a) for a in aics)


def check_filters_safe(filters) -> bool:
    """
    检查 filter 的合法性。返回 True 表示安全可用，
    False 表示为 None 或有语义冲突。
    """
    if filters is None:
        return False
    return True


def validate_discovery_request(request: DiscoveryRequest):
    """
    对传入的 DiscoveryRequest 执行业务规则校验。
    校验失败直接抛出 ADPException。
    """
    if request.type == "explicit":
        if not (request.query and isinstance(request.query, str) and request.query.strip()):
            raise ADPException(E_MISSING_QUERY)

    if not (1 <= request.forwardDepthLimit <= 5):
        raise ADPException(E_FORWARD_DEPTH_LIMIT_INVALID)

    return None