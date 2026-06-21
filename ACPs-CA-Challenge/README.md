# CA Challenge Server

Agent Trusted Registration (ATR) 协议中的挑战服务器（Challenge Server）实现。

## 1. 项目简要说明

本项目实现了 ATR 协议中的 HTTP-01 挑战响应机制。Challenge Server 部署在 Agent 侧，主要职责包括：

1.  **接收挑战响应**：接收 CA Client (Agent) 设置的挑战响应内容（Key Authorization）。
2.  **提供验证接口**：向 CA Server 提供验证接口，返回存储的挑战响应内容以完成域名所有权验证。

本项目基于 **FastAPI** 框架开发，使用 **Poetry** 进行依赖管理，支持高并发和异步处理。

### 前置要求

- Python 3.10+
- Poetry 包管理工具

## 2. 项目开发说明

### 开发环境搭建

推荐使用本地虚拟环境进行开发，避免污染全局环境。

**创建环境安装依赖**：

```bash
python3 -m venv venv # 创建虚拟环境
source venv/bin/activate # 激活虚拟环境
pip install poetry # 安装 Poetry，(如果未全局安装)
poetry install # 安装项目依赖
```

**配置环境变量**：

复制示例配置文件并根据需要修改：`cp .env.example .env`

修改 `.env` 文件，例如开启热加载以便于调试：`UVICORN_RELOAD=true`

### 运行与调试

确保虚拟环境已激活，然后执行以下命令启动服务（默认加载 `.env`）：

```bash
python main.py
```

如果需要指定其他配置文件（例如 `.env.dev`），可以使用 `ENV_FILE` 环境变量：

```bash
ENV_FILE=.env.dev python main.py
```

或者使用 `uvicorn` 运行：

```bash
# 默认加载 .env
uvicorn acps_ca_challenge.main:app --reload --host 0.0.0.0 --port 8004

# 指定配置文件
ENV_FILE=.env.dev uvicorn acps_ca_challenge.main:app --reload --host 0.0.0.0 --port 8004
```

服务启动后，可以访问 `http://localhost:8004/docs` 查看交互式 API 文档。

### 后台运行

`./run.sh` 会直接使用 `./venv/bin/python`（或 `.venv/bin/python`）启动服务，因此执行前需要先完成上面的虚拟环境创建和依赖安装。

```bash
./run.sh start      # 启动服务（若已运行则报错）
./run.sh stop       # 停止服务
./run.sh restart    # 重启服务（先停后启）
./run.sh status     # 查看服务状态
./run.sh kill-port  # 按端口杀死监听进程（PID文件丢失时的恢复手段，默认端口从配置读取）
./run.sh kill-port 8004  # 指定端口号
```

## 3. 项目部署说明

本项目支持打包为 Python Wheel 包进行分发和部署。

### 打包

在开发环境中（确保已安装 poetry），执行以下命令进行打包：

```bash
poetry build
```

打包完成后，会在 `dist/` 目录下生成 `.whl` 文件（例如 `acps_ca_challenge-2.0.0-py3-none-any.whl`）和 `.tar.gz` 源码包。

### 部署步骤

1.  **传输文件**：将生成的 `.whl` 文件拷贝到目标部署服务器。

2.  **环境准备**：在服务器上创建并激活虚拟环境。

    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **安装应用**：使用 `pip` 安装上传的 `.whl` 文件。

    ```bash
    pip install acps_ca_challenge-2.0.0-py3-none-any.whl
    ```

    _注意：文件名可能会随版本变化，请以实际生成的文件名为准。_

4.  **配置环境**：
    在部署目录下创建配置文件（默认为 `.env`）：

    ```bash
    # 创建配置文件
    touch .env
    ```

    编辑配置文件，以 .env.example 为模版，填入生产环境配置。

5.  **运行服务**。

    安装完成后，系统会自动注册 `challenge-server` 命令。你可以直接运行：

    ```bash
    # 启动服务 (默认加载当前目录下的 .env)
    challenge-server

    # 如果使用自定义配置文件名
    ENV_FILE=.env.prod challenge-server
    ```
