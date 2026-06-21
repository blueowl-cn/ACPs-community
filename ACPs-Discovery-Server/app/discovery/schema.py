"""
发现模块的 Pydantic 模式定义。

此模块定义用于 Agent 发现 API 端点中
请求/响应验证的数据模式。
"""
from acps_sdk.adp import (
    ErrorDetail,
    DiscoveryAgentSkill,
    DiscoveryAgentGroup,
    DiscoveryRoute,
    DiscoveryResult,
    DiscoveryResponse,
    DiscoveryFilter,
    FilterCondition,
    FilterOperator,
)
from datetime import datetime
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, conint, ConfigDict
from typing import List, Dict, Any, Optional, Literal


class DiscoveryContext(BaseModel):
    """
    描述请求侧可选的会话与用户背景切片，供发现服务器理解意图。
    """
    conversationId: str = Field(..., description="客户端自定义的会话 ID，用于关联多轮查询")
    recentTurns: List[str] = Field('', description="近期对话摘要或要点")
    userProfile: Optional[Dict[str, Any]] = Field(..., description='匿名化用户画像片段，如地理位置、预算偏好等')
    metadata: Optional[Dict[str, Any]] = Field(..., description='额外的上下文扩展，供上下游约定使用')


# ---------------------------------------------------------------------------
# Legacy internal filter model — kept for DB query layer compatibility
# ---------------------------------------------------------------------------

class DiscoveryCapabilityFlags(BaseModel):
    """AgentCapabilities 的过滤项（内部使用）"""
    streaming: Optional[bool] = Field(None, description='是否需要流式响应能力')
    notification: Optional[bool] = Field(None, description='是否需要异步通知能力')
    messageQueue: Optional[List[str]] = Field(None, description='必须支持的消息队列协议版本')
    messageQueue_reject: Optional[List[str]] = Field(None, description='必须排除的消息队列协议版本')


class DiscoveryFilters(BaseModel):
    """
    内部使用的固定字段过滤器（供数据库查询层使用）。
    外部请求统一使用 DiscoveryFilter（通用条件数组格式），
    通过 convert_filter_to_legacy() 转换后传入此类。
    """
    protocolVersions: Optional[List[str]] = Field(None)
    protocolVersions_reject: Optional[List[str]] = Field(None)
    transports: Optional[List[str]] = Field(None)
    transports_reject: Optional[List[str]] = Field(None)
    requiredSecuritySchemes: Optional[List[str]] = Field(None)
    requiredSecuritySchemes_reject: Optional[List[str]] = Field(None)
    skillTags: Optional[List[str]] = Field(None)
    skillTags_reject: Optional[List[str]] = Field(None)
    skillIds: Optional[List[str]] = Field(None)
    skillIds_reject: Optional[List[str]] = Field(None)
    providerCountryCodes: Optional[List[str]] = Field(None)
    providerCountryCodes_reject: Optional[List[str]] = Field(None)
    providerOrganizations: Optional[List[str]] = Field(None)
    providerOrganizations_reject: Optional[List[str]] = Field(None)
    providerLicenses: Optional[List[str]] = Field(None)
    providerLicenses_reject: Optional[List[str]] = Field(None)
    inputModes: Optional[List[str]] = Field(None)
    inputModes_reject: Optional[List[str]] = Field(None)
    outputModes: Optional[List[str]] = Field(None)
    outputModes_reject: Optional[List[str]] = Field(None)
    isActive: Optional[bool] = Field(None)
    aic: Optional[str] = Field(None)
    aicStartWith: Optional[str] = Field(None)
    entityUserId: Optional[str] = Field(None)
    hasEndpoints: Optional[bool] = Field(None)
    hasWebAppUrl: Optional[bool] = Field(None)
    capabilities: Optional[DiscoveryCapabilityFlags] = Field(None)


# ---------------------------------------------------------------------------
# Filter conversion: DiscoveryFilter (new) → DiscoveryFilters (legacy)
# ---------------------------------------------------------------------------

