from typing import Optional, Dict, Any

from app.core.base_exception import BaseException


class AcmeException(BaseException):
    """
    Custom exception class for acme-related errors

    Inherits from BaseException but fixes error_group to 'acme'
    """

    def __init__(
        self,
        status_code: int = 400,
        error_name: str = "acme_error",
        error_msg: str = "An error occurred with acme operation",
        input_params: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            status_code=status_code,
            error_group="acme",  # Fixed to 'acme' for all acmeExceptions
            error_name=error_name,
            error_msg=error_msg,
            input_params=input_params,
        )


class AcmeError:
    """
    Class containing all acme error types as constants.
    This allows referencing error types using dot notation (AcmeError.CERTIFICATE_NOT_FOUND)
    """

    # 证书相关错误
    CERTIFICATE_NOT_FOUND = "CERTIFICATE_NOT_FOUND"
    CERTIFICATE_EXISTS = "CERTIFICATE_EXISTS"
    CERTIFICATE_EXPIRED = "CERTIFICATE_EXPIRED"
    CERTIFICATE_REVOKED = "CERTIFICATE_REVOKED"
    INVALID_CERTIFICATE_FORMAT = "INVALID_CERTIFICATE_FORMAT"

    # ACME 协议错误
    BAD_NONCE = "BAD_NONCE"
    BAD_SIGNATURE = "BAD_SIGNATURE"
    MALFORMED_REQUEST = "MALFORMED_REQUEST"
    MALFORMED = "MALFORMED"  # JWS验证器使用
    ACCOUNT_NOT_FOUND = "ACCOUNT_NOT_FOUND"
    ACCOUNT_EXISTS = "ACCOUNT_EXISTS"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    ORDER_NOT_READY = "ORDER_NOT_READY"
    AUTHORIZATION_NOT_FOUND = "AUTHORIZATION_NOT_FOUND"
    CHALLENGE_NOT_FOUND = "CHALLENGE_NOT_FOUND"
    INVALID_CONTACT = "INVALID_CONTACT"
    UNSUPPORTED_CONTACT = "UNSUPPORTED_CONTACT"
    EXTERNAL_ACCOUNT_REQUIRED = "EXTERNAL_ACCOUNT_REQUIRED"
    UNSUPPORTED_ALGORITHM = "UNSUPPORTED_ALGORITHM"  # JWS验证器使用
    UNSUPPORTED_IDENTIFIER = "UNSUPPORTED_IDENTIFIER"  # 标识符验证
    INVALID_IDENTIFIER = "INVALID_IDENTIFIER"  # 标识符验证

    # 验证相关错误
    UNAUTHORIZED = "UNAUTHORIZED"
    DNS_ERROR = "DNS_ERROR"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    TLS_ERROR = "TLS_ERROR"
    INCORRECT_RESPONSE = "INCORRECT_RESPONSE"
    CAA_ERROR = "CAA_ERROR"

    # 服务器错误
    SERVER_INTERNAL = "SERVER_INTERNAL"
    USER_ACTION_REQUIRED = "USER_ACTION_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
