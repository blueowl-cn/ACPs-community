"""
OCSP (Online Certificate Status Protocol) 业务服务
"""

import hashlib
from datetime import timedelta
from typing import Optional, List, Tuple, Dict, Any

from sqlmodel import Session, select, func
from cryptography import x509
from cryptography.x509.ocsp import OCSPResponseBuilder
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import Encoding

from .ocsp_model import (
    OCSPRequest,
    OCSPResponse,
    OCSPResponder,
    OCSPResponseStatus,
)
from .certificate_model import Certificate, CertificateStatus, RevocationReason
from .time_utils import beijing_now, format_datetime
from ..core.ca_manager import get_ca_manager


class OCSPService:
    """OCSP服务"""

    def __init__(self, db: Session):
        self.db = db

    def get_active_responder(self) -> Optional[OCSPResponder]:
        """获取活跃的OCSP响应器"""
        statement = select(OCSPResponder).where(OCSPResponder.is_active.is_(True))
        return self.db.exec(statement).first()

    def process_ocsp_request(
        self, request_der: bytes, client_ip: Optional[str] = None
    ) -> Tuple[bytes, int]:
        """处理OCSP请求"""
        start_time = beijing_now()

        try:
            # 解析OCSP请求
            ocsp_request = x509.ocsp.load_der_ocsp_request(request_der)

            # 生成请求ID
            request_id = hashlib.sha256(request_der).hexdigest()

            # 获取证书序列号和签发者信息
            single_request = ocsp_request.tbs_request.request_list[0]
            cert_id = single_request.req_cert

            serial_number = str(cert_id.serial_number)
            issuer_key_hash = cert_id.issuer_key_hash.hex()
            issuer_name_hash = cert_id.issuer_name_hash.hex()
            hash_algorithm = cert_id.hash_algorithm.name

            # 记录请求
            request_record = OCSPRequest(
                request_id=request_id,
                certificate_serial=serial_number,
                issuer_key_hash=issuer_key_hash,
                issuer_name_hash=issuer_name_hash,
                hash_algorithm=hash_algorithm,
                client_ip=client_ip,
                request_der=request_der,
            )
            self.db.add(request_record)

            # 查询证书状态
            certificate = self.db.exec(
                select(Certificate).where(Certificate.serial_number == serial_number)
            ).first()

            if not certificate:
                cert_status = OCSPResponseStatus.UNKNOWN
                revocation_time = None
                revocation_reason = None
            elif certificate.status == CertificateStatus.REVOKED:
                cert_status = OCSPResponseStatus.REVOKED
                revocation_time = certificate.revoked_at
                revocation_reason = certificate.revocation_reason
            elif certificate.status == CertificateStatus.VALID:
                cert_status = OCSPResponseStatus.GOOD
                revocation_time = None
                revocation_reason = None
            else:
                cert_status = OCSPResponseStatus.UNKNOWN
                revocation_time = None
                revocation_reason = None

            # 生成OCSP响应
            ca_manager = get_ca_manager()
            responder = self.get_active_responder()

            if not responder:
                raise Exception("No active OCSP responder found")

            # 构建OCSP响应
            now = beijing_now()
            next_update = now + timedelta(hours=24)

            response_builder = OCSPResponseBuilder()

            if cert_status == OCSPResponseStatus.GOOD:
                response_builder = response_builder.add_response(
                    cert=(
                        x509.load_pem_x509_certificate(
                            certificate.certificate_pem.encode()
                        )
                        if certificate
                        else None
                    ),
                    issuer=ca_manager.ca_cert,
                    algorithm=hashes.SHA1(),
                    cert_status=x509.ocsp.OCSPCertStatus.GOOD,
                    this_update=now,
                    next_update=next_update,
                )
            elif cert_status == OCSPResponseStatus.REVOKED:
                response_builder = response_builder.add_response(
                    cert=x509.load_pem_x509_certificate(
                        certificate.certificate_pem.encode()
                    ),
                    issuer=ca_manager.ca_cert,
                    algorithm=hashes.SHA1(),
                    cert_status=x509.ocsp.OCSPCertStatus.REVOKED,
                    this_update=now,
                    next_update=next_update,
                    revocation_time=revocation_time,
                    revocation_reason=(
                        x509.ReasonFlags.key_compromise
                        if revocation_reason == RevocationReason.KEY_COMPROMISE
                        else x509.ReasonFlags.unspecified
                    ),
                )
            else:
                response_builder = response_builder.add_response(
                    cert=None,
                    issuer=ca_manager.ca_cert,
                    algorithm=hashes.SHA1(),
                    cert_status=x509.ocsp.OCSPCertStatus.UNKNOWN,
                    this_update=now,
                    next_update=next_update,
                )

            # 加载响应器私钥
            responder_private_key = serialization.load_pem_private_key(
                responder.private_key_pem.encode(), password=None
            )

            # 签名响应
            ocsp_response = response_builder.sign(
                private_key=responder_private_key, algorithm=hashes.SHA256()
            )

            # 转换为DER格式
            response_der = ocsp_response.public_bytes(Encoding.DER)

            # 计算处理时间
            processing_time = int((beijing_now() - start_time).total_seconds() * 1000)

            # 记录响应
            response_record = OCSPResponse(
                request_id=request_record.id,
                certificate_serial=serial_number,
                cert_status=cert_status,
                this_update=now,
                next_update=next_update,
                revocation_time=revocation_time,
                revocation_reason=revocation_reason,
                responder_id=responder.name,
                responder_key_hash=hashlib.sha1(
                    ca_manager.ca_cert.public_key().public_bytes(
                        encoding=serialization.Encoding.DER,
                        format=serialization.PublicFormat.SubjectPublicKeyInfo,
                    )
                ).hexdigest(),
                response_der=response_der,
                response_size=len(response_der),
                signature_algorithm="SHA256withRSA",
                processing_time_ms=processing_time,
            )
            self.db.add(response_record)

            self.db.commit()

            return response_der, processing_time

        except Exception as e:
            self.db.rollback()
            raise Exception(f"OCSP processing failed: {str(e)}")

    def batch_check_certificates(
        self, certificates: List[Dict[str, str]]
    ) -> List[Dict[str, Any]]:
        """批量检查证书状态"""
        responses = []

        for cert_info in certificates:
            serial_number = cert_info.get("serial_number")
            if not serial_number:
                continue

            certificate = self.db.exec(
                select(Certificate).where(Certificate.serial_number == serial_number)
            ).first()

            if not certificate:
                status = OCSPResponseStatus.UNKNOWN
                this_update = beijing_now()
                next_update = this_update + timedelta(hours=24)
                revocation_time = None
                revocation_reason = None
            elif certificate.status == CertificateStatus.REVOKED:
                status = OCSPResponseStatus.REVOKED
                this_update = beijing_now()
                next_update = this_update + timedelta(hours=24)
                revocation_time = certificate.revoked_at
                revocation_reason = (
                    certificate.revocation_reason.value
                    if certificate.revocation_reason
                    else None
                )
            elif certificate.status == CertificateStatus.VALID:
                status = OCSPResponseStatus.GOOD
                this_update = beijing_now()
                next_update = this_update + timedelta(hours=24)
                revocation_time = None
                revocation_reason = None
            elif certificate.status == CertificateStatus.EXPIRED:
                # Use the new EXPIRED status for expired certificates
                status = OCSPResponseStatus.EXPIRED
                this_update = beijing_now()
                next_update = this_update + timedelta(hours=24)
                revocation_time = certificate.expires_at
                revocation_reason = None
            else:
                status = OCSPResponseStatus.UNKNOWN
                this_update = beijing_now()
                next_update = this_update + timedelta(hours=24)
                revocation_time = None
                revocation_reason = None

            response = {
                "serial_number": serial_number,
                "status": status if isinstance(status, str) else status.value,
                "this_update": this_update,
                "next_update": next_update,
            }

            if revocation_time:
                response["revocation_time"] = revocation_time

            if revocation_reason:
                response["revocation_reason"] = revocation_reason

            responses.append(response)

        return responses

    def get_responder_info(self) -> Dict[str, Any]:
        """获取OCSP响应器信息"""
        responder = self.get_active_responder()
        if not responder:
            raise Exception("No active OCSP responder found")

        ca_manager = get_ca_manager()

        return {
            "responder": {
                "name": responder.name,
                "key_hash": hashlib.sha1(
                    ca_manager.ca_cert.public_key().public_bytes(
                        encoding=serialization.Encoding.DER,
                        format=serialization.PublicFormat.SubjectPublicKeyInfo,
                    )
                ).hexdigest(),
                "certificate": responder.certificate_pem,
            },
            "service_info": {
                "version": "1.0",
                "supported_extensions": responder.supported_extensions,
                "max_request_size": responder.max_request_size,
                "response_timeout": f"PT{responder.response_timeout_seconds}S",
            },
            "endpoints": responder.endpoints,
        }

    def create_responder(
        self,
        name: str,
        certificate_pem: str,
        private_key_pem: str,
        endpoints: Dict[str, Any],
        max_request_size: int = 1048576,
        response_timeout_seconds: int = 30,
        supported_extensions: Optional[List[str]] = None,
    ) -> OCSPResponder:
        """创建OCSP响应器"""
        if supported_extensions is None:
            supported_extensions = ["nonce"]

        # 验证证书和私钥
        try:
            cert = x509.load_pem_x509_certificate(certificate_pem.encode())
            _ = serialization.load_pem_private_key(
                private_key_pem.encode(), password=None
            )
            # 验证私钥和证书匹配
            # 这里可以添加更多验证逻辑
        except Exception as e:
            raise ValueError(f"Invalid certificate or private key: {str(e)}")

        # 停用现有的响应器
        existing_responders = self.db.exec(
            select(OCSPResponder).where(OCSPResponder.is_active.is_(True))
        ).all()
        for responder in existing_responders:
            responder.is_active = False
            self.db.add(responder)

        # 创建新响应器
        responder = OCSPResponder(
            name=name,
            certificate_pem=certificate_pem,
            private_key_pem=private_key_pem,
            certificate_serial=format(cert.serial_number, "x"),
            is_active=True,
            endpoints=endpoints,
            max_request_size=max_request_size,
            response_timeout_seconds=response_timeout_seconds,
            supported_extensions=supported_extensions,
        )

        self.db.add(responder)
        self.db.commit()
        self.db.refresh(responder)

        return responder

    def get_ocsp_statistics(self) -> Dict[str, Any]:
        """获取OCSP统计信息"""
        # 总请求数
        total_requests = self.db.exec(select(func.count(OCSPRequest.id))).one()

        # 各种状态的响应数
        valid_responses = self.db.exec(
            select(func.count(OCSPResponse.id)).where(
                OCSPResponse.cert_status == OCSPResponseStatus.GOOD
            )
        ).one()

        revoked_responses = self.db.exec(
            select(func.count(OCSPResponse.id)).where(
                OCSPResponse.cert_status == OCSPResponseStatus.REVOKED
            )
        ).one()

        unknown_responses = self.db.exec(
            select(func.count(OCSPResponse.id)).where(
                OCSPResponse.cert_status == OCSPResponseStatus.UNKNOWN
            )
        ).one()

        # 平均响应时间
        avg_response_time = (
            self.db.exec(select(func.avg(OCSPResponse.processing_time_ms))).one() or 0
        )

        # 最近24小时的请求数
        since_24h = beijing_now() - timedelta(hours=24)
        last_24h_requests = self.db.exec(
            select(func.count(OCSPRequest.id)).where(
                OCSPRequest.created_at >= since_24h
            )
        ).one()

        return {
            "total_requests": total_requests,
            "good_responses": valid_responses,  # Add alias for backward compatibility
            "valid_responses": valid_responses,
            "revoked_responses": revoked_responses,
            "unknown_responses": unknown_responses,
            "average_response_time_ms": float(avg_response_time),
            "last_24h_requests": last_24h_requests,
        }

    def get_certificate_status(self, serial_number: str) -> Dict[str, Any]:
        """获取证书状态（简化接口）"""
        try:
            # 查询证书
            statement = select(Certificate).where(
                Certificate.serial_number == serial_number
            )
            certificate = self.db.exec(statement).first()

            current_time = beijing_now()

            # 构建响应
            response_data = {
                "serial_number": serial_number,  # Use snake_case for consistency
                "serialNumber": serial_number,  # Keep camelCase for backward compatibility
                "thisUpdate": format_datetime(current_time),
                "nextUpdate": format_datetime(current_time + timedelta(hours=24)),
            }

            if not certificate:
                # 证书不存在，返回UNKNOWN状态
                response_data["certificateStatus"] = "unknown"
                return response_data

            # 根据证书状态设置响应
            if certificate.status == CertificateStatus.REVOKED:
                response_data.update(
                    {
                        "certificateStatus": "revoked",
                        "revocationTime": (
                            format_datetime(certificate.revoked_at)
                            if certificate.revoked_at
                            else None
                        ),
                        "revocationReason": (
                            certificate.revocation_reason.value
                            if certificate.revocation_reason
                            else None
                        ),
                    }
                )
            elif certificate.status == CertificateStatus.VALID:
                # 检查是否过期 - 先确保时区兼容性
                if certificate.expires_at:
                    # 如果expires_at是naive datetime，假设它是UTC
                    expires_at = certificate.expires_at
                    if expires_at.tzinfo is None:
                        from datetime import timezone

                        expires_at = expires_at.replace(tzinfo=timezone.utc)

                    current_time_aware = current_time
                    if current_time_aware.tzinfo is None:
                        from datetime import timezone

                        current_time_aware = current_time_aware.replace(
                            tzinfo=timezone.utc
                        )

                    if expires_at < current_time_aware:
                        response_data["certificateStatus"] = "expired"
                    else:
                        response_data["certificateStatus"] = "good"
                else:
                    response_data["certificateStatus"] = "good"
            elif certificate.status == CertificateStatus.EXPIRED:
                response_data["certificateStatus"] = "expired"
            else:
                response_data["certificateStatus"] = "unknown"

            return response_data

        except Exception as e:
            # 记录错误，返回unknown状态而不是None
            print(f"Error getting certificate status: {e}")
            current_time = beijing_now()
            return {
                "serial_number": serial_number,
                "serialNumber": serial_number,
                "certificateStatus": "unknown",
                "thisUpdate": format_datetime(current_time),
                "nextUpdate": format_datetime(current_time + timedelta(hours=24)),
            }

    def batch_certificate_status(
        self, certificates: List[Dict[str, str]]
    ) -> List[Dict[str, Any]]:
        """批量获取证书状态"""
        results = []
        for cert_req in certificates:
            serial_number = cert_req.get("serial_number", "")
            if not serial_number:
                continue

            status = self.get_certificate_status(serial_number)
            results.append(status)

        return results