def _collect_conditions(filter_obj: DiscoveryFilter, out: list) -> None:
    """递归收集 DiscoveryFilter 中所有 FilterCondition，忽略 logic 层级（统一 AND 处理）。"""
    if filter_obj.conditions:
        out.extend(filter_obj.conditions)
    if filter_obj.groups:
        for group in filter_obj.groups:
            _collect_conditions(group, out)


def _as_list(value: Any) -> List:
    """将标量或列表统一转换为列表。"""
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def convert_filter_to_legacy(filter_obj: Optional[DiscoveryFilter]) -> Optional[DiscoveryFilters]:
    """
    (兼容性实现)将新版通用条件数组格式 (DiscoveryFilter) 转换为内部固定字段格式 (DiscoveryFilters)。

    转换规则：
    - 仅映射当前 DB 层已支持的字段/运算符组合，不支持的条件静默丢弃。
    - 嵌套 groups 中的条件与顶层条件一同展开，logic 层级暂不区分（全部视为 AND）。
    - OR / NOT logic 的语义无法完整映射，仅做尽力转换。

    Args:
        filter_obj: 新版 DiscoveryFilter，为 None 时返回 None。

    Returns:
        DiscoveryFilters 实例，或 None（当 filter_obj 为 None）。
    """
    if filter_obj is None:
        return None

    conditions: List[FilterCondition] = []
    _collect_conditions(filter_obj, conditions)

    if not conditions:
        return None

    legacy = DiscoveryFilters()

    for cond in conditions:
        field = cond.field
        op = cond.op
        value = cond.value

        # ── active ──
        if field == "active":
            if op in (FilterOperator.EQ, FilterOperator.NE):
                legacy.isActive = bool(value) if op == FilterOperator.EQ else not bool(value)

        # ── protocolVersion ──
        elif field == "protocolVersion":
            if op == FilterOperator.EQ:
                legacy.protocolVersions = [value]
            elif op == FilterOperator.IN:
                legacy.protocolVersions = _as_list(value)
            elif op == FilterOperator.NIN:
                legacy.protocolVersions_reject = _as_list(value)
            elif op == FilterOperator.NE:
                legacy.protocolVersions_reject = [value]

        # ── endPoints.transport ──
        elif field == "endPoints.transport":
            if op == FilterOperator.EQ:
                legacy.transports = [value]
            elif op == FilterOperator.IN:
                legacy.transports = _as_list(value)
            elif op == FilterOperator.NIN:
                legacy.transports_reject = _as_list(value)
            elif op == FilterOperator.NE:
                legacy.transports_reject = [value]

        # ── securitySchemes ──
        elif field == "securitySchemes":
            if op == FilterOperator.HAS_KEY:
                legacy.requiredSecuritySchemes = [value]
            elif op in (FilterOperator.HAS_ANY_KEY, FilterOperator.HAS_ALL_KEYS):
                legacy.requiredSecuritySchemes = _as_list(value)
            elif op == FilterOperator.HAS_NO_KEY:
                legacy.requiredSecuritySchemes_reject = _as_list(value)

        # ── skills.tags ──
        elif field == "skills.tags":
            if op == FilterOperator.ANY_OF:
                legacy.skillTags = _as_list(value)
            elif op == FilterOperator.ALL_OF:
                legacy.skillTags = _as_list(value)
            elif op == FilterOperator.NONE_OF:
                legacy.skillTags_reject = _as_list(value)

        # ── skills.id ──
        elif field == "skills.id":
            if op == FilterOperator.EQ:
                legacy.skillIds = [value]
            elif op == FilterOperator.IN:
                legacy.skillIds = _as_list(value)
            elif op == FilterOperator.NIN:
                legacy.skillIds_reject = _as_list(value)
            elif op == FilterOperator.NE:
                legacy.skillIds_reject = [value]

        # ── provider.countryCode ──
        elif field == "provider.countryCode":
            if op == FilterOperator.EQ:
                legacy.providerCountryCodes = [value]
            elif op == FilterOperator.IN:
                legacy.providerCountryCodes = _as_list(value)
            elif op == FilterOperator.NIN:
                legacy.providerCountryCodes_reject = _as_list(value)
            elif op == FilterOperator.NE:
                legacy.providerCountryCodes_reject = [value]

        # ── provider.organization ──
        elif field == "provider.organization":
            if op in (FilterOperator.EQ, FilterOperator.CONTAINS,
                      FilterOperator.STARTS_WITH, FilterOperator.CONTAINS_CS):
                legacy.providerOrganizations = [value]
            elif op == FilterOperator.IN:
                legacy.providerOrganizations = _as_list(value)
            elif op == FilterOperator.NIN:
                legacy.providerOrganizations_reject = _as_list(value)
            elif op == FilterOperator.NE:
                legacy.providerOrganizations_reject = [value]

        # ── provider.license ──
        elif field == "provider.license":
            if op in (FilterOperator.EQ, FilterOperator.CONTAINS):
                legacy.providerLicenses = [value]
            elif op == FilterOperator.IN:
                legacy.providerLicenses = _as_list(value)
            elif op == FilterOperator.NIN:
                legacy.providerLicenses_reject = _as_list(value)

        # ── defaultInputModes / skills.inputModes ──
        elif field in ("defaultInputModes", "skills.inputModes"):
            if op in (FilterOperator.ANY_OF, FilterOperator.ALL_OF):
                legacy.inputModes = _as_list(value)
            elif op == FilterOperator.NONE_OF:
                legacy.inputModes_reject = _as_list(value)

        # ── defaultOutputModes / skills.outputModes ──
        elif field in ("defaultOutputModes", "skills.outputModes"):
            if op in (FilterOperator.ANY_OF, FilterOperator.ALL_OF):
                legacy.outputModes = _as_list(value)
            elif op == FilterOperator.NONE_OF:
                legacy.outputModes_reject = _as_list(value)

        # ── aic ──
        elif field == "aic":
            if op == FilterOperator.EQ:
                legacy.aic = value
            elif op == FilterOperator.STARTS_WITH:
                legacy.aicStartWith = value
            elif op == FilterOperator.IN:
                # 仅取第一个（尽力转换）
                lst = _as_list(value)
                if lst:
                    legacy.aic = lst[0]

        # ── entityUserId ──
        elif field == "entityUserId":
            if op == FilterOperator.EQ:
                legacy.entityUserId = value

        # ── endPoints（存在性） ──
        elif field == "endPoints":
            if op == FilterOperator.EXISTS:
                legacy.hasEndpoints = bool(value)

        # ── webAppUrl ──
        elif field == "webAppUrl":
            if op == FilterOperator.EXISTS:
                legacy.hasWebAppUrl = bool(value)

        # ── capabilities.streaming ──
        elif field == "capabilities.streaming":
            if op == FilterOperator.EQ:
                if legacy.capabilities is None:
                    legacy.capabilities = DiscoveryCapabilityFlags()
                legacy.capabilities.streaming = bool(value)

        # ── capabilities.notification ──
        elif field == "capabilities.notification":
            if op == FilterOperator.EQ:
                if legacy.capabilities is None:
                    legacy.capabilities = DiscoveryCapabilityFlags()
                legacy.capabilities.notification = bool(value)

        # ── capabilities.messageQueue ──
        elif field == "capabilities.messageQueue":
            if op == FilterOperator.ANY_OF:
                if legacy.capabilities is None:
                    legacy.capabilities = DiscoveryCapabilityFlags()
                legacy.capabilities.messageQueue = _as_list(value)
            elif op == FilterOperator.NONE_OF:
                if legacy.capabilities is None:
                    legacy.capabilities = DiscoveryCapabilityFlags()
                legacy.capabilities.messageQueue_reject = _as_list(value)

        # 其余字段/运算符：静默丢弃（暂不支持）

    return legacy


