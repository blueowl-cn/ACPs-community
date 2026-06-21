# Agent Discovery Server

- 提供 Agent 发现的 API 服务。输入自然语言的请求，返回以Agent的skill为主体的rank列表。
- 与 Registry Server 配合使用，Registry Server 负责存储和管理 Agent 的 ACS 信息，Agent Discovery Server 负责根据用户的自然语言请求进行匹配和推荐。Discovery 需要与 Registry 保持 Agent 的 ACS 信息同步，使用 DRC（Discovery Registry Coordination）协议实现。

## 技术栈

- **Python 版本**: 3.13
- **Web 框架**: FastAPI
- **数据验证与解析**: Pydantic V2 （避免使用 V1 版本的风格）
- **ORM**: SQLModel/SQLAlchemy
- **数据库**: PostgreSQL
- **数据库结构同步**: Alembic
- **外部大语言模型 API**: DASHSCOPE API
- **Embedding API**: OPENAI API


## 开发环境搭建

首先，确保已经安装了 Python，推荐使用 Python 3.13 版本。可以从Python 官方网站下载并安装适合你操作系统的 Python 版本。

0. 安装 ACPs SDK（前置依赖）

本项目基于 `ACPs SDK` 开发，需在本地提前获取该 SDK。

请先克隆 SDK 仓库：

```bash
git clone [Repository-URL]
```

1. 克隆代码库

```bash
git clone [Repository-URL]
cd [代码库本地目录]
```
参考目录结构
```
project/
├── acps-sdk/
└── discovery-server/
```
sdk仅下载到本地使用参考目录结构即可，无需其他操作。

2. 创建虚拟环境并安装依赖

```bash
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，修改数据库相关配置，以及：
# 1. 至少配置 OPENAI_API_KEY (用于 Embedding) 以及 其他 LLM 的 Key
# 2. 配置 OPENAI_BASE_URL（如果使用非官方端点）
```

4. 创建数据库结构

使用 Alembic 进行数据库迁移：

```bash
#进行此操作前确保已经正确配置了.env文件中的数据库相关参数
alembic upgrade head    
```

5. 启动服务

```bash
#前台启动服务
python main.py

#使用提供的脚本在后台启动服务，并将日志输出到./logs 文件夹：
chmod +x start.sh   # 赋予执行权限（仅需一次）
./start.sh          # 启动服务
```
假设你在`.env`中配置的服务器端口为 8005，那么服务器将在 http://localhost:8005 启动，API 文档可在 http://localhost:8005/docs 查看。


6. 停止服务

```bash
chmod +x stop.sh    # 赋予执行权限（仅需一次）
./stop.sh           # 停止服务
```

7. 可能出现的问题

```python

"error_msg": "Failed to discover: Database query failed: Failed to enhanced_discover: 'skills'"

#当出现以上报错时，是因为过滤条件过于严苛或过滤条件矛盾导致下面的方法没能从数据库中获取到智能体
async def _discovery_agents_async(self, query: str, limit: int, filters: DiscoveryFilters = None) -> Tuple[List[DiscoveryAgentSkill], Dict, str]:
```






## 关键配置调整

### 1. 优化配置

**位置：** `optimization_config` 字典
**用途：** 控制系统功能开关和性能参数

```python
# 修改优化设置 - 影响性能、功能和成本
discovery_system.update_optimization_config(
    # 核心功能开关
    use_semantic_matching=True, # 是否启用语义匹配 (需配置 Embedding API)
    prefilter_enabled=True,      # 是否启用预筛选 (推荐开启以节省 LLM 成本)
    
    # 性能/成本参数
    max_agents_to_llm=20,        # 发送给 LLM 进行精细评估的最大候选技能数量
    llm_return_multiplier=2,     # LLM 返回数量倍数 (例如 k=5, LLM 返回 10 个)
    
    # 评分权重 (会叠加到 LLM 基础得分上)
    keyword_weight=10,           # 关键词预筛选阶段的权重
    semantic_weight=25,          # 语义匹配得分的最终加权系数 (25 表示 25%)
)
```

