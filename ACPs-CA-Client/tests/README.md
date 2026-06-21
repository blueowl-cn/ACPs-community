# CA Client 测试

本目录包含三个层级的测试，覆盖粒度由细到粗：

## 目录结构

```
tests/
├── README.md           # 本文件
├── conftest.py         # 全局共享 fixtures
├── unit/               # 单元测试
│   ├── conftest.py
│   ├── test_keys.py    # 密钥生成、保存、加载
│   ├── test_config.py  # 配置文件解析
│   ├── test_acme.py    # ACME 协议工具函数与 JWS 签名
│   └── test_utils.py   # 工具函数
├── integration/        # 集成测试（Click CliRunner）
│   ├── conftest.py
│   └── test_cli.py     # CLI 子命令集成测试
└── e2e/                # 端到端测试（需要 ca-server Mock 模式）
    ├── conftest.py
    ├── e2e.conf         # E2E 专用配置（Mock 开关已开启）
    └── test_e2e.py     # 完整证书生命周期场景
```

## 三类测试的区别

| 维度        | 单元测试 (unit)     | 集成测试 (integration)     | 端到端测试 (e2e)                    |
| ----------- | ------------------- | -------------------------- | ----------------------------------- |
| 测试范围    | 单个函数 / 类       | CLI 命令的输入输出         | 完整证书生命周期                    |
| 外部依赖    | 无（全部 mock）     | 无（mock ACME 交互）       | 需要运行中的 ca-server（Mock 模式） |
| 运行速度    | 毫秒级              | 秒级                       | 秒~十秒级                           |
| pytest 标记 | `@pytest.mark.unit` | `@pytest.mark.integration` | `@pytest.mark.e2e`                  |

## 运行方式

```bash
# 运行所有测试
pytest

# 仅运行单元测试
pytest -m unit

# 仅运行集成测试
pytest -m integration

# 仅运行 E2E 测试（确保 ca-server Mock 模式已启动）
pytest -m e2e

# 带覆盖率
pytest --cov=acps_ca_client --cov-report=term-missing
```

## E2E 测试前置条件

E2E 测试需要 ca-server 以 Mock 模式运行：

```bash
# 启动 ca-server（在 ca-server 目录下）
AGENT_REGISTRY_MOCK=true HTTP01_VALIDATION_MOCK=true python main.py
```

ca-client 侧的 `CHALLENGE_DEPLOY_MOCK` 由 E2E 配置文件 `e2e/e2e.conf` 自动启用。