# ---------------------------------------------------------------------------
# Public request model
# ---------------------------------------------------------------------------

class DiscoveryRequest(BaseModel):
    """
    客户端发起的发现请求模型。
    """
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "type": "explicit",
                "query": "获取用户画像的帮助",
                "limit": 5
            }
        }
    )

    type: Literal['explicit', 'exploratory', 'trending', 'filtered'] = Field(
        'explicit',
        description="查询类型: 'explicit'-明确查询, 'exploratory'-探索性查询, 'trending'-热门查询, 'filtered'-过滤查询"
    )
    query: Optional[str] = Field(
        None,
        description="用于匹配智能体能力描述的自然语言文本。在 'explicit' 和 'exploratory' 类型下通常为必需。"
    )
    context: Optional[DiscoveryContext] = Field(
        None,
        description="包含会话 ID 等信息的上下文对象。"
    )
    limit: conint(ge=1, le=50) = Field(
        5,
        description="期望返回的最大智能体数量，限制在 1 到 50 之间。"
    )
    filter: Optional[DiscoveryFilter] = Field(
        None,
        description=(
            "结构化过滤条件（通用条件数组格式）。"
            "采用 { field, op, value } 结构，支持 AND/OR/NOT 逻辑组合。"
            "当前服务仅支持 ACS 字段路径与运算符映射表中列出的组合，不支持的条件将被忽略。"
        )
    )
    forwardDepthLimit: conint(ge=1, le=5) = Field(
        1,
        description="允许的最大转发深度，限制在 1 到 5 之间。"
    )
    forwardFanoutLimit: conint(ge=1, le=5) = Field(
        1,
        description="允许的最大扇出（fan-out）广度，限制在 1 到 5 之间。"
    )
    forwardFanoutRemaining: conint(ge=0, le=5) = Field(
        0,
        description='当前分支尚可消耗的 fan-out 额度'
    )
    forwardChain: Optional[List[str]] = Field(default_factory=list, description='转发追踪链')
    forwardTrustedServers: Optional[List[str]] = Field(default_factory=list, description='信任的发现服务器 AIC 列表')
    forwardSignatures: Optional[List[str]] = Field(default_factory=list, description='转发发现服务器的数字签名')
    forwardEachTimeoutMs: Optional[int] = Field(10000, description='每次转发的请求超时，单位毫秒')
    forwardTotalTimeoutMs: Optional[int] = Field(60000, description='转发请求的总超时')


