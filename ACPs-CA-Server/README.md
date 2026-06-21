# Agent CA 认证服务 - 后端 API - 技术实现细节文档

这是一个基于 FastAPI 开发的 Agent CA 认证系统的后端 API，该系统允许用户管理数字证书。以下是该系统的技术实现细节文档。

## 1. 概述

### 1.1. 本项目的业务功能

本项目的业务功能主要包括以下几个方面：

1. ACME 协议 API：实现证书的自动化申请、续期和撤销等功能。RFC 8555 标准。
2. CRL 支持的 API：定期发布已吊销证书的列表。符合 RFC 5280 标准。
3. OCSP 支持的 API：实时查询证书状态。符合 RFC 6960 标准。
4. 根证书和中间证书的管理 API：根证书和中间证书的生成、续期、撤销和查询等功能。
5. 用户证书的状态查询与管理 API: 管理员应能查询和管理所有已签发、已吊销、已过期的证书。

### 1.2. 技术栈

- **Python 版本**: 3.13+
- **Web 框架**: FastAPI
- **数据验证与解析** Pydantic V2（避免使用 V1 版本的风格）
- **ORM**: SQLModel/SQLAlchemy
- **数据库**: PostgreSQL
- **数据库结构同步**: Alembic

### 1.3. 开发流程的规范

