# Agent CA ACME 客户端

这是一个基于 bash 的 ACME 客户端，遵循 ATR（Agent Trusted Registration）规范，用于与 CA Server 和 Challenge Server 进行交互，支持智能体证书的申请、更新和吊销功能。

## 功能特性

- ✅ **申请新证书**: 为指定的 Agent Identity Code (AIC) 申请新的 X.509 证书
- ✅ **更新证书**: 更新即将到期的证书
- ✅ **吊销证书**: 吊销已签发的证书
- ✅ **HTTP-01 挑战**: 支持 ATR 规范的 HTTP-01 验证方式
- ✅ **自动密钥管理**: 自动生成和管理 ACME 账户密钥和证书私钥
- ✅ **配置文件支持**: 支持外部配置文件
- ✅ **详细日志**: 提供详细的操作日志和调试信息
- ✅ **ATR 规范兼容**: 完全符合 ATR-DESIGN.md 中定义的 API 规范

## 文件结构

成功运行后，会生成以下文件：

```
ca-client/
├── acme-client.sh              # 主脚本
├── acme-client.conf            # 配置文件
├── challenge-server.sh         # 挑战验证服务器
├── README.md                   # 文档
├── certs/                      # 证书目录
│   ├── {aic}.crt              # 证书文件
│   ├── {aic}.csr              # 证书签名请求
│   └── revoked/               # 已吊销证书
├── private/                   # 私钥目录 (权限 700)
│   ├── account.key            # ACME 账户私钥
│   └── {aic}.key              # 证书私钥
└── challenges/                # 挑战文件目录
    └── {aic}/
        └── {token}
```

## 系统要求

确保系统中安装了以下工具：

- `openssl` - 用于密钥和证书操作
- `curl` - 用于 HTTP 请求
- `jq` - 用于 JSON 处理
- `base64` - 用于 Base64 编码 (通常系统自带)

### 安装依赖

**macOS:**

```bash
brew install openssl curl jq
```

**Ubuntu/Debian:**

```bash
sudo apt-get update
sudo apt-get install openssl curl jq
```

**CentOS/RHEL:**

```bash
sudo yum install openssl curl jq
```

## ACME 客户端及其配置

### acme-client.conf - ACME 客户端配置文件

`acme-client.conf` 支持以下配置项：

```properties
# CA 服务器基础URL (ATR 规范)
CA_SERVER_BASE_URL=http://ca-server:8003/acps-atr-v1

# Challenge 服务器基础URL (ATR 规范)
CHALLENGE_SERVER_BASE_URL=http://challenge-server:8004/acps-atr-v1

# 联系邮箱 (用于ACME账户注册)
CONTACT_EMAIL=admin@example.com

# 私钥长度
KEY_SIZE=2048

# 证书存储目录
CERT_DIR=./certs

# 私钥存储目录 (权限会设置为 700)
PRIVATE_KEY_DIR=./private

# 调试模式 (true/false)
DEBUG=false
```

### acme-client.sh - ACME 客户端程序

#### 命令格式

```bash
./acme-client.sh <command> --agent-id <agent_id> [options]
```

#### 可用命令

- `new-cert` - 申请新证书
- `renew-cert` - 更新现有证书
- `revoke-cert` - 吊销证书

#### 必需参数

- `--agent-id <id>` - Agent Identity Code (AIC)，例如 `01001560001000620251316469874465`

#### 可选参数

- `--config <file>` - 配置文件路径 (默认: `./acme-client.conf`)
- `--ca-server <url>` - CA 服务器基础 URL
- `--challenge-server <url>` - Challenge 服务器基础 URL
- `--contact <email>` - 联系邮箱
- `--key-size <size>` - 私钥长度 (默认: 2048)
- `--cert-dir <dir>` - 证书存储目录 (默认: `./certs`)
- `--private-dir <dir>` - 私钥存储目录 (默认: `./private`)
- `--force` - 强制操作，跳过确认
- `--debug` - 启用调试模式，输出详细日志
- `--reason <reason>` - 吊销原因 (仅用于 revoke-cert)

#### 证书吊销原因

- `unspecified` - 未指定 (0)
- `keyCompromise` - 密钥泄露 (1)
- `caCompromise` - CA 密钥泄露 (2)
- `affiliationChanged` - 归属变更 (3)
- `superseded` - 已被替代 (4)
- `cessationOfOperation` - 停止操作 (5)

#### 使用示例

```bash
# 申请新证书
./acme-client.sh new-cert --agent-id 01001560001000620251316469874465

# 使用自定义配置
./acme-client.sh new-cert \
  --agent-id 01001560001000620251316469874465 \
  --config /path/to/custom.conf \
  --contact admin@example.com

# 启用调试模式
./acme-client.sh new-cert \
  --agent-id 01001560001000620251316469874465 \
  --debug

# 更新证书
./acme-client.sh renew-cert --agent-id 01001560001000620251316469874465

# 吊销证书
./acme-client.sh revoke-cert \
  --agent-id 01001560001000620251316469874465 \
  --reason keyCompromise
```

## challenge-server.sh - HTTP-01 挑战验证服务器

用于处理 ACME HTTP-01 挑战验证的服务器，遵循 ATR 规范的 API 定义。

### 启动服务器

```bash
# 使用默认配置
./challenge-server.sh

# 指定端口和目录
./challenge-server.sh --port 8004 --challenge-dir /tmp/challenges

# 指定 API 基础路径
./challenge-server.sh --api-base-path /acps-atr-v1
```

### API 端点 (ATR 规范)

- `GET {API_BASE_PATH}/{agent_id}/{token}` - 获取挑战响应
- `POST {API_BASE_PATH}/{agent_id}/{token}` - 设置挑战响应
- `GET /status` - 服务器状态
- `GET /challenges` - 列出所有挑战

### 使用示例

```bash
# 设置挑战响应
curl -X POST http://localhost:8004/acps-atr-v1/01001560001000620251316469874465/token123 \
     -H "Content-Type: text/plain" \
     -d "token123.key_authorization"

# 获取挑战响应
curl http://localhost:8004/acps-atr-v1/01001560001000620251316469874465/token123

# 查看服务器状态
curl http://localhost:8004/status
```

## 安全注意事项

1. **私钥保护**: 私钥目录权限自动设置为 700，请勿修改
2. **配置文件**: 避免在配置文件中包含敏感信息
3. **网络安全**: 确保与 CA Server 的通信使用 HTTPS
4. **定期更新**: 建议在证书到期前 30 天内更新
5. **AIC 保护**: Agent Identity Code 应妥善保管，避免泄露

## 故障排除

如果遇到问题，请按以下步骤排查：

1. **检查系统依赖**: 确认 openssl、curl、jq 等工具已安装
2. **验证配置文件**: 检查 URL 格式和网络连通性
3. **启用调试模式**: 使用 `--debug` 参数查看详细日志信息
4. **检查服务状态**: 确认 CA Server 和 Challenge Server 正常运行
5. **验证 AIC 格式**: 确保使用正确的 Agent Identity Code
6. **网络连接**: 检查防火墙和网络代理设置