# ---------------------------------------------------------------------------
# V1 compatibility models (unchanged)
# ---------------------------------------------------------------------------

class ProviderSchemaV1(BaseModel):
    """Agent 提供者信息 (V1)"""
    countryCode: Optional[str] = Field(default="CN")
    organization: str = Field(...)
    department: Optional[str] = Field(default=None)
    url: str = Field(...)
    license: str = Field(...)


class AgentSchemaV1(BaseModel):
    """V1 版本的 Agent Schema"""
    acs: Any = Field(
        ...,
        description="Agent 能力规范 (ACS) 的原始 JSON 数据",
    )
    skill_description: str = Field(
        default="",
        description="发现得到的技能描述",
    )
    skill_id: Optional[str] = Field(
        default=None,
        description="Agent 技能 ID",
    )
    ranking: Optional[int] = Field(
        default=None,
        description="排名",
    )
    memo: str = Field(
        default="",
        description="拓展信息",
    )


class DiscoveryRequestV1(BaseModel):
    """V1 发现请求的模式定义"""
    query: str = Field(
        ...,
        description="用于 Agent 发现的自然语言查询",
        min_length=1,
        max_length=1000,
    )
    limit: Optional[int] = Field(
        default=5, 
        description="返回的最大 Agent 数量", 
        ge=1, 
        le=10
    )
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "我需要下棋的帮助",
                "limit": 5
            }
        }
    )       


class DiscoveryResponseV1(BaseModel):
    """V1 发现响应的模式定义"""
    query: str = Field(..., description="原始查询")
    agents: List[AgentSchemaV1] = Field(
        default_factory=list, 
        description="匹配的 Agent 列表"
    )
    reasoning: Optional[str] = Field(
        default=None,
        description="大模型的思考过程总结"
    )

    class Config:
        """Pydantic 配置"""
        json_encoders = {datetime: lambda v: v.isoformat()}