from typing import Optional, Dict, Any

from app.core.base_exception import BaseException


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
            error_group="discovery",  # 对所有 DiscoveryException 固定为 "discovery"
            error_name=error_name,
            error_msg=error_msg,
            input_params=input_params,
        )


class DiscoveryError:
    """
    定义发现相关错误类型常量的类。

    可通过点号访问的方式引用错误类型，例如: DiscoveryError.DISCOVERY_FAIL
    """

    DISCOVERY_FAIL = "discovery_fail"
    DATABASE_ERROR = "database_error"
    ENHANCED_DISCOVERY_FAIL = "enhanced_discovery_fail"