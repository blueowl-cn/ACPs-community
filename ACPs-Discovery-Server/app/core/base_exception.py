from typing import Optional, Dict, Any


class BaseException(Exception):
    """
    应用自定义异常类，用于表示应用级别的错误。

    属性:
        status_code: 要返回的 HTTP 状态码
        error_group: 发生错误的功能分组
        error_name: 具体的错误名称
        error_msg: 便于展示的错误描述
        input_params: 导致错误的输入参数
    """

    def __init__(
        self,
        status_code: int = 400,
        error_group: str = "base",
        error_name: str = "unknown_error",
        error_msg: str = "An error occurred",
        input_params: Optional[Dict[str, Any]] = None,
    ):
        self.status_code = status_code
        self.error_group = error_group
        self.error_name = error_name
        self.error_msg = error_msg
        self.input_params = input_params or {}
        super().__init__(self.error_msg)

    def to_dict(self) -> Dict[str, Any]:
        """将异常转换为字典以用于 JSON 响应。"""
        return {
            "status_code": self.status_code,
            "error_group": self.error_group,
            "error_name": self.error_name,
            "error_msg": self.error_msg,
            "input_params": self.input_params,
        }
