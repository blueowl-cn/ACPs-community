# Agent CA 认证服务 - 开发环境搭建指南

本文档详细描述了如何搭建 Agent CA 认证服务的本地开发环境。

## 前置要求

- **Python**: 3.13+
- **PostgreSQL**: 14+
- **Git**: 2.0+
- **操作系统**: macOS / Linux / Windows

## 快速开始

### 1. 获取项目源代码

```bash
# 克隆项目仓库
git clone <项目仓库地址>
cd ca-server
# 切换到开发分支（如果有的话）
git checkout develop
```

### 2. 创建 Python 虚拟环境

```bash
# 创建虚拟环境（推荐使用 Python 3.13+）
python3 -m venv venv

# 激活虚拟环境
# macOS/Linux:
source venv/bin/activate

# Windows:
# venv\Scripts\activate

# 确认 Python 版本
python --version  # 应该显示 Python 3.13.x
```

### 3. 安装项目依赖

```bash
# 升级 pip 到最新版本
pip install --upgrade pip

# 安装项目依赖
pip install -r requirements.txt

# 验证关键依赖安装
pip list | grep -E "(fastapi|sqlmodel|alembic|uuid6|pytest)"
```

### 4. 配置环境变量

创建 `.env` 文件并配置以下环境变量：

```bash
# 复制环境变量模板
cp .env.example .env
```

在 `.env` 文件中根据实际情况修改各个配置项。

### 5. 初始化 Alembic 数据库迁移

```bash

# 应用数据库迁移（这个命令会根据迁移文件更新数据库结构）
alembic upgrade head

# 验证数据库连接和表结构
psql -U postgres -d agent_ca_dev -c "\dt"
```

### 6. 启动开发服务器

```bash
# 使用 uvicorn 直接启动（推荐开发时使用）
uvicorn main:app --reload
```

### 7. 验证安装

启动服务器后，访问以下 URL 验证安装：

- **API 文档**: http://localhost:8003/docs
- **ReDoc 文档**: http://localhost:8003/redoc
- **健康检查**: http://localhost:8003/health (如果实现了健康检查端点)

## 运行测试

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

## 常用开发命令

### 数据库相关

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

### 代码质量检查

```bash
# 代码格式化
black .

# 代码质量检查
flake8

# 运行所有预提交钩子
pre-commit run --all-files
```

### 依赖管理

```bash
# 生成当前环境的依赖列表
pip freeze > requirements.txt

# 安装新的依赖
pip install <package_name>

# 卸载依赖
pip uninstall <package_name>

# 清理 pip 缓存
pip cache purge

# 升级 pip
pip install --upgrade pip

# 重新安装依赖
pip install -r requirements.txt --force-reinstall
```

## 开发建议

1. **代码提交前**：确保运行 `pre-commit run --all-files` 检查代码质量
2. **数据库变更**：每次修改模型后运行 `alembic revision --autogenerate`
3. **测试驱动**：编写新功能前先编写测试用例
4. **环境隔离**：不同环境使用不同的数据库和配置
5. **日志记录**：合理使用日志级别，便于调试和监控

---

# Agent CA 服务器 - Mock 模式使用指南

## 概述

Agent CA 服务器支持 Mock 模式，允许在开发、测试或集成环境下无需真实外部服务即可返回模拟数据。Mock 模式通过环境变量控制，便于问题隔离和系统集成测试。

## Mock 模式配置

### 环境变量

在`.env`文件中配置以下环境变量来启用 Mock 模式：

```bash
# Agent注册服务Mock模式（默认: false）
AGENT_REGISTRY_MOCK=true

# HTTP-01验证服务Mock模式（默认: false）
HTTP01_VALIDATION_MOCK=true

# 通用外部服务Mock模式（默认: false）
EXTERNAL_SERVICES_MOCK=true
```

### 支持的 Mock 服务

#### 1. Agent 注册服务 Mock (AGENT_REGISTRY_MOCK=true)

当启用时，以下 API 调用将返回模拟数据：

- **validate_aic_and_get_info()**: 返回随机生成的 Agent 信息
- **validate_agent_endpoint()**: 返回随机的端点验证结果（80%成功率）
- **register_certificate_request()**: 返回随机的注册结果（85%成功率）
- **notify_certificate_issued()**: 返回随机的通知结果（90%成功率）
- **verify_agent_ownership()**: 返回随机的所有权验证结果（75%成功率）

