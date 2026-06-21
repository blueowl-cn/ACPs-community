#!/usr/bin/env python3
"""
CRL和OCSP测试运行脚本

提供便捷的命令来运行不同类型的测试
"""

import subprocess
import argparse


def run_command(cmd, description):
    """运行命令并显示结果"""
    print(f"\n🚀 {description}")
    print("=" * 60)
    print(f"执行命令: {' '.join(cmd)}")
    print("-" * 60)

    result = subprocess.run(cmd, capture_output=False)

    if result.returncode == 0:
        print(f"✅ {description} - 成功")
    else:
        print(f"❌ {description} - 失败 (退出码: {result.returncode})")

    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="运行CRL和OCSP测试")
    parser.add_argument(
        "--type",
        choices=["all", "crl", "ocsp", "integration", "unit", "quick"],
        default="all",
        help="测试类型",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("--coverage", action="store_true", help="生成覆盖率报告")
    parser.add_argument("--parallel", "-p", action="store_true", help="并行运行测试")

    args = parser.parse_args()

    # 基础pytest命令
    base_cmd = ["python", "-m", "pytest"]

    if args.verbose:
        base_cmd.extend(["-v", "-s"])

    if args.coverage:
        base_cmd.extend(["--cov=app", "--cov-report=html", "--cov-report=term"])

    if args.parallel:
        base_cmd.extend(["-n", "auto"])

    # 根据测试类型确定测试文件和标记
    test_configs = {
        "all": {
            "description": "运行所有CRL和OCSP测试",
            "files": [
                "tests/test_crl.py",
                "tests/test_ocsp.py",
                "tests/test_crl_ocsp_integration.py",
            ],
            "markers": None,
        },
        "crl": {
            "description": "运行CRL相关测试",
            "files": ["tests/test_crl.py"],
            "markers": ["-m", "crl"],
        },
        "ocsp": {
            "description": "运行OCSP相关测试",
            "files": ["tests/test_ocsp.py"],
            "markers": ["-m", "ocsp"],
        },
        "integration": {
            "description": "运行集成测试",
            "files": ["tests/test_crl_ocsp_integration.py"],
            "markers": ["-m", "integration"],
        },
        "unit": {
            "description": "运行单元测试",
            "files": ["tests/test_crl.py", "tests/test_ocsp.py"],
            "markers": [
                "-m",
                "unit or (crl and not integration) or (ocsp and not integration)",
            ],
        },
        "quick": {
            "description": "运行快速测试（排除慢速测试）",
            "files": [
                "tests/test_crl.py",
                "tests/test_ocsp.py",
                "tests/test_crl_ocsp_integration.py",
            ],
            "markers": ["-m", "not slow"],
        },
    }

    config = test_configs[args.type]

    # 构建完整命令
    cmd = base_cmd.copy()

    if config["markers"]:
        cmd.extend(config["markers"])

    cmd.extend(config["files"])

    # 运行测试
    success = run_command(cmd, config["description"])

    if args.coverage and success:
        print("\n📊 覆盖率报告已生成:")
        print("   HTML报告: htmlcov/index.html")
        print("   命令行报告见上方输出")

    if not success:
        print("\n💡 测试失败提示:")
        print("   1. 确保服务器已停止，避免端口冲突")
        print("   2. 检查数据库连接是否正常")
        print("   3. 确保所有依赖已安装: pip install -r requirements.txt")
        print("   4. 运行单个测试文件排查问题: pytest tests/test_crl.py -v")

    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