## 关键代码位置

### 1. 系统初始化流程

```python

# 初始化系统
discovery_system = EnhancedAgentDiscoverySystem(api_key="your_key")

# 配置系统
discovery_system.update_scoring_config()
discovery_system.update_optimization_config()

# 加载智能体数据
discovery_system.load_agents(your_agent_list)

```

### 2. 智能体发现调用

**位置：** `discover_skills_enhanced()`

```python

# 技能级别发现（更精确）
skill_results = discovery_system.discover_skills(
    task_description="你的任务描述",
    k=5
)
```


### 3. LLM提示词模板修改

**位置：** `_create_skill_evaluation_prompt_enhanced` 方法

关键修改点：
```python
# 可在该方法中找到这些部分进行修改：

# 评估因素描述
"""
请分析每个技能与任务的匹配程度，考虑以下因素:
1. 技能功能匹配度 - 技能提供的功能是否满足任务具体需求
2. 数据类型兼容性 - 技能的输入输出类型是否与任务数据兼容
3. 技能精确性 - 技能描述与任务需求的精确匹配程度
4. 技术栈适配 - 技能的技术实现是否适合任务场景
5. 可用性和稳定性 - 所属Agent的状态和技能的成熟度
6. 易用性 - 技能的使用复杂度和文档完整性
"""

# 详细输出要求
"""
要求:
1. 专注于技能级别的精确匹配，而不是Agent级别的泛化能力
2. 评分范围0-1，保留2位小数
3. 按总分从高到低排序技能
4. **只返回最匹配的 {llm_return_count} 个技能的详细信息**
5. 推荐理由要基于技能的具体功能特性
6. 确保使用正确的AIC和技能ID格式
7. 分析数据流的兼容性和处理效率
"""
```



### 4. 预筛选评分算法

**位置：** `_prefilter_skills` 方法

```python
# 在该方法中可以修改预筛选的评分逻辑：
 def _calculate_skill_prefilter_score(self, skill: Dict, task_keywords: set, task_requirements: Optional[Dict] = None) -> float:

```

### 5. 接收数据处理

**位置：** `app/sync/client/apply` 方法

```python
#可以在此方法中修改数据接收后的处理
    async def apply(self, envelope: Envelope):
        """
        将 envelope 的数据应用到本地状态和数据库。

        Args:
            envelope: 要应用的 Envelope 对象
        """
        # 幂等性检查：跳过已经处理过的旧版本
        if not self.should_apply_envelope(envelope):
            current_version = self.state.object_versions.get(envelope.type, {}).get(
                envelope.id, 0
            )
            logger.debug(
                f"Skipping envelope {envelope.type}:{envelope.id} v{envelope.version} "
                f"(current: v{current_version})"
            )
            return

        # 类型过滤：仅处理支持的数据类型
        if envelope.type != "acs":
            logger.debug(f"Skipping non-acs type: {envelope.type}")
            return

        # 确保对象版本追踪结构存在
        if envelope.type not in self.state.object_versions:
            self.state.object_versions[envelope.type] = {}

        # 执行数据库操作
        await self._apply_to_database(envelope)

        # TODO: 可在此处添加其他针对每一条数据的处理功能，例如：
        # - 更新搜索索引
        # - 调用外部服务
        # - 记录审计日志
        # - 发送通知或事件
        # await self._process_additional_actions(envelope)

        # 更新内存中的版本追踪状态（仅在上述各个操作成功后执行）
        if envelope.op == OperationType.DELETE:
            # 对于删除操作，从版本跟踪中移除对象
            if envelope.id in self.state.object_versions[envelope.type]:
                del self.state.object_versions[envelope.type][envelope.id]
                logger.debug(
                    f"Removed from version tracking: {envelope.type}:{envelope.id}"
                )
        else:
            # 对于upsert操作，更新版本跟踪
            self.state.object_versions[envelope.type][envelope.id] = envelope.version

```