#### 2. HTTP-01 验证服务 Mock (HTTP01_VALIDATION_MOCK=true)

当启用时，以下验证调用将返回模拟数据：

- **validate_challenge()**: 返回随机的挑战验证结果（80%成功率）
- **pre_validate_agent_endpoint()**: 返回随机的预验证结果（85%成功率）

## Mock 数据特性

### 随机性

每次请求都会生成不同的随机数据，包括：

- **Agent 信息**: 随机的组织名称、部门、国家、联系邮箱等
- **响应时间**: 模拟真实网络延迟（成功: 0.5-3.0s，失败: 5.0-30.0s）
- **成功/失败概率**: 不同 API 有不同的成功率，模拟真实环境
- **错误场景**: 包含各种常见的错误类型（网络超时、服务不可用、认证失败等）

### Mock 数据示例

#### Agent 信息示例

```json
{
  "aic": "agent-123-2024-XYZ",
  "valid": true,
  "agentInfo": {
    "organizationName": "TechCorp Solutions",
    "organizationalUnit": "Engineering",
    "country": "US",
    "state": "CA",
    "locality": "San Francisco",
    "contactEmail": "tech@techcorp.com",
    "status": "active"
  },
  "acmeChallengeEndpoint": "https://example.com/ca/agent/agent-123-2024-XYZ/",
  "registrationDate": "2024-06-15T10:30:00Z",
  "lastSeen": "2024-06-18T14:20:00Z"
}
```

#### HTTP-01 验证结果示例

```json
{
  "success": true,
  "response_time": 2.34,
  "details": {
    "status_code": 200,
    "url": "https://mock-agent-12345678.example.com/ca/agent/agent-123/token-456",
    "attempt": 1,
    "content_length": 64
  }
}
```

## 使用场景

### 1. 开发环境

```bash
# 启用所有Mock服务进行本地开发
AGENT_REGISTRY_MOCK=true
HTTP01_VALIDATION_MOCK=true
EXTERNAL_SERVICES_MOCK=true
```

### 2. 单元测试

```python
import os
os.environ["AGENT_REGISTRY_MOCK"] = "true"
os.environ["HTTP01_VALIDATION_MOCK"] = "true"

# 测试代码...
```

### 3. 集成测试

```bash
# 只Mock部分服务，测试特定集成点
AGENT_REGISTRY_MOCK=true
HTTP01_VALIDATION_MOCK=false  # 使用真实的HTTP-01验证
```

### 4. 演示环境

```bash
# 确保演示过程中服务稳定可用
AGENT_REGISTRY_MOCK=true
HTTP01_VALIDATION_MOCK=true
```

## 日志输出

当 Mock 模式启用时，会在日志中看到相应的提示信息：

```
AgentRegistryClient: Mock mode enabled
AgentRegistryClient: Using mock data for AIC validation: agent-123
HTTP01ValidationService: Mock mode enabled
HTTP01ValidationService: Using mock validation for agent: agent-456, token: token-123
```

## 测试 Mock 功能

运行测试脚本验证 Mock 功能：

```bash
# 运行 Mock 集成测试
python -m pytest tests/test_mock_integration.py -v

# 运行所有测试（包括 Mock 测试）
python -m pytest tests/ -v
```

Mock 集成测试位于 `tests/test_mock_integration.py`，包括：

- Agent 注册服务的各种 Mock 功能测试
- HTTP-01 验证服务的 Mock 功能测试
- Mock 数据随机性验证
- Mock 成功率验证

## 注意事项

1. **生产环境**: 确保生产环境中所有 Mock 模式都设置为`false`
2. **配置检查**: 启动时检查环境变量配置，确保符合预期
3. **日志监控**: 通过日志确认 Mock 模式是否按预期工作
4. **测试覆盖**: Mock 模式应该覆盖所有可能的成功和失败场景

## 扩展 Mock 功能

如需添加新的 Mock 功能，可以：

1. 在`app/acme/mock_data.py`中的`MockDataGenerator`类添加新方法
2. 在相应的服务类中添加 Mock 模式检查
3. 在`app/core/config.py`中添加新的配置选项
4. 在`.env.example`中添加配置示例
