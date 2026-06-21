# Agent CA 认证服务 - ACME API 说明文档

本文档定义了 Agent CA 认证服务支持的 ACME 协议 API 接口，用于客户端自动获取、续期和吊销 Agent 证书。

## API 端点

### 1. 目录端点 (Directory)

获取 ACME 服务的所有端点信息。

```
GET /acps-atr-v1/acme/directory
```

**权限级别:** `public` - 任何客户端都需要获取 ACME 服务端点信息

**响应示例:**

```json
{
  "newNonce": "https://ca.example.com/acps-atr-v1/acme/new-nonce",
  "newAccount": "https://ca.example.com/acps-atr-v1/acme/new-account",
  "newOrder": "https://ca.example.com/acps-atr-v1/acme/new-order",
  "revokeCert": "https://ca.example.com/acps-atr-v1/acme/revoke-cert",
  "keyChange": "https://ca.example.com/acps-atr-v1/acme/key-change",
  "meta": {
    "termsOfService": "https://ca.example.com/terms",
    "website": "https://ca.example.com",
    "caaIdentities": ["ca.example.com"],
    "externalAccountRequired": false
  }
}
```

### 获取 CA 根证书

**GET** `/ca-cert`

直接返回 PEM 格式的根证书，`Content-Type: application/x-pem-file`，并附带 `Content-Disposition: attachment; filename=ca.crt`。

### Nonce 管理

- **HEAD / GET** `/new-nonce` 生成一次性 nonce。
- 响应头包含 `Replay-Nonce`，`Cache-Control` 为 `no-store`。

### 账户管理

#### 创建账户

**POST** `/new-account`

- 请求体：JWS，`protected` 中必须包含 `jwk`。
- 当 `payload.onlyReturnExisting` 为 `true` 时，将尝试返回已存在账户，否则创建新账户。
- 成功创建返回 `201`，重复调用返回 `200`。

解码后的 `payload` 示例：

```json
{
  "termsOfServiceAgreed": true,
  "contact": ["mailto:admin@example.com"],
  "onlyReturnExisting": false
}
```

响应数据：

```json
{
  "status": "valid",
  "contact": ["mailto:admin@example.com"],
  "termsOfServiceAgreed": true,
  "orders": "https://ca.example.com/acps-atr-v1/acme/acct/1/orders"
}
```

响应头包含 `Location: .../acct/{accountId}` 以及新的 `Replay-Nonce`。

#### 更新账户

**POST** `/acct/{accountId}`

- 使用 `kid` 或 `jwk` 标识账户。
- `payload` 可更新 `contact` 与 `status` 字段。
- 响应结构同创建账户，状态码 `200`。

### 订单流程

#### 创建订单

**POST** `/new-order`

- `payload.identifiers` 必须是 `[{"type": "agent", "value": "<AIC>"}]`。
- 服务内部会调用 Agent Registry 预验证 AIC 及 HTTP-01 验证端点。
- 成功后返回 `201`，`authorizations` 字段给出授权 URL 列表：

```json
{
  "status": "pending",
  "expires": "2024-05-01T08:00:00Z",
  "identifiers": [
    { "type": "agent", "value": "10001000011K912345E789ABCDEF2353" }
  ],
  "authorizations": ["https://ca.example.com/acps-atr-v1/acme/authz/1"],
  "finalize": "https://ca.example.com/acps-atr-v1/acme/order/1/finalize"
}
```

#### 查询订单

**POST** `/order/{orderId}`

- 返回订单状态、授权列表及（当可用时）`certificate` URL。

#### 获取授权详情

**POST** `/authz/{authzId}`

- 返回授权状态、到期时间以及每个挑战的 URL、token、状态。
- 当前实现仅生成 HTTP-01 挑战。

#### 响应挑战

**POST** `/challenge/{challengeId}`

- 验证 HTTP-01 结果。成功后挑战状态为 `valid`，对应授权变为 `valid`。

#### 完成订单

**POST** `/order/{orderId}/finalize`

- `payload.csr` 为 base64url 编码的 DER 格式 CSR。
- 所有关联授权均为 `valid` 时允许执行，签发完成后返回：

```json
{
  "status": "valid",
  "certificate": "https://ca.example.com/acps-atr-v1/acme/cert/abcd-1234",
  "authorizations": ["https://ca.example.com/acps-atr-v1/acme/authz/1"],
  "finalize": "https://ca.example.com/acps-atr-v1/acme/order/1/finalize"
}
```

#### 下载证书

**POST** `/cert/{certId}`

- 返回 `application/pem-certificate-chain`，主体为 PEM 证书链。

#### 吊销证书

