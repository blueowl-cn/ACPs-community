# CA Client 使用指南

本文档介绍 `ca-client` 命令行工具的安装、配置及各场景下的使用示例。

---

## 1. 安装

从 wheel 包安装（生产部署）。先创建 Python 虚拟环境，然后使用 pip 安装：

```bash
python3.13 -m venv venv        # 创建虚拟环境
source venv/bin/activate    # 激活虚拟环境
pip install acps_ca_client-2.0.0-py3-none-any.whl # 安装 wheel 包
ca-client --help      # 验证安装成功
```

在没有激活虚拟环境的情况下，可以使用直接使用路径来调用：

```bash
./venv/bin/ca-client --help
```

这种调用方式适用于在脚本中直接调用 `ca-client`，无需激活虚拟环境。

## 2. 配置

在运行任何命令前，需先准备配置文件。

```bash
cp ca-client.conf.example .ca-client.conf
# 编辑 .ca-client.conf，填入实际地址和路径
```

> 客户端按顺序查找 `.ca-client.conf`、`ca-client.conf`，也可通过全局参数 `--config` 显式指定。

---

## 3. 全局参数

以下参数适用于所有子命令，须放在子命令名称之前：

| 参数        | 简写 | 默认值                                        | 说明                       |
| ----------- | ---- | --------------------------------------------- | -------------------------- |
| `--config`  | `-c` | 自动查找 `.ca-client.conf` / `ca-client.conf` | 指定配置文件路径           |
| `--verbose` | `-v` | 关闭                                          | 启用详细输出，显示调试信息 |
| `--help`    | `-h` |                                               | 显示帮助信息               |

**示例**：

```bash
# 使用自定义配置文件
ca-client --config /etc/ca-client/prod.conf new-cert --aic 1.2.156.3088.1.34C2.478BDF.3GF546.1.0156

# 启用详细输出
ca-client --verbose new-cert --aic 1.2.156.3088.1.34C2.478BDF.3GF546.1.0156
```

---

## 4. 子命令参考

### 4.1. `new-cert` — 申请新证书

为指定 AIC 申请新的 Agent 证书。流程包括：自动注册 ACME 账户、生成 Agent 私钥和 CSR、完成 HTTP-01 挑战验证、下载证书链，并自动更新信任包。

```bash
ca-client new-cert --aic <AIC> [选项]
```

| 参数                  | 简写 | 必填 | 默认值                           | 说明                                              |
| --------------------- | ---- | ---- | -------------------------------- | ------------------------------------------------- |
| `--aic`               | `-a` | 是   |                                  | Agent 身份码（AIC），点分 10 段格式               |
| `--key-type`          | `-k` | 否   | `ec`                             | 密钥类型：`ec`（ECDSA P-256）或 `rsa`（RSA 2048） |
| `--key-path`          |      | 否   | `{PRIVATE_KEYS_DIR}/{aic}.key`   | Agent 私钥输出路径                                |
| `--cert-path`         |      | 否   | `{CERTS_DIR}/{aic}.pem`          | 证书链输出路径                                    |
| `--trust-bundle-path` |      | 否   | 配置文件中的 `TRUST_BUNDLE_PATH` | 信任包输出路径                                    |

**输出文件**：

| 文件                           | 说明                            |
| ------------------------------ | ------------------------------- |
| `{PRIVATE_KEYS_DIR}/{aic}.key` | Agent 证书私钥（PEM，权限 600） |
| `{CSR_DIR}/{aic}.csr`          | 证书签名请求（中间文件）        |
| `{CERTS_DIR}/{aic}.pem`        | 证书链（Agent 证书 + CA 证书）  |
| `{TRUST_BUNDLE_PATH}`          | 最新信任包（自动更新）          |

> 以上为默认路径。通过 `--key-path`、`--cert-path`、`--trust-bundle-path` 可将对应文件直接输出到指定位置。

---

### 4.2. `renew-cert` — 续期证书

续期已有的 Agent 证书，流程与 `new-cert` 完全相同（使用相同 AIC 重新执行完整申请流程）。

```bash
ca-client renew-cert --aic <AIC> [选项]
```

| 参数                  | 简写 | 必填 | 默认值                           | 说明               |
| --------------------- | ---- | ---- | -------------------------------- | ------------------ |
| `--aic`               | `-a` | 是   |                                  | Agent 身份码       |
| `--key-path`          |      | 否   | `{PRIVATE_KEYS_DIR}/{aic}.key`   | Agent 私钥输出路径 |
| `--cert-path`         |      | 否   | `{CERTS_DIR}/{aic}.pem`          | 证书链输出路径     |
| `--trust-bundle-path` |      | 否   | 配置文件中的 `TRUST_BUNDLE_PATH` | 信任包输出路径     |

---

### 4.3. `revoke-cert` — 吊销证书

吊销指定 AIC 对应的 Agent 证书。

```bash
ca-client revoke-cert --aic <AIC> [--reason <REASON>]
```