- **提交信息**: 使用 [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) 规范
- **分支管理**: 使用 Git Flow 工作流
- **版本命名**: 使用 [Semantic Versioning](https://semver.org/) 进行版本命名
- **测试**: 使用 pytest 进行单元测试和集成测试
- **代码审查**: 使用 GitLab Merge Request 进行代码审查
- **CI/CD**: 使用 GitLab 进行持续集成和持续部署
- **代码质量**: 使用 [Flake8](http://flake8.pycqa.org/en/latest/) 检查代码质量
- **代码格式化**: 使用 [Black](https://black.readthedocs.io/en/stable/) 进行代码格式化
- **强制代码格式化**: 使用 [pre-commit](https://pre-commit.com/) 进行代码格式化和检查

### 1.4. 代码风格及规范

- **代码风格**: 遵循 PEP 8 的风格和规范
- **类型注解**: 使用 Python 3.9+ 的类型注解，无需再从 typing 模块导入 List、Dict 等类型，使代码更简洁且更符合直觉。
- **文档字符串**: 使用 Google 风格的文档字符串
- **注释或文档的语言**: 使用中文作为注释或文档的语言，但关键性的专业词汇使用英文，避免翻译造成的歧义。

### 1.5. 目录结构及文件功能说明

```
ca-server/
│
├── app/                        # 主应用目录
│   ├── acme/                   # ACME 协议模块 (RFC 8555)
│   │   ├── api.py              #   路由和端点
│   │   ├── services.py         #   业务逻辑（账户、订单、挑战、签发流程）
│   │   ├── schemas.py          #   Pydantic 请求/响应模型
│   │   ├── models.py           #   数据库模型（Account, Order, Authorization, Challenge）
│   │   ├── jws_verifier.py     #   JWS 签名验证
│   │   ├── http01_validator.py #   HTTP-01 挑战验证器
│   │   ├── agent_registry.py   #   Agent Registry 服务集成
│   │   └── ...                 #   exception, error_handler, mock_data, utils
│   │
│   ├── certificates/           # 证书管理模块
│   │   ├── api.py              #   证书查询与管理 API
│   │   ├── api_ext.py          #   扩展 API（Trust Bundle 等）
│   │   └── services.py         #   证书签发、续期、查询等业务逻辑
│   │
│   ├── crl/                    # CRL 模块 (RFC 5280)
│   │   └── api.py              #   CRL 发布端点
│   │
│   ├── ocsp/                   # OCSP 模块 (RFC 6960)
│   │   └── api.py              #   OCSP 实时状态查询端点
│   │
│   ├── common/                 # 跨模块共享的数据库模型和服务
│   │   ├── certificate_*.py    #   证书相关的 model / schema / service
│   │   ├── crl_*.py            #   CRL 相关的 model / schema / service
│   │   ├── ocsp_*.py           #   OCSP 相关的 model / schema / service
│   │   └── time_utils.py       #   时间工具函数
│   │
│   ├── core/                   # 核心基础设施
│   │   ├── config.py           #   应用配置（环境变量、数据库连接等）
│   │   ├── db_session.py       #   数据库会话管理
│   │   ├── ca_manager.py       #   CA 证书与密钥管理
│   │   ├── base_exception.py   #   基础异常类
│   │   └── atr_ip_filter.py    #   ATR IP 白名单过滤
│   │
│   └── utils/                  # 通用工具函数
│
├── alembic/                    # 数据库迁移
│   └── versions/               #   迁移版本文件
│
├── certs/                      # CA 证书和密钥文件 (ca.crt, ca.key)
├── tests/                      # pytest 测试代码
├── main.py                     # 应用入口点
├── pyproject.toml              # 项目依赖管理 (Poetry)
├── alembic.ini                 # Alembic 迁移配置
├── run.sh                      # 服务启停管理脚本
└── .env                        # 环境变量配置（从 .env.example 复制）
```

---

## 2. 开发环境搭建步骤

### 2.1. 虚拟环境及依赖安装

```bash
cd ca-server
python3 -m venv venv # 创建虚拟环境（推荐使用 Python 3.13+）
source venv/bin/activate # 激活虚拟环境
pip install poetry # 安装 Poetry（如果未全局安装）
poetry install # 安装项目依赖
```

### 2.2. 配置环境变量

创建 `.env` 文件并配置以下环境变量：

```bash
# 复制环境变量模板
cp .env.example .env
```

在 `.env` 文件中根据实际情况修改各个配置项。

### 2.3. 数据库结构同步

```bash

# 应用数据库迁移（这个命令会根据迁移文件更新数据库结构）
alembic upgrade head

# （可选）验证数据库连接和表结构（数据库名称、用户名和密码需要与 .env 中的配置一致）
psql -U postgres -d agent_ca_dev -c "\dt"
```

### 2.4. 启动开发服务器

```bash
# 使用 uvicorn 直接启动（reload推荐开发时使用）
uvicorn main:app --reload
```

### 2.5. 验证安装

启动服务器后，访问以下 URL 验证安装：

- **API 文档**: http://localhost:8003/docs
- **ReDoc 文档**: http://localhost:8003/redoc
- **健康检查**: http://localhost:8003/health (如果实现了健康检查端点)

### 2.6. 后台运行

可以使用 `./run.sh` 脚本来管理后台服务：

```bash
./run.sh start      # 启动服务（若已运行则报错）
./run.sh stop       # 停止服务
./run.sh restart    # 重启服务（先停后启）
./run.sh status     # 查看服务状态
./run.sh kill-port  # 按端口杀死监听进程（PID文件丢失时的恢复手段，默认端口从配置读取）
./run.sh kill-port 8003  # 指定端口号
```

### 2.7. 打包

使用 Poetry 打包项目，打包文件将生成在 `dist/` 目录下：

```bash
poetry build
```

wheel文件可以传输到其他环境使用 pip 安装：

```bash
pip install agent_ca_server-2.0.0-py3-none-any.whl
```

## 3. Mock 模式

本项目支持 Mock 模式，允许在开发和测试环境下无需真实外部服务即可运行。通过 `.env` 文件中的环境变量控制：

- **`AGENT_REGISTRY_MOCK`**（默认 `false`）：启用后，Agent 注册服务的所有外部调用（AIC 验证、证书请求注册、签发通知、所有权验证）将返回模拟数据，业务操作始终返回成功。
- **`HTTP01_VALIDATION_MOCK`**（默认 `false`）：启用后，HTTP-01 挑战验证和端点预验证将返回模拟数据，始终返回验证成功。

## 4. 运行测试

测试基于pytest，使用前需要激活虚拟环境。测试相关的命令举例如下：

```bash
# 运行所有测试
pytest

# 运行测试并显示覆盖率
pytest --cov=app --cov-report=term-missing --cov-report=html

# 运行特定测试文件
pytest tests/test_acme.py

# 运行测试并生成详细报告
pytest -v --tb=short
```

## 5. 常用开发命令

### 5.1. 数据库相关

```bash
# 初始化 Alembic（只需要执行一次，会生成 alembic 目录。如果已经有alembic目录，跳过这一步）
alembic init alembic

# 创建一个迁移版本（每次数据库模型变更后都需要执行，此命令会生成一个新的迁移文件，用于版本控制，不会真的操作数据库）
alembic revision --autogenerate -m "描述迁移内容"

# 应用数据库迁移（这个命令会根据迁移文件更新数据库结构）
alembic upgrade head

# 回滚迁移
alembic downgrade -1

# 查看迁移历史
alembic history

# 查看当前迁移状态
alembic current

# 重置迁移（谨慎使用，会丢失数据）
alembic downgrade base
alembic upgrade head

# 手动标记迁移为已应用
alembic stamp head
```

### 5.2. 代码质量检查

```bash
# 代码格式化
black .

# 代码质量检查
flake8

# 运行所有预提交钩子
pre-commit run --all-files
```

### 5.3. 包依赖管理

```bash
# 安装新的依赖
poetry add <package_name>

# 安装新的开发依赖
poetry add --group dev <package_name>

# 卸载依赖
poetry remove <package_name>

# 升级依赖到约束范围内的新版本
poetry update

# pyproject.toml 发生较大变更后，先刷新锁文件
poetry lock

# 再按照锁文件安装依赖，确保环境一致
poetry install
```

---
