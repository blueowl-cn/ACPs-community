# AIP SDK — 智能体交互协议 (Agent Interaction Protocol) v2

AIP SDK 提供了 AIP v2 协议的 Python 实现，支持智能体之间通过 **RPC 模式**和**群组模式 (Group Mode)** 进行任务协作与消息通信。

---

## 目录结构

```
aip/
├── __init__.py             # 公共导出模块
├── aip_base_model.py       # AIP v2 基础数据模型
├── aip_rpc_model.py        # RPC 模式数据模型
├── aip_stream_model.py     # 流式传输数据模型
├── aip_rpc_client.py       # RPC 客户端
├── aip_group_model.py      # 群组模式数据模型
├── aip_group_leader.py     # 群组模式 Leader 端实现
├── aip_group_partner.py    # 群组模式 Partner 端实现
├── mtls_config.py          # mTLS 双向认证配置
├── README.md               # 本文件
└── TUTORIAL.md             # 使用教程与示例
```

---

## 功能概览

### 两种通信模式

| 模式         | 适用场景                         | 传输方式                          | 核心类                                |
| ------------ | -------------------------------- | --------------------------------- | ------------------------------------- |
| **RPC 模式** | 1:1 Leader-Partner 请求/响应交互 | HTTP(S) + JSON-RPC                | `AipRpcClient`                        |
| **群组模式** | 1:N Leader 协调多 Partner 协作   | RabbitMQ (AMQP) + Fanout Exchange | `GroupLeader`, `GroupPartnerMqClient` |

### 任务生命周期

任务在 Leader 和 Partner 之间按照以下状态流转：

```
start → accepted → working → awaiting-input / awaiting-completion → completed
                           → failed / canceled / rejected
```

- **Leader** 通过 `TaskCommand` 发起和控制任务（start, continue, complete, cancel, get）
- **Partner** 通过 `TaskResult` 返回任务状态和产出物

### 群组协作流程

1. Leader 创建群组（`create_group` / `create_group_session`）
2. Leader 通过 RPC 邀请 Partner 加入群组（`invite_partner`）
3. Partner 接收邀请、连接 RabbitMQ、绑定 Exchange（`join_group`）
4. Leader 向群组发布任务命令，通过 `mentions` 指定目标 Partner
5. Partner 处理任务并通过 MQ 广播状态更新和产出物
6. Leader 通过管理命令进行成员管理（状态查询、静音、踢出）
7. 任务完成后，Leader 解散群组（`dissolve_group`）

### 安全通信

通过 `MTLSConfig` 支持 mTLS 双向认证，确保智能体之间的通信安全，适用于 RPC 模式的 HTTPS 连接。

---

## 示例与教程

详细的使用示例请参阅 [TUTORIAL.md](TUTORIAL.md)。
