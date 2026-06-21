"""
ATR 管理功能 IP 访问控制中间件

实现对 ATR 管理功能的源 IP 限制，只允许配置的 IP 地址访问相关端点。
"""

import ipaddress
from typing import List, Union
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import get_settings


class ATRManagementIPFilterMiddleware(BaseHTTPMiddleware):
    """ATR 管理功能 IP 过滤中间件"""

    def __init__(self, app, atr_mgmt_paths: List[str] = None):
        super().__init__(app)
        self.settings = get_settings()
        # 默认的 ATR 管理路径前缀
        self.atr_mgmt_paths = atr_mgmt_paths or ["/acps-atr-v1/mgmt"]

    def _is_atr_management_path(self, path: str) -> bool:
        """检查是否为 ATR 管理路径"""
        return any(path.startswith(mgmt_path) for mgmt_path in self.atr_mgmt_paths)

    def _parse_ip_list(self, ip_list: List[str]) -> List[
        Union[
            ipaddress.IPv4Address,
            ipaddress.IPv6Address,
            ipaddress.IPv4Network,
            ipaddress.IPv6Network,
        ]
    ]:
        """解析 IP 地址和网段列表"""
        parsed_ips = []
        for ip_str in ip_list:
            try:
                # 尝试解析为单个 IP 地址
                if "/" not in ip_str:
                    parsed_ips.append(ipaddress.ip_address(ip_str))
                else:
                    # 解析为网段
                    parsed_ips.append(ipaddress.ip_network(ip_str, strict=False))
            except ValueError as e:
                print(
                    f"Invalid IP address or network in ATR_MGMT_ALLOW_IP_LIST: {ip_str}, error: {e}"
                )
                continue
        return parsed_ips

    def _is_ip_allowed(
        self,
        client_ip: str,
        allowed_ips: List[
            Union[
                ipaddress.IPv4Address,
                ipaddress.IPv6Address,
                ipaddress.IPv4Network,
                ipaddress.IPv6Network,
            ]
        ],
    ) -> bool:
        """检查客户端 IP 是否在允许列表中"""
        try:
            client_ip_obj = ipaddress.ip_address(client_ip)

            for allowed_ip in allowed_ips:
                if isinstance(
                    allowed_ip, (ipaddress.IPv4Address, ipaddress.IPv6Address)
                ):
                    # 单个 IP 地址匹配
                    if client_ip_obj == allowed_ip:
                        return True
                elif isinstance(
                    allowed_ip, (ipaddress.IPv4Network, ipaddress.IPv6Network)
                ):
                    # 网段匹配
                    if client_ip_obj in allowed_ip:
                        return True

            return False
        except ValueError:
            # 无法解析客户端 IP，拒绝访问
            return False

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端真实 IP 地址"""
        # 优先检查代理头
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # X-Forwarded-For 可能包含多个 IP，取第一个
            return forwarded_for.split(",")[0].strip()

        # 检查其他代理头
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        # 使用直接连接的 IP
        client_host = request.client.host if request.client else "unknown"

        # 特殊处理测试客户端的情况
        if client_host == "testclient":
            # TestClient 情况下，假设为本地测试，使用 127.0.0.1
            return "127.0.0.1"

        return client_host

    async def dispatch(self, request: Request, call_next) -> Response:
        """中间件处理函数"""
        # 检查是否为 ATR 管理路径
        if not self._is_atr_management_path(request.url.path):
            # 非 ATR 管理路径，直接放行
            response = await call_next(request)
            return response

        # 获取允许的 IP 列表
        allowed_ip_list = self.settings.atr_mgmt_allow_ip_list_parsed
        if not allowed_ip_list:
            # 如果没有配置允许的 IP 列表，拒绝所有访问
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ATR management access is not configured",
            )

        # 解析允许的 IP 列表
        parsed_allowed_ips = self._parse_ip_list(allowed_ip_list)
        if not parsed_allowed_ips:
            # 如果无法解析任何有效的 IP，拒绝访问
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ATR management access configuration error",
            )

        # 获取客户端 IP
        client_ip = self._get_client_ip(request)

        # 检查客户端 IP 是否被允许
        if not self._is_ip_allowed(client_ip, parsed_allowed_ips):
            # 记录未授权访问尝试
            print(
                f"Unauthorized ATR management access attempt from IP: {client_ip}, path: {request.url.path}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: IP {client_ip} is not authorized for ATR management operations",
            )

        # IP 验证通过，继续处理请求
        response = await call_next(request)
        return response
