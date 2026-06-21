# Agent CA 认证服务 - 业务功能说明


本文档详细描述了 Agent CA 认证服务的业务功能，也即是需求说明。

## Agent CA 证书设计说明

Agent CA 认证服务与传统的域名 CA 认证主题功能和结构都是一样的，唯一的区别，就是认证对象不一样。Agent CA 认证服务的认证对象是 Agent 注册数据，而不是域名。

所以，Agent CA 认证服务不需要 DNS-01 和 TLS-ALPN 验证，只有 HTTP-01 验证方式。并且 HTTP-01 验证方式的验证路径是可以由 Agent 注册信息来指定的，比如 `/ca/agent/<agent_id>/<token>`，而不是传统域名 CA 认证中固定的 `/.well-known/acme-challenge/<token>`。

除了上述的认证主体和验证地址之外，Agent CA 认证服务的其他功能与传统域名 CA 认证服务几乎完全一样。客户端和服务器之间的自动化交互流程（ACME 协议）也是一样的。

Agent CA 认证的对象是 Agent 注册完成后，生成的 AIC（Agent Identify Code） 作为认证对象。AIC 是一个 32 个字符的字符串。本项目需要用客户提供的 AIC 向注册服务发送请求确认 AIC 的正确性，并获取 AIC 相关的附加信息，比如这个 AIC 注册的公司等信息，可以作为证书的附加信息。Agent 注册服务是一个外部服务，本项目中主要关心证书的生成和验证流程，以及其他证书操作。

### 证书主体 (Subject) 设计原则

Agent CA 证书的设计遵循以下原则：

1. **标识符优先**: CN 字段始终使用完整的 AIC（Agent Identify Code），确保证书的唯一性和可识别性
2. **组织信息可选**: 根据 Agent 注册时提供的信息决定是否包含组织相关字段
3. **与传统 SSL 兼容**: 采用标准的 X.509 DN 结构，便于现有工具和系统的处理
4. **灵活适配**: 支持从简单的 AIC（Agent Identify Code） 到包含完整组织信息的多种证书格式

### 与传统域名证书的对比

| 字段     | 传统 SSL 证书                  | Agent CA 证书                                               |
| -------- | ------------------------------ | ----------------------------------------------------------- |
| CN       | 域名 (如 www.example.com)      | AIC 对应域名 (如 10001000011K912345E789ABCDEF2353.acps.pub) |
| O        | 证书申请公司名称               | Agent 所属组织 (从注册信息获取)                             |
| OU       | 公司部门                       | Agent 功能分类或部门归属                                    |
| 验证方式 | DNS-01, HTTP-01, TLS-ALPN-01   | 仅 HTTP-01                                                  |
| 验证路径 | `/.well-known/acme-challenge/` | `/ca/agent/{agent_id}/`                                     |

### 与标准 ACME 协议的区别

