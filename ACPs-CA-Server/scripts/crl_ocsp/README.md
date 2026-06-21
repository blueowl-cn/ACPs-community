# CRL 和 OCSP 功能测试与文档

这个目录包含了 Agent CA 项目中 CRL (Certificate Revocation List) 和 OCSP (Online Certificate Status Protocol) 功能的所有相关文件，包括测试脚本、演示代码、文档和工具。

## 📁 文件说明

### 🔧 工具脚本

- `init_crl_ocsp.py` - 初始化 CRL 和 OCSP 服务的脚本，创建基础配置
- `debug_batch_ocsp.py` - OCSP 批量查询调试脚本
- `run_crl_ocsp_tests.py` - 运行 CRL 和 OCSP 相关测试的便捷脚本

### 🎯 演示脚本

- `demo_crl_ocsp.py` - 完整的 CRL 和 OCSP API 使用演示，适合教学和测试

## 🚀 快速开始测试

### 1. 启动服务器

```bash
# 在项目根目录下
python main.py
```

### 2. 初始化 CRL 和 OCSP 服务

```bash
# 在项目根目录下
python scripts/crl_ocsp/init_crl_ocsp.py
```

### 3. 运行完整演示

```bash
# 在项目根目录下
python scripts/crl_ocsp/demo_crl_ocsp.py
```

### 4. 运行测试套件

```bash
# 在项目根目录下
python scripts/crl_ocsp/run_crl_ocsp_tests.py --all
```

## 🧪 测试流程详解

### 基础环境测试

```bash
# 运行基础的CRL和OCSP单元测试
python scripts/crl_ocsp/run_crl_ocsp_tests.py --unit

# 运行API集成测试
python scripts/crl_ocsp/run_crl_ocsp_tests.py --integration
```

### 功能验证测试

```bash
# 运行演示脚本进行功能验证
python scripts/crl_ocsp/demo_crl_ocsp.py

# 调试OCSP批量查询
python scripts/crl_ocsp/debug_batch_ocsp.py
```

## 📊 测试覆盖的功能

### CRL (证书撤销列表) 功能

- ✅ CRL 生成和管理
- ✅ CRL 信息查询 (`/api/v1/crl/info`)
- ✅ CRL 下载 - DER 格式 (`/api/v1/crl/current`)
- ✅ CRL 下载 - PEM 格式 (`/api/v1/crl/current/pem`)
- ✅ CRL 分发点配置 (`/api/v1/crl/distribution-points`)
- ✅ 历史 CRL 查询 (`/api/v1/crl/version/{version}`)
- ✅ CRL 刷新 (`POST /api/v1/crl/refresh`)

### OCSP (在线证书状态协议) 功能

- ✅ OCSP 响应器信息 (`/api/v1/ocsp/responder/info`)
- ✅ OCSP 批量查询 (`POST /api/v1/ocsp/batch`)
- ✅ OCSP 统计信息 (`/api/v1/ocsp/stats`)
- ✅ 简化证书状态查询 (`/api/v1/ocsp/certificate/{serial}`)
- ✅ 标准 OCSP 请求 - POST 方法 (`POST /api/v1/ocsp`)
- ✅ 标准 OCSP 请求 - GET 方法 (`GET /api/v1/ocsp/{base64_request}`)

## 🎯 教学价值

### 学习目标

1. **PKI 基础概念理解**

   - CRL 的作用和工作原理
   - OCSP 与 CRL 的区别和优劣
   - 证书状态管理机制

2. **实际开发技能**

   - FastAPI 框架的使用
   - SQLModel ORM 的实践
   - 密码学库的应用
   - RESTful API 设计规范

3. **测试驱动开发**
   - 单元测试编写
   - 集成测试设计
   - API 测试自动化
   - 错误处理验证

### 代码特点

- **清晰的模块化设计** - 分层架构便于理解
- **详细的中文注释** - 降低学习门槛
- **标准协议兼容** - 严格遵循 RFC 5280 和 RFC 6960
- **完整的测试覆盖** - 32 个测试用例全部通过

## 🔧 故障排除

### 常见问题

1. **服务器未启动**

   ```
   错误: Connection refused
   解决: 先运行 python main.py 启动服务器
   ```

2. **CRL/OCSP 服务未初始化**

   ```
   错误: No current CRL available
   解决: 运行 python scripts/crl_ocsp/init_crl_ocsp.py
   ```

3. **导入模块错误**
   ```
   错误: ModuleNotFoundError: No module named 'app'
   解决: 确保在项目根目录下运行脚本
   ```

### 验证步骤

1. **验证服务器状态**

   ```bash
   curl http://localhost:8003/health
   ```

2. **验证 CRL 服务**

   ```bash
   curl http://localhost:8003/api/v1/crl/info
   ```

3. **验证 OCSP 服务**
   ```bash
   curl http://localhost:8003/api/v1/ocsp/responder/info
   ```

## 📚 相关标准和文档

- **RFC 5280** - Internet X.509 Public Key Infrastructure Certificate and Certificate Revocation List (CRL) Profile
- **RFC 6960** - X.509 Internet Public Key Infrastructure Online Certificate Status Protocol - OCSP
- **RFC 8555** - Automatic Certificate Management Environment (ACME)

## 🔄 持续改进

如需进一步完善，可考虑：

### 性能优化

- CRL 和 OCSP 响应缓存机制
- 数据库查询优化
- 并发请求处理

### 安全加强

- OCSP nonce 验证实现
- 请求频率限制
- 完整的证书链验证

### 功能扩展

- Delta CRL 支持
- OCSP Stapling 实现
- 多 CA 环境支持
- 监控和告警机制

---

**注意**: 所有脚本都应该从项目根目录 (`ca-server/`) 运行，以确保正确的模块导入路径。