| 参数       | 简写 | 必填 | 默认值        | 说明               |
| ---------- | ---- | ---- | ------------- | ------------------ |
| `--aic`    | `-a` | 是   |               | Agent 身份码       |
| `--reason` | `-r` | 否   | `unspecified` | 吊销原因（见下表） |

**吊销原因**：

| 值                     | 代码 | 说明         |
| ---------------------- | ---- | ------------ |
| `unspecified`          | 0    | 未指定原因   |
| `keyCompromise`        | 1    | 密钥泄露     |
| `cACompromise`         | 2    | CA 泄露      |
| `affiliationChanged`   | 3    | 隶属关系变更 |
| `superseded`           | 4    | 被新证书替代 |
| `cessationOfOperation` | 5    | 停止运营     |

---

### 4.4. `key-rollover` — 轮换 ACME 账户密钥

轮换 ACME 账户密钥，并将新密钥同步到 CA Server。旧密钥默认备份后替换。

```bash
ca-client key-rollover [选项]
```

| 参数                       | 简写 | 必填 | 默认值     | 说明                                               |
| -------------------------- | ---- | ---- | ---------- | -------------------------------------------------- |
| `--new-key`                | `-n` | 否   | 自动生成   | 新密钥文件路径（已存在则直接使用，否则写入此路径） |
| `--key-type`               | `-k` | 否   | `ec`       | 自动生成时的密钥类型：`ec` 或 `rsa`                |
| `--backup` / `--no-backup` | `-b` | 否   | `--backup` | 是否备份旧密钥（备份文件名附加时间戳）             |

---

### 4.5. `update-trust-bundle` — 更新信任包

从 CA Server 下载最新的信任包（包含本 CA 及互信 CA 的根证书），保存到 `TRUST_BUNDLE_PATH`。

```bash
ca-client update-trust-bundle
```

> 此命令无额外参数，使用配置文件中的 `CA_SERVER_BASE_URL` 和 `TRUST_BUNDLE_PATH`。

---

### 4.6. `download-crl` — 下载证书吊销列表

从 CA Server 下载 CRL（Certificate Revocation List）。

```bash
ca-client download-crl [选项]
```

| 参数       | 简写 | 必填 | 默认值                           | 说明                          |
| ---------- | ---- | ---- | -------------------------------- | ----------------------------- |
| `--output` | `-o` | 否   | `{CERTS_DIR}/ca.crl` 或 `ca.pem` | 输出文件路径                  |
| `--format` | `-f` | 否   | `der`                            | 格式：`der`（二进制）或 `pem` |

---

### 4.7. `check-ocsp` — OCSP 证书状态查询

通过 OCSP 协议查询证书当前状态（有效 / 已吊销 / 未知）。

```bash
ca-client check-ocsp --cert <CERT_PATH> --issuer <ISSUER_PATH>
```

| 参数       | 简写 | 必填 | 说明                          |
| ---------- | ---- | ---- | ----------------------------- |
| `--cert`   | `-c` | 是   | 待查询的证书文件路径（PEM）   |
| `--issuer` | `-i` | 是   | 签发 CA 的证书文件路径（PEM） |

---

## 5. 使用场景示例

### 场景一：首次为 Agent 申请证书

Agent 供应商在完成配置后首次为某个 AIC 申请证书。

```bash
# 1. 准备配置文件
cp ca-client.conf.example .ca-client.conf
# 编辑 .ca-client.conf 填入 CA_SERVER_BASE_URL 和 CHALLENGE_SERVER_BASE_URL

# 2. 申请证书（首次运行将自动生成 ACME 账户密钥）
ca-client new-cert --aic 1.2.156.3088.1.34C2.478BDF.3GF546.1.0156
```

执行后将生成以下文件：

```
./private/account.key              # ACME 账户私钥（首次自动生成）
./private/1.2.156.3088.1.34C2.478BDF.3GF546.1.0156.key   # Agent 私钥
./csr/1.2.156.3088.1.34C2.478BDF.3GF546.1.0156.csr       # CSR
./certs/1.2.156.3088.1.34C2.478BDF.3GF546.1.0156.pem     # 证书链
./certs/trust-bundle.pem           # 信任包（自动更新）
```

---

### 场景二：为多个 Agent 申请证书（批量）

同一个 Agent 供应商账号下有多个 AIC 需要申请证书，复用同一 ACME 账户。

```bash
# 第一个 Agent（同时生成 ACME 账户密钥）
ca-client new-cert --aic 1.2.156.3088.1.34C2.478BDF.3GF546.1.0156

# 后续 Agent（复用已有的 ACME 账户密钥）
ca-client new-cert --aic 1.2.156.3088.1.34C2.478BDF.3GF546.1.0157
ca-client new-cert --aic 1.2.156.3088.1.34C2.478BDF.3GF546.1.0158
```

---

### 场景三：指定输出路径（适合脚本和部署）

将私钥、证书和信任包直接输出到目标位置，无需额外拷贝。

```bash
ca-client new-cert \
  --aic 1.2.156.3088.1.34C2.478BDF.3GF546.1.0156 \
  --key-path /etc/agent/ssl/agent.key \
  --cert-path /etc/agent/ssl/agent.pem \
  --trust-bundle-path /etc/agent/ssl/trust-bundle.pem
```