Agent CA 服务基于 [RFC 8555 ACME 协议](https://tools.ietf.org/html/rfc8555)，但针对 Agent 认证场景进行了以下调整：

1. **认证对象**: 从域名改为 AIC（Agent Identify Code）
2. **验证方式**: 仅支持 HTTP-01 验证，不支持 DNS-01 和 TLS-ALPN-01
3. **验证路径**: 从固定的 `/.well-known/acme-challenge/<token>` 改为可配置的 `/ca/agent/<agent_id>/<token>`

### 证书模板

#### Distinguished Name (DN) 结构

Agent CA 证书的主体信息 (Subject) 采用以下结构：

- **CN (Common Name)**: AIC 对应的完全限定域名 (必需)

  - 格式: `<AIC>.<suffix>`，例如 `10001000011K912345E789ABCDEF2353.acps.pub`
  - 域名后缀通过环境变量 `AGENT_CN_DOMAIN_SUFFIX` 配置，默认值为 `acps.pub`
  - 说明: AIC 由 32 位大写字母与数字组成（参考 ACPs-spec-AIC-v01.00），CN 使用域名形式确保与现有 PKI 基础设施兼容

- **O (Organization)**: Agent 所属组织 (可选)

  - 从 Agent 注册信息中获取，如 `Acme Corporation`
  - 如果 Agent 注册时未提供组织信息，则省略此字段

- **OU (Organizational Unit)**: Agent 部门或用途 (可选)

  - 如 `AI Assistant Services` 或 `Customer Support`
  - 基于 Agent 的功能分类或部门归属

- **C (Country)**: 国家代码 (可选)
  - 如 `US`, `CN`, `GB` 等
  - 从 Agent 注册信息或组织信息中获取

**示例 DN 结构：**

```
# 完整信息的Agent证书
CN=10001000011K912345E789ABCDEF2353.acps.pub, OU=AI Assistant Services, O=Acme Corporation, C=US

# 最小信息的Agent证书
CN=10001000011K912345E789ABCDEF2353.acps.pub

# 包含组织但无部门的Agent证书
CN=20001000022L012345F123ABCDEF4477.acps.pub, O=Tech Solutions Ltd, C=UK
```

## 本项目的业务功能

本项目的业务功能主要包括以下几个方面：

1. ACME 协议 API：实现证书的自动化申请、续期和撤销等功能。RFC 8555 标准。
2. CRL 支持的 API：定期发布已吊销证书的列表。符合 RFC 5280 标准。
3. OCSP 支持的 API：实时查询证书状态。符合 RFC 6960 标准。
4. 根证书和中间证书的管理 API：根证书和中间证书的生成、续期、撤销和查询等功能。
5. 用户证书的状态查询与管理 API: 管理员应能查询和管理所有已签发、已吊销、已过期的证书。

# Agent CA 认证服务 - 后端 API - 技术实现细节文档

这是一个基于 FastAPI 开发的 Agent CA 认证系统的后端 API，该系统允许用户管理数字证书。以下是该系统的技术实现细节文档。

## 技术栈

- **Web 框架**: FastAPI
- **数据验证与解析** Pydantic V2（避免使用 V1 版本的风格）
- **ORM**: SQLModel/SQLAlchemy
- **数据库**: PostgreSQL
- **数据库结构同步**: Alembic

## 开发流程的规范

- **提交信息**: 使用 [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) 规范
- **分支管理**: 使用 Git Flow 工作流
- **版本命名**: 使用 [Semantic Versioning](https://semver.org/) 进行版本命名
- **测试**: 使用 pytest 进行单元测试和集成测试
- **代码审查**: 使用 GitLab Merge Request 进行代码审查
- **CI/CD**: 使用 GitLab 进行持续集成和持续部署
- **代码质量**: 使用 [Flake8](http://flake8.pycqa.org/en/latest/) 检查代码质量
- **代码格式化**: 使用 [Black](https://black.readthedocs.io/en/stable/) 进行代码格式化
- **强制代码格式化**: 使用 [pre-commit](https://pre-commit.com/) 进行代码格式化和检查

## 代码风格及规范

- **Python 版本**: 3.13+
- **代码风格**: 遵循 PEP 8 的风格和规范
- **类型注解**: 使用 Python 3.9+ 的类型注解，无需再从 typing 模块导入 List、Dict 等类型，使代码更简洁且更符合直觉。
- **文档字符串**: 使用 Google 风格的文档字符串
- **注释或文档的语言**: 使用中文作为注释或文档的语言，但关键性的专业词汇使用英文，避免翻译造成的歧义。

## 目录结构及文件功能说明

```
ca-server/
│
├── app/                       # 主应用目录
│   ├── __init__.py            # 应用初始化
│   ├── acme/                 # 功能模块，此处acme模块为示例
│   │   ├── __init__.py        # 模块初始化
│   │   ├── api.py             # API 路由和端点
│   │   ├── exception.py       # 异常定义
│   │   ├── model.py           # 数据模型定义
│   │   ├── schema.py          # Pydantic 验证模式
│   │   ├── service.py         # 业务逻辑服务
│   │   └── utils.py            # 本模块的工具函数
│   │
│   ├── crl/                    # 其它功能模块 (结构类似)
│   │   └── ...
│   │
│   ├── core/                  # 核心配置
│   │   ├── __init__.py        # 模块初始化
│   │   ├── base_exception.py  # 基础异常类
│   │   ├── config.py          # 应用配置
│   │   └── db_session.py      # 数据库会话管理
│   │
│   └── utils/                 # 通用工具函数
│       └── ...
│
├── alembic/                   # Alembic 数据库迁移，由"alembic init alembic"命令自动生成
│   ├── versions/              # 数据库迁移版本
│   ├── env.py                 # Alembic 环境配置，在自动生成的内容之上需要按照开发步骤的说明进行修改
│   ├── README                 # Alembic 使用说明
│   └── script.py.mako         # 迁移脚本模板
│
├── tests/                     # 测试代码
│
├── alembic.ini                # Alembic 配置文件，由"alembic init alembic"命令自动生成
├── main.py                    # 应用入口点
├── README.md                  # 项目基本说明
├── requirements.txt           # 项目依赖
```

## 数据(Model)和数据库设计和代码的相关约定

- 数据库主键使用 UUID，使用第三方库 "uuid6" 中的 uuid7。
- Pydantic 使用 V2 版本的风格，避免使用 V1 版本的风格。
- 数据库模型使用 SQLModel，避免使用 SQLAlchemy 的 ORM。

## API 端点和业务逻辑(Service)的联系与区别

- Service 类封装业务逻辑，避免在 API 路由中直接编写业务逻辑。
- API 端点中使用 Schema 类进行数据验证和解析。使用 Dict 类型传递给 Service 类。
- Service 类中主要使用 Model 类进行数据返回，使用 JOIN 取出所有关联数据。
- API 端点中使用 Schema 类对 Model 类进行格式转换后返回。

## API 相关约定

- API 采用正常的 RESTful API 的设计。
- API 请求的数据和返回数据都使用 JSON 格式，避免使用表单格式。
- 请求数据和返回数据都使用 Pydantic 模式进行验证，避免数据错误。
- 请求数据和返回数据都使用类型注解进行类型检查，避免类型错误。
