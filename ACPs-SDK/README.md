# ACPs SDK

Agent Collaboration Protocols（智能体协作协议体系）SDK — ACPs 协议体系的 Python 实现。

目前本SDK包含以下模块：

| 模块           | 说明                                          |
| -------------- | --------------------------------------------- |
| `acps_sdk.acs` | Agent Capability Specification 智能体能力描述 |
| `acps_sdk.adp` | Agent Discovery Protocol 智能体发现协议       |
| `acps_sdk.aic` | Agent Identity Code 智能体身份码              |
| `acps_sdk.aip` | Agent Interaction Protocol 智能体交互协议     |

## 1. SDK本地开发环境

### 1.1. 开发环境搭建

建议使用 Python 3.13+，并通过 Poetry 打包。

```bash
# 克隆仓库
git clone <仓库地址>
cd acps-sdk

# 安装并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装 poerty（如果尚未全局安装，则在虚拟环境中安装）
pip install poetry

# 安装SDK项目的依赖
poetry install
```

### 1.2. 构建和发布

```bash
poetry build
```

生成的 wheel 和 sdist 将位于 `dist/` 目录。

发布到 PyPI：

```bash
poetry publish --username <PyPI用户名> --password <PyPI密码>
```

## 2. 目标项目中SDK的安装

### 2.1 使用pip

在需要使用本SDK的Python环境中，可以通过 pip 安装。

从 PyPI（发布后）:

```bash
pip install acps-sdk
```

从本地 wheel 文件:

```bash
pip install path/to/acps_sdk-2.0.0-py3-none-any.whl
```

### 2.2 使用pyproject.toml

在需要使用本SDK的项目，可以用 `pyproject.toml` 管理依赖。

从 PyPI（发布后）：

```toml
[tool.poetry.dependencies]
acps-sdk = "^2.0.0"
```

从本地 wheel 文件：

```toml
[tool.poetry.dependencies]
acps-sdk = { path = "path/to/acps_sdk-2.0.0-py3-none-any.whl" }
```

从本地源码：

```toml
[tool.poetry.dependencies]
acps-sdk = { path = "../acps-sdk" }
```

## 3. SDK使用示例代码

```python
from acps_sdk.acs import AgentCapabilitySpec
from acps_sdk.aip import AipRpcClient, TaskState
from acps_sdk.aic import validate_aic_format, parse_aic
```