也可以只指定部分路径，未指定的文件仍输出到默认位置：

```bash
# 仅指定证书路径，私钥和信任包使用默认位置
ca-client new-cert \
  --aic 1.2.156.3088.1.34C2.478BDF.3GF546.1.0156 \
  --cert-path /etc/agent/ssl/agent.pem
```

---

### 场景四：使用非默认配置文件

在多套环境（测试、生产）下分别维护不同的配置文件。

```bash
# 使用测试环境配置
ca-client --config ./conf/test.conf new-cert --aic 1.2.156.3088.1.34C2.478BDF.3GF546.1.0156

# 使用生产环境配置
ca-client --config ./conf/prod.conf new-cert --aic 1.2.156.3088.1.34C2.478BDF.3GF546.1.0156
```

---

### 场景五：证书到期前续期

建议在证书到期前 30 天内执行续期。续期与申请流程相同，不需要额外操作。

```bash
ca-client renew-cert --aic 1.2.156.3088.1.34C2.478BDF.3GF546.1.0156
```

> 旧证书被新证书替代后，CA Server 会自动将旧证书标记为已替代（`superseded`）。

---

### 场景六：因密钥泄露紧急吊销证书

当 Agent 私钥疑似泄露时，立即主动吊销证书。

```bash
ca-client revoke-cert \
  --aic 1.2.156.3088.1.34C2.478BDF.3GF546.1.0156 \
  --reason keyCompromise
```

吊销后，应立即重新申请新证书并使用新密钥：

```bash
# 删除旧私钥，强制生成新密钥
rm ./private/1.2.156.3088.1.34C2.478BDF.3GF546.1.0156.key

# 重新申请
ca-client new-cert --aic 1.2.156.3088.1.34C2.478BDF.3GF546.1.0156
```

---

### 场景七：停止运营，吊销所有证书

Agent 供应商停止运营某些 Agent 时，吊销相应证书。

```bash
ca-client revoke-cert \
  --aic 1.2.156.3088.1.34C2.478BDF.3GF546.1.0156 \
  --reason cessationOfOperation
```

---

### 场景八：轮换 ACME 账户密钥

建议每年轮换一次 ACME 账户密钥，提升安全性。

```bash
# 自动生成新密钥并轮换（旧密钥自动备份）
ca-client key-rollover

# 指定新密钥类型
ca-client key-rollover --key-type rsa

# 使用预先准备好的新密钥
ca-client key-rollover --new-key ./private/account-new.key

# 轮换但不备份旧密钥
ca-client key-rollover --no-backup
```

轮换完成后，旧密钥备份文件名格式为 `account.key.bak-{时间戳}`，例如：

```
./private/account.key.bak-20260311093000
```

---

### 场景九：手动更新信任包

以下情况建议手动更新信任包：新 CA 加入互信体系、部署新的 Agent 实例之前。

```bash
ca-client update-trust-bundle
```

信任包保存到配置文件中的 `TRUST_BUNDLE_PATH`（默认 `./certs/trust-bundle.pem`）。

---

### 场景十：下载 CRL 并离线验证证书状态

在无法访问 OCSP 的网络环境中，通过 CRL 进行离线证书状态校验。

```bash
# 下载 DER 格式 CRL（默认）
ca-client download-crl

# 下载 PEM 格式 CRL 到指定路径
ca-client download-crl --format pem --output ./certs/ca.pem
```

---

### 场景十一：通过 OCSP 实时查询证书状态

在互联网连通的环境中，实时验证证书是否有效。

```bash
ca-client check-ocsp \
  --cert ./certs/1.2.156.3088.1.34C2.478BDF.3GF546.1.0156.pem \
  --issuer ./certs/trust-bundle.pem
```

**输出示例（证书有效）**：

```
Checking OCSP status...
OCSP Response Status: OCSPResponseStatus.SUCCESSFUL
Certificate Status: OCSPCertStatus.GOOD
Certificate is valid (GOOD).
```

**输出示例（证书已吊销）**：

```
Checking OCSP status...
OCSP Response Status: OCSPResponseStatus.SUCCESSFUL
Certificate Status: OCSPCertStatus.REVOKED
Revocation Time: 2026-03-11 09:30:00+00:00
Revocation Reason: ReasonFlags.key_compromise
```

---

### 场景十二：调试模式排查问题

遇到问题时，使用 `--verbose` 参数查看详细的请求和响应信息。

```bash
ca-client --verbose new-cert --aic 1.2.156.3088.1.34C2.478BDF.3GF546.1.0156
```

---

## 6. 退出码

| 退出码 | 说明                                             |
| ------ | ------------------------------------------------ |
| 0      | 操作成功                                         |
| 1      | 一般错误（包含 ACME 协议错误、服务端拒绝等）     |
| 2      | 配置错误（配置文件缺失、格式错误或必填项未设置） |

> 当命令因 ACME 错误中断时，会在标准错误输出中打印具体错误信息和详情，可结合 `--verbose` 获取更完整的调试信息。
