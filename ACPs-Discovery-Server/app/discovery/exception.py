from typing import Optional, Dict, Any

from app.core.base_exception import BaseException
from acps_sdk.adp import ErrorDetail  # 替代原来的 ErrorData


class DiscoveryException(BaseException):
    """
    与发现（discovery）相关的自定义异常类。
    继承自 BaseException，但将 error_group 固定为 "discovery"。
    """
    def __init__(
        self,
        status_code: int = 400,
        error_name: str = "discovery_error",
        error_msg: str = "An error occurred with discovery operation",
        input_params: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            status_code=status_code,
            error_group="discovery",
            error_name=error_name,
            error_msg=error_msg,
            input_params=input_params,
        )


class DiscoveryError:
    DISCOVERY_FAIL = "discovery_fail"
    DATABASE_ERROR = "database_error"
    ENHANCED_DISCOVERY_FAIL = "enhanced_discovery_fail"


class ADPException(Exception):
    """
    自定义的业务逻辑异常。
    封装结构化的 ErrorDetail 对象，供 API 层转换为标准错误响应。
    """
    def __init__(self, error_data: ErrorDetail):
        self.error_data = error_data
        super().__init__(f"[{self.error_data.code}] {self.error_data.message}")