**POST** `/revoke-cert`

请求体：

```json
{
  "certificate": "<base64url DER>",
  "reason": 0
}
```

- `reason` 取值 `0-5`，含义与 RFC 8555 保持一致。
- 成功响应：

```json
{
  "status": "success",
  "message": "Certificate revoked successfully",
  "revocation_date": "2024-05-01T08:10:00Z",
  "reason": 0
}
```

#### 更换账户密钥

**POST** `/key-change`

- 外层 JWS 使用旧密钥签名，`payload` 为内层 JWS 字符串；内层 JWS 由新密钥签名并包含：

```json
{
  "account": "/acps-atr-v1/acme/acct/{accountId}",
  "oldKey": { "kty": "RSA", "n": "...", "e": "AQAB" }
}
```

---

## 证书管理 API (`/admin/certificates`)

接口实现见 `app/certificates/api.py`。所有请求/响应均使用 JSON，除下载证书外。

### 根证书管理

| 方法 | 路径                           | 说明                                              |
| ---- | ------------------------------ | ------------------------------------------------- |
| GET  | `/root`                        | 列出所有根证书，返回 `List[CertificateResponse]`  |
| POST | `/root`                        | 创建根证书，请求体 `CreateRootCertificateRequest` |
| POST | `/root/{certificateId}/renew`  | 续期根证书，可选 `validity_days` query            |
| POST | `/root/{certificateId}/revoke` | 吊销根证书，必填 query `reason`                   |

`CreateRootCertificateRequest` 字段：

- `subject_name` (string)
- `validity_days` (int，默认 3650)

`CertificateResponse` 关键字段：

- `id`, `serial_number`, `certificate_type`, `status`
- `issued_at`, `expires_at`, `revoked_at`
- `certificate_pem`, `public_key`, `aic`

### 中间证书管理

| 方法 | 路径                                   | 说明                                                        |
| ---- | -------------------------------------- | ----------------------------------------------------------- |
| GET  | `/intermediate`                        | 支持 `parent_id` 过滤，返回列表                             |
| GET  | `/intermediate/{certificateId}`        | 获取详细信息                                                |
| POST | `/intermediate`                        | 创建中间证书，请求体 `CreateIntermediateCertificateRequest` |
| POST | `/intermediate/{certificateId}/renew`  | 续期中间证书                                                |
| POST | `/intermediate/{certificateId}/revoke` | 吊销中间证书，query `reason`                                |

`CreateIntermediateCertificateRequest` 字段：`subject_name`, `parent_certificate_id`, `validity_days`。

### 普通证书操作

| 方法 | 路径                        | 说明                                                                                                           |
| ---- | --------------------------- | -------------------------------------------------------------------------------------------------------------- |
| GET  | `/`                         | 分页查询证书列表，支持 `page`, `page_size`, `certificate_type`, `status`, `aic` 查询参数，返回 `PagedResponse` |
| GET  | `/{certificateId}`          | 获取指定证书详情                                                                                               |
| GET  | `/{certificateId}/download` | 下载 PEM 证书，返回 `text/plain`                                                                               |
| GET  | `/{certificateId}/chain`    | 返回证书链，类型 `List[CertificateResponse]`                                                                   |
| POST | `/{certificateId}/revoke`   | 手动吊销证书，query `reason`                                                                                   |
| GET  | `/expiring`                 | 查询即将过期的证书，默认 `days_ahead=30`                                                                       |

`PagedResponse` 结构：

