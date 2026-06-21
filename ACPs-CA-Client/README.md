# ACPs ATR CA 客户端（Python 版）

本仓库包含了基于ATR CA 客户端的 Python 实现框架。

## 项目结构

- `acps_ca_client/`：源码包
  - `cli.py`：CLI 入口及子命令
  - `config.py`：配置加载器
  - `keys.py`：密钥与 CSR 生成辅助
  - `acme.py`：ACME 协议工具
- `ca-client.conf.example`：配置模板

## 开发过程

1. **准备环境**：

创建python虚拟环境，安装poetry，安装项目依赖：

```bash
python3 -m venv venv        # 创建虚拟环境
source venv/bin/activate    # 激活虚拟环境
pip install poetry      # 安装poetry
poetry install          # 安装项目依赖
```

2. **配置**：

复制示例配置文件并进行编辑：

```bash
cp ca-client.conf.example ca-client.conf
# 用你的设置编辑 ca-client.conf
```

3. **开发调试**：

修改源代码，执行命令进行调试。比如，根据 AIC 申请 CA 证书：

```bash
ca-client new-cert --aic 1.2.156.3088.xxxx.xxxx.xxxxx.xxxxx.1.xxx
```

4. **打包**：

```bash
poetry build
```

打包完成后，生成的 wheel 文件位于 `dist/` 目录下。

可以将此 wheel 文件部署到目标环境，并使用 pip 安装：

```bash
pip install acps_ca_client-2.0.0-py3-none-any.whl
```

## 参数说明及使用示例

具体内容请参见 `USAGE.md` 文档。
