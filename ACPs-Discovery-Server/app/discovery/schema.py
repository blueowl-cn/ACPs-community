"""
发现模块的 Pydantic 模式定义。

此模块定义用于 Agent 发现 API 端点中
请求/响应验证的数据模式。
"""

from datetime import datetime
from typing import List, Optional, Dict, Any, Union, Literal

from pydantic import BaseModel, Field


class ProviderSchema(BaseModel):
    """Agent 提供者信息"""

    countryCode: Optional[str] = Field(
        default="CN",
        description="智能体提供者的国家或地区代码，符合 ISO 3166-1 alpha-2 标准。默认值为 'CN'。",
    )
    organization: str = Field(
        ...,
        description="智能体提供者的组织名称，通常为公司、大学或研究机构等顶级组织。",
    )
    department: Optional[str] = Field(
        default=None,
        description="智能体提供者的具体部门或院系名称，提供更精确的组织结构信息。",
    )
    url: str = Field(
        ...,
        description="智能体提供者的官方网站或相关文档的 URL 地址。",
    )
    license: str = Field(
        ...,
        description=(
            "智能体提供者的法律备案信息或许可证号，用于合规性验证。"
            "通常为 URL 对应网站的ICP备案号或其他资质证明。"
        ),
    )



class MutualTLSSecurityScheme(BaseModel):
    type: Literal["mutualTLS"] = Field(description="安全方案类型")
    description: Optional[str] = Field(None, description="安全方案描述")
    x_caChallengeBaseUrl: str = Field(
        ..., alias="x-caChallengeBaseUrl", description="CA挑战基础URL"
    )


class OpenIdConnectSecurityScheme(BaseModel):
    type: Literal["openIdConnect"] = Field(description="安全方案类型")
    description: Optional[str] = Field(None, description="安全方案描述")
    openIdConnectUrl: str = Field(..., description="OpenID Connect配置URL")

SecuritySchemeSchema = Union[MutualTLSSecurityScheme, OpenIdConnectSecurityScheme]

class EndPointSchema(BaseModel):
    """Agent 端点信息"""

    url: str = Field(..., description="端点URL")
    transport: str = Field(..., description="传输协议，如HTTP_JSON、JSONRPC等")
    security: Optional[List[Dict[str, List[str]]]] = Field(
        None, description="安全认证配置"
    )




class CapabilitiesSchema(BaseModel):
    """Agent 技术能力"""

    streaming: bool = Field(..., description="是否支持流式处理")
    notification: bool = Field(..., description="是否支持通知")
    messageQueue: List[str] = Field(
        default_factory=list, description="支持的消息队列类型"
    )


class SkillSchema(BaseModel):
    """Agent 技能"""

    id: str = Field(..., description="技能唯一标识符")
    name: str = Field(..., description="技能名称")
    description: str = Field(..., description="技能描述")
    version: str = Field(..., description="技能版本")
    tags: List[str] = Field(..., description="技能标签")
    examples: Optional[List[str]] = Field(None, description="使用示例")
    inputModes: Optional[List[str]] = Field(None, description="支持的输入模式")
    outputModes: Optional[List[str]] = Field(None, description="支持的输出模式")


class ACSSchema(BaseModel):
    """Agent 能力规范 (ACS)"""

    aic: str = Field(..., description="Agent 标识码")
    active: bool = Field(..., description="Agent 是否激活")
    lastModifiedTime: str = Field(..., description="最后修改时间戳 (ISO 8601)")
    protocolVersion: str = Field(..., description="协议版本")
    name: str = Field(..., description="Agent 名称")
    description: str = Field(..., description="Agent 描述")
    version: str = Field(..., description="Agent 版本")
    iconUrl: Optional[str] = Field(None, description="图标URL")
    documentationUrl: Optional[str] = Field(None, description="文档URL")
    webAppUrl: Optional[str] = Field(None, description="Web应用URL")
    provider: ProviderSchema = Field(..., description="提供者信息")
    securitySchemes: Dict[str, SecuritySchemeSchema] = Field(
        default_factory=dict, description="安全方案配置"
    )
    endPoints: Optional[List[EndPointSchema]] = Field(
        default_factory=list,
        description="服务端点列表（可为空）"
    )
    capabilities: CapabilitiesSchema = Field(..., description="技术能力")
    defaultInputModes: List[str] = Field(..., description="默认支持的输入模式")
    defaultOutputModes: List[str] = Field(..., description="默认支持的输出模式")
    skills: List[SkillSchema] = Field(..., min_length=1, description="技能列表")


class AgentSchema(BaseModel):
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
        description="Agent 技能 ID - 适配新结构",
        alias="skill_id"  # 保持与旧API的兼容性
    )
    ranking: Optional[int] = Field(
        default=None,
        description="排名",
    )
    memo: str = Field(
        default="",
        description="拓展信息",
    )


class DiscoveryRequest(BaseModel):
    """发现请求的模式定义。"""

    query: str = Field(
        ...,
        description="用于 Agent 发现的自然语言查询",
        min_length=1,
        max_length=1000,
        examples=["我需要北京餐厅推荐的帮助"],
    )
    limit: Optional[int] = Field(
        default=5, description="返回的最大 Agent 数量", ge=1, le=10
    )


class DiscoveryResponse(BaseModel):
    """发现响应的模式定义。"""

    query: str = Field(..., description="原始查询")
    agents: List[AgentSchema] = Field(
        default_factory=list, description="匹配的 Agent 列表"
    )

    class Config:
        """Pydantic 配置。"""

        json_encoders = {datetime: lambda v: v.isoformat()}
