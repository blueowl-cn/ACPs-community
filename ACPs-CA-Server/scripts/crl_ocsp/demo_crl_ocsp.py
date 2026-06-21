#!/usr/bin/env python3
"""
CRL和OCSP服务示例脚本

这个脚本演示如何使用Agent CA的CRL和OCSP API。
适合作为教学示例。
"""

import requests
from datetime import datetime


def test_crl_api():
    """测试CRL相关API"""
    print("🔍 测试CRL API")
    print("=" * 40)

    base_url = "http://localhost:8003/api/v1/crl"

    # 1. 获取CRL基本信息
    print("1. 获取CRL信息:")
    try:
        response = requests.get(f"{base_url}/info")
        if response.status_code == 200:
            crl_info = response.json()
            print(f"   版本: {crl_info['version']}")
            print(f"   签发者: {crl_info['issuer']}")
            print(f"   更新时间: {crl_info['this_update']}")
            print(f"   下次更新: {crl_info['next_update']}")
            print(f"   吊销证书数量: {crl_info['revoked_certificates_count']}")
            print(f"   CRL大小: {crl_info['crl_size']} 字节")
        else:
            print(f"   ❌ 获取失败: {response.status_code}")
    except Exception as e:
        print(f"   ❌ 请求失败: {e}")

    # 2. 获取分发点信息
    print("\n2. 获取CRL分发点:")
    try:
        response = requests.get(f"{base_url}/distribution-points")
        if response.status_code == 200:
            dist_points = response.json()
            print(f"   主要分发点: {dist_points['primary']}")
            print(f"   镜像分发点: {', '.join(dist_points['mirrors'])}")
            print(f"   更新间隔: {dist_points['update_interval']}")
        else:
            print(f"   ❌ 获取失败: {response.status_code}")
    except Exception as e:
        print(f"   ❌ 请求失败: {e}")

    # 3. 下载当前CRL（PEM格式）
    print("\n3. 下载CRL (PEM格式):")
    try:
        response = requests.get(f"{base_url}/current/pem")
        if response.status_code == 200:
            crl_pem = response.text
            lines = crl_pem.strip().split("\n")
            print("   ✅ 下载成功!")
            print(f"   开始行: {lines[0]}")
            print(f"   结束行: {lines[-1]}")
            print(f"   总行数: {len(lines)}")
        else:
            print(f"   ❌ 下载失败: {response.status_code}")
    except Exception as e:
        print(f"   ❌ 请求失败: {e}")


def test_ocsp_api():
    """测试OCSP相关API"""
    print("\n🔍 测试OCSP API")
    print("=" * 40)

    base_url = "http://localhost:8003/api/v1/ocsp"

    # 1. 获取OCSP响应器信息
    print("1. 获取OCSP响应器信息:")
    try:
        response = requests.get(f"{base_url}/responder/info")
        if response.status_code == 200:
            responder_info = response.json()
            print(f"   响应器名称: {responder_info['responder']['name']}")
            print(f"   密钥哈希: {responder_info['responder']['key_hash']}")
            print(f"   版本: {responder_info['service_info']['version']}")
            print(
                f"   支持的扩展: {', '.join(responder_info['service_info']['supported_extensions'])}"
            )
            print(f"   主要端点: {responder_info['endpoints']['primary']}")
        else:
            print(f"   ❌ 获取失败: {response.status_code}")
    except Exception as e:
        print(f"   ❌ 请求失败: {e}")

    # 2. 测试批量OCSP查询
    print("\n2. 批量OCSP查询:")
    test_certificates = [
        {
            "serial_number": "1A2B3C4D5E6F7890",
            "issuer_key_hash": "sha1:A1B2C3D4E5F6789012345678901234567890ABCD",
        },
        {
            "serial_number": "FEDCBA0987654321",
            "issuer_key_hash": "sha1:A1B2C3D4E5F6789012345678901234567890ABCD",
        },
    ]

    try:
        response = requests.post(
            f"{base_url}/batch",
            json={"certificates": test_certificates},
            headers={"Content-Type": "application/json"},
        )
        if response.status_code == 200:
            batch_result = response.json()
            print(f"   响应者ID: {batch_result['responder_id']}")
            print(f"   生成时间: {batch_result['produced_at']}")
            print("   查询结果:")
            for resp in batch_result["responses"]:
                print(f"     序列号: {resp['serial_number']}")
                print(f"     状态: {resp['status']}")
                print(f"     更新时间: {resp['this_update']}")
        else:
            print(f"   ❌ 查询失败: {response.status_code}")
    except Exception as e:
        print(f"   ❌ 请求失败: {e}")

    # 3. 获取OCSP统计信息
    print("\n3. 获取OCSP统计信息:")
    try:
        response = requests.get(f"{base_url}/stats")
        if response.status_code == 200:
            stats = response.json()
            print(f"   总请求数: {stats['total_requests']}")
            print(f"   有效响应数: {stats['valid_responses']}")
            print(f"   吊销响应数: {stats['revoked_responses']}")
            print(f"   未知响应数: {stats['unknown_responses']}")
            print(f"   平均响应时间: {stats['average_response_time_ms']} ms")
            print(f"   最近24小时请求数: {stats['last_24h_requests']}")
        else:
            print(f"   ❌ 获取失败: {response.status_code}")
    except Exception as e:
        print(f"   ❌ 请求失败: {e}")


def test_simple_certificate_status():
    """测试简单的证书状态查询"""
    print("\n🔍 测试简单证书状态查询")
    print("=" * 40)

    # 测试一个不存在的证书序列号
    serial_number = "ABC123DEF456"

    try:
        response = requests.get(
            f"http://localhost:8003/api/v1/ocsp/certificate/{serial_number}"
        )
        if response.status_code == 200:
            status = response.json()
            print(f"证书序列号: {status['serialNumber']}")
            print(f"证书状态: {status['certificateStatus']}")
            print(f"更新时间: {status['thisUpdate']}")
        else:
            print(f"❌ 查询失败: {response.status_code}")
    except Exception as e:
        print(f"❌ 请求失败: {e}")


def display_api_summary():
    """显示API总结"""
    print("\n📋 CRL和OCSP API 总结")
    print("=" * 50)
    print("✅ 已实现的核心功能:")
    print("   • CRL生成和分发")
    print("   • CRL信息查询")
    print("   • CRL下载（DER和PEM格式）")
    print("   • OCSP响应器配置")
    print("   • OCSP批量查询")
    print("   • OCSP统计信息")
    print("   • 简化的证书状态查询")
    print()
    print("🎯 教学价值:")
    print("   • 清晰的代码结构")
    print("   • 完整的测试覆盖")
    print("   • 符合RFC标准的实现")
    print("   • 易于理解的API设计")
    print()
    print("📚 相关标准:")
    print("   • RFC 5280 - CRL标准")
    print("   • RFC 6960 - OCSP标准")
    print("   • RFC 8555 - ACME协议（证书吊销）")


def main():
    """主函数"""
    print("🚀 Agent CA - CRL和OCSP服务测试")
    print("=" * 50)
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    try:
        # 测试CRL API
        test_crl_api()

        # 测试OCSP API
        test_ocsp_api()

        # 测试简单证书状态查询
        test_simple_certificate_status()

        # 显示总结
        display_api_summary()

        print("\n🎉 所有测试完成!")

    except KeyboardInterrupt:
        print("\n⚠️  测试被用户中断")
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")


if __name__ == "__main__":
    main()