```json
{
  "items": [
    {
      "id": "...",
      "certificate_type": "END_ENTITY",
      "serial_number": "1A2B...",
      "subject": "CN=agent-001",
      "issuer": "CN=Agent Intermediate",
      "status": "valid",
      "issued_at": "2024-03-01T00:00:00",
      "expires_at": "2024-04-19T00:00:00",
      "aic": "10001000011K912345E789ABCDEF2353"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

---

## ATR 管理吊销 API (`/acps-atr-v1/mgmt`)

### 批量吊销 Agent 证书

**POST** `/revoke`

请求体 (`RevokeRequest`):

```json
{
  "aic": "10001000011K912345E789ABCDEF2353",
  "reason": 3
}
```

`reason` 范围 `0-5`，服务会调用 `CertificateManagementService.revoke_certificates_by_aic` 吊销所有 `pending/valid` 状态证书。响应 (`RevokeResponse`)：

```json
{
  "aic": "10001000011K912345E789ABCDEF2353",
  "revocation_reason": "affiliationChanged",
  "revoked_at": "2024-05-01T08:15:30Z",
  "revoked_cert_count": 2
}
```

---

## CRL API (`/acps-atr-v1/crl`)

### 公共查询接口

| 方法 | 路径                   | 说明                                              |
| ---- | ---------------------- | ------------------------------------------------- |
| GET  | `/current`             | 返回最新 CRL 的 DER 内容 (`application/pkix-crl`) |
| GET  | `/current/pem`         | 返回最新 CRL 的 PEM 内容                          |
| GET  | `/info`                | 返回 `CRLInfoResponse` 元数据                     |
| GET  | `/version/{version}`   | 下载指定版本（`YYYYMMDDHH`）的历史 CRL            |
| GET  | `/distribution-points` | 返回 `CRLDistributionPointsResponse`              |
| GET  | `/detail`              | 返回当前 CRL 的详细吊销列表                       |

`CRLInfoResponse` 主要字段：`version`, `issuer`, `this_update`, `next_update`, `revoked_certificates_count`, `crl_size`, `distribution_point`, `signature`。

`/detail` 返回示例：

```json
{
  "version": "2024050108",
  "issuer": "CN=Agent CA Intermediate",
  "thisUpdate": "2024-05-01T08:00:00",
  "nextUpdate": "2024-05-01T20:00:00",
  "revokedCertificates": [
    {
      "serialNumber": "1A2B3C",
      "revocationDate": "2024-04-30T12:00:00",
      "reason": "keyCompromise"
    }
  ],
  "revokedCertificatesCount": 1
}
```

### 管理接口

| 方法 | 路径       | 说明                                                   |
| ---- | ---------- | ------------------------------------------------------ |
| GET  | `/list`    | 分页查询历史 CRL（支持 `status`, `page`, `page_size`） |
| POST | `/refresh` | 重新生成最新 CRL，返回新的 `CRLInfoResponse`           |

---

## OCSP API (`/acps-atr-v1/ocsp`)

### 在线状态查询

| 方法 | 路径                           | 说明                                                        |
| ---- | ------------------------------ | ----------------------------------------------------------- |
| POST | `/`                            | 接收 DER 编码的 OCSP 请求，返回 `application/ocsp-response` |
| GET  | `/{base64_request}`            | Base64URL 编码的 OCSP 请求（末尾自动补 `==`）               |
| GET  | `/certificate/{serial_number}` | 简化接口，直接返回证书状态 JSON                             |

`/certificate/{serial_number}` 示例响应：

```json
{
  "serialNumber": "1A2B3C",
  "certificateStatus": "good",
  "thisUpdate": "2024-05-01T08:00:00",
  "nextUpdate": "2024-05-01T20:00:00"
}
```

### 批量与元数据

| 方法 | 路径              | 说明                                                 |
| ---- | ----------------- | ---------------------------------------------------- |
| POST | `/batch`          | 请求体 `OCSPBatchRequest`，返回 `OCSPBatchResponse`  |
| GET  | `/responder/info` | 返回 `OCSPResponderInfo`                             |
| GET  | `/stats`          | 返回 `OCSPStatsResponse`，包含累计请求数、平均耗时等 |

`OCSPBatchRequest` 结构：

```json
{
  "certificates": [
    {
      "serial_number": "1A2B3C",
      "issuer_key_hash": "AABB...",
      "issuer_name_hash": "CCDD...",
      "hash_algorithm": "sha1"
    }
  ]
}
```

`OCSPBatchResponse` 示例：

```json
{
  "responses": [
    {
      "serial_number": "1A2B3C",
      "status": "good",
      "this_update": "2024-05-01T08:00:00",
      "next_update": "2024-05-01T20:00:00",
      "revocation_time": null,
      "revocation_reason": null
    }
  ],
  "responder_id": "CN=Agent CA OCSP Responder",
  "produced_at": "2024-05-01T08:00:05"
}
```

---

## 错误与返回码

- ACME 端点统一抛出 `AcmeException`，使用 `urn:ietf:params:acme:error:*` 错误码及 `Replay-Nonce` 头。
- 证书管理、CRL、OCSP API 返回 FastAPI 标准错误结构：

```json
{
  "detail": "<错误描述>"
}
```

或（当显式使用 `ErrorResponse`）

```json
{
  "error": "INVALID_REQUEST",
  "detail": "具体原因"
}
```

---

## 调试提示

- 查看完整 OpenAPI 描述：启动服务后访问 `/docs` 或 `/redoc`。
- 日志文件位于 `ca-server.log`，数据库为 `ca_server.db`（SQLite）。
- ACME 流程依赖外部 Agent Registry 与 HTTP-01 验证服务，运行测试时可使用 `app/acme/mock_data.py` 与 `tests/` 下的集成用例参考请求格式。
