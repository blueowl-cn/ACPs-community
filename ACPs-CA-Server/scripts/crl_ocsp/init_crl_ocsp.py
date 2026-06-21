#!/usr/bin/env python3
"""
初始化CRL和OCSP服务的脚本

这个脚本创建基本的CRL和OCSP响应器配置，用于演示和教学目的。
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from sqlmodel import Session  # noqa: E402
from app.core.db_session import engine  # noqa: E402
from app.common import CRLService, OCSPService  # noqa: E402
from app.common.ocsp_model import OCSPResponder  # noqa: E402
from app.core.ca_manager import get_ca_manager  # noqa: E402

# 添加项目根目录到Python路径
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


def init_crl_service():
    """初始化CRL服务"""
    print("正在初始化CRL服务...")

    with Session(engine) as db:
        crl_service = CRLService(db)

        # 检查是否已有CRL
        current_crl = crl_service.get_current_crl()
        if current_crl:
            print(f"CRL已存在，版本: {current_crl.version}")
            return current_crl

        # 创建初始CRL
        try:
            new_crl = crl_service.generate_new_crl(
                issuer="CN=Agent CA Intermediate, O=Agent CA Services, C=CN",
                next_update_hours=24,
            )
            print(f"创建CRL成功，版本: {new_crl.version}")
            print(f"CRL大小: {new_crl.crl_size} 字节")
            print(f"吊销证书数量: {new_crl.revoked_certificates_count}")
            return new_crl
        except Exception as e:
            print(f"创建CRL失败: {e}")
            return None


def init_ocsp_responder():
    """初始化OCSP响应器"""
    print("正在初始化OCSP响应器...")

    with Session(engine) as db:
        ocsp_service = OCSPService(db)

        # 检查是否已有活跃的响应器
        try:
            responder = ocsp_service.get_active_responder()
            if responder:
                print(f"OCSP响应器已存在: {responder.name}")
                return responder
        except Exception:
            pass

        # 获取CA管理器来创建响应器证书
        try:
            ca_manager = get_ca_manager()

            # 使用CA证书作为OCSP响应器证书（简化版本）
            ca_cert_pem = ca_manager.get_ca_certificate_pem()
            ca_key_pem = ca_manager.get_ca_private_key_pem()

            # 创建OCSP响应器
            responder = OCSPResponder(
                name="Agent CA OCSP Responder",
                certificate_pem=ca_cert_pem,
                private_key_pem=ca_key_pem,
                certificate_serial=f"{ca_manager.ca_cert.serial_number:X}",
                is_active=True,
                endpoints={
                    "primary": "https://ca.example.com/api/v1/ocsp",
                    "backup": "https://ca-backup.example.com/api/v1/ocsp",
                },
                max_request_size=1048576,
                response_timeout_seconds=30,
                supported_extensions=["nonce", "crlReferences"],
            )

            db.add(responder)
            db.commit()
            db.refresh(responder)

            print(f"创建OCSP响应器成功: {responder.name}")
            print(f"证书序列号: {responder.certificate_serial}")
            return responder

        except Exception as e:
            print(f"创建OCSP响应器失败: {e}")
            return None


def main():
    """主函数"""
    print("开始初始化CRL和OCSP服务...")
    print("=" * 50)

    # 初始化CRL
    crl = init_crl_service()
    print()

    # 初始化OCSP响应器
    responder = init_ocsp_responder()
    print()

    if crl and responder:
        print("✅ CRL和OCSP服务初始化成功！")
        print("\n可以测试的API端点:")
        print("- GET http://localhost:8003/api/v1/crl/info")
        print("- GET http://localhost:8003/api/v1/crl/current")
        print("- GET http://localhost:8003/api/v1/ocsp/responder/info")
        print("- POST http://localhost:8003/api/v1/ocsp/batch")
    else:
        print("❌ 初始化失败")


if __name__ == "__main__":
    main()
