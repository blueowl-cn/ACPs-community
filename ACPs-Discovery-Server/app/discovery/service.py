import json
import os
from pathlib import Path
from typing import List, Optional, Dict
import logging
from fastapi import status
from sqlmodel import select, Boolean
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.sync.model import Agent
from app.discovery.exception import (
    DiscoveryError,
    DiscoveryException,
)
from app.discovery.schema import (
    DiscoveryRequest,
    DiscoveryResponse,
    DiscoveryAgentSkill,
    DiscoveryFilters,
    convert_filter_to_legacy,
)
from app.discovery.singleton import AgentDiscovery
import time
import asyncio
from functools import wraps
from typing import Callable, Any, Awaitable, Tuple
from sqlalchemy import or_
from sqlalchemy import cast
from sqlalchemy.dialects.postgresql import JSONPATH 

# 定义类型别名
SyncFunc = Callable[..., Any]
AsyncFunc = Callable[..., Awaitable[Any]]
Func = Callable[..., Any]
WrappedReturn = Tuple[Any, float]


def time_it_return_ms(func: Func) -> Callable[..., Awaitable[WrappedReturn]]:
    @wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> WrappedReturn:
        start_time = time.perf_counter()
        result = await func(*args, **kwargs)
        end_time = time.perf_counter()
        return result, (end_time - start_time) * 1000

    @wraps(func)
    async def sync_wrapper_async_return(*args: Any, **kwargs: Any) -> WrappedReturn:
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()
        return result, (end_time - start_time) * 1000

    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper_async_return


logger = logging.getLogger(__name__)


class DiscoveryService:
    """Agent 发现功能的服务类。"""

    def __init__(self):
        """初始化发现服务。"""
        pass

    @time_it_return_ms
    async def discover_agents_async(
        self, request: DiscoveryRequest
    ) -> Tuple[Tuple[List[DiscoveryAgentSkill], Dict, str], float]:
        """
        基于自然语言查询发现 Agent（异步版本）。

        Returns:
            ((agents_list, acs_dict, reasoning), duration_ms)
        """
        try:
            # 将新版 DiscoveryFilter 转换为内部 DiscoveryFilters
            legacy_filters = convert_filter_to_legacy(request.filter)

            all_agents, acs_dict, reasoning = await self._discovery_agents_async(
                request.query, limit=request.limit, filters=legacy_filters
            )
            return all_agents, acs_dict, reasoning

        except Exception as e:
            raise DiscoveryException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_name=DiscoveryError.DISCOVERY_FAIL,
                error_msg=f"Failed to discover: {str(e)}",
                input_params={"query": request.query},
            )

    async def _search_agents_async(self, query: str) -> List[DiscoveryAgentSkill]:
        agents_schema = []
        try:
            async with AsyncSessionLocal() as session:
                stmt = (
                    select(Agent)
                    .where(Agent.acs["description"].astext.like(f"%{query}%"))
                    .order_by(Agent.seq.desc())
                    .limit(3)
                )
                result = await session.execute(stmt)
                agents = result.scalars().all()
                for agent in agents:
                    agent_schema = DiscoveryAgentSkill(
                        aic=agent.aic,
                        skillId=None,
                        ranking=None,
                        memo=None
                    )
                    agents_schema.append(agent_schema)
        except Exception as e:
            raise DiscoveryException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_name=DiscoveryError.DATABASE_ERROR,
                error_msg=f"Database query failed: {e}",
                input_params={"query": query},
            )
        return agents_schema
    
    async def _discovery_agents_async(self, query: str, limit: int, filters: DiscoveryFilters = None) -> Tuple[List[DiscoveryAgentSkill], Dict, str]:
        """
        使用发现智能体方法搜索 Agent。

        Args:
            query: 搜索查询字符串
            limit: 返回的agents数量限制
            filters: 过滤条件

        Returns:
            (匹配的 AgentSchema 列表, acs_dict, reasoning)
        """
        agents_schema = []
        reasoning = ""

        try:
            # 获取数据库中的 Agent
            async with AsyncSessionLocal() as session:
                # 构建基础查询
                stmt = select(Agent)
                
                # 应用过滤条件
                where_clauses = self._build_filter_clauses(filters)
                for clause in where_clauses:
                    stmt = stmt.where(clause)
                
                result = await session.execute(stmt)
                agents = result.scalars().all()
                agents_data = [agent.acs for agent in agents]

            enhanced_button = True
            if enhanced_button:
                agents_schema, acs_dict, reasoning = await self._enhanced_search_agents(
                    query, agents_data, limit
                )
            else:
                # 直接转换为 AgentSchema（取前limit个）
                for agent in agents_data[:limit]:
                    agent_schema = DiscoveryAgentSkill(
                        aic=None, skillId=None, ranking=None, memo=""
                    )
                    agents_schema.append(agent_schema)
                acs_dict = {}
                reasoning = ""

        except Exception as e:
            raise DiscoveryException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_name=DiscoveryError.DATABASE_ERROR,
                error_msg=f"Database query failed: {e}",
                input_params={"query": query},
            )
        return agents_schema, acs_dict, reasoning

    def _build_filter_clauses(self, filters: Optional[DiscoveryFilters]):
        """
        构建SQLAlchemy过滤条件列表
        """
        from sqlalchemy import and_, or_, not_, func
        from sqlmodel import Boolean

        clauses = []
        
        # ========== 默认条件处理 ==========
        # 当 filters 为 None 或者 hasEndpoints 和 hasWebAppUrl 都未设置时，应用默认条件
        if filters is None or (filters.hasEndpoints is None and filters.hasWebAppUrl is None):
            clauses.append(
                or_(
                    func.jsonb_array_length(Agent.acs["endPoints"]) > 0,
                    and_(
                        Agent.acs["webAppUrl"].is_not(None),
                        Agent.acs["webAppUrl"].astext != "null",
                        Agent.acs["webAppUrl"].astext != ""
                    )
                )
            )
        
        # ========== isActive 默认条件 ==========
        # 当 filters 为 None 或者 isActive 未设置时，默认只查询 active 的
        if filters is None or filters.isActive is None:
            clauses.append(
                or_(
                    Agent.acs["active"].astext.cast(Boolean) == True,
                    Agent.acs["active"].astext == "true"
                )
            )

        if filters is None:
            return clauses

        # ── 协议版本 ──
        if filters.protocolVersions:
            clauses.append(Agent.acs["protocolVersion"].astext.in_(filters.protocolVersions))
        if filters.protocolVersions_reject:
            clauses.append(not_(Agent.acs["protocolVersion"].astext.in_(filters.protocolVersions_reject)))

        # ── 传输协议 ──
        if filters.transports:
            transport_conditions = [
                func.jsonb_path_exists(
                    Agent.acs,
                    cast(f'$.endPoints[*] ? (@.transport == "{t}")', JSONPATH)
                )
                for t in filters.transports
            ]
            clauses.append(or_(*transport_conditions))

        if filters.transports_reject:
            transport_reject_conditions = [
                not_(func.jsonb_path_exists(
                    Agent.acs,
                    cast(f'$.endPoints[*] ? (@.transport == "{t}")', JSONPATH)
                ))
                for t in filters.transports_reject
            ]
            clauses.append(and_(*transport_reject_conditions))

        # ── 安全方案 ──
        if filters.requiredSecuritySchemes:
            scheme_conditions = [
                func.jsonb_path_exists(
                    Agent.acs,
                    cast(f'$.securitySchemes.{scheme}', JSONPATH)
                )
                for scheme in filters.requiredSecuritySchemes
            ]
            clauses.append(and_(*scheme_conditions))

        if filters.requiredSecuritySchemes_reject:
            scheme_reject_conditions = [
                not_(func.jsonb_path_exists(
                    Agent.acs,
                    cast(f'$.securitySchemes.{scheme}', JSONPATH)
                ))
                for scheme in filters.requiredSecuritySchemes_reject
            ]
            clauses.append(and_(*scheme_reject_conditions))

        # ── 技能 ID ──
        if filters.skillIds:
            skill_id_conditions = [
                func.jsonb_path_exists(
                    Agent.acs,
                    cast(f'$.skills[*] ? (@.id == "{sid}")', JSONPATH)
                )
                for sid in filters.skillIds
            ]
            clauses.append(or_(*skill_id_conditions))

        if filters.skillIds_reject:
            skill_id_reject_conditions = [
                not_(func.jsonb_path_exists(
                    Agent.acs,
                    cast(f'$.skills[*] ? (@.id == "{sid}")', JSONPATH)
                ))
                for sid in filters.skillIds_reject
            ]
            clauses.append(and_(*skill_id_reject_conditions))

        # ── 提供者许可证 ──
        if filters.providerLicenses:
            clauses.append(
                Agent.acs["provider"]["license"].astext.in_(filters.providerLicenses)
            )
        if filters.providerLicenses_reject:
            clauses.append(
                not_(Agent.acs["provider"]["license"].astext.in_(filters.providerLicenses_reject))
            )
        # ── 技能标签 ──
        if filters.skillTags:
            tag_conditions = [
                func.jsonb_path_exists(
                    Agent.acs,
                    cast(f'$.skills[*].tags[*] ? (@ == "{tag}")', JSONPATH)
                )
                for tag in filters.skillTags
            ]
            clauses.append(or_(*tag_conditions))
        if filters.skillTags_reject:
            tag_reject_conditions = [
                not_(func.jsonb_path_exists(
                    Agent.acs,
                    cast(f'$.skills[*].tags[*] ? (@ == "{tag}")', JSONPATH)
                ))
                for tag in filters.skillTags_reject
            ]
            clauses.append(and_(*tag_reject_conditions))

        # ── 提供者组织 ──
        if filters.providerOrganizations:
            clauses.append(Agent.acs["provider"]["organization"].astext.in_(filters.providerOrganizations))
        if filters.providerOrganizations_reject:
            clauses.append(
                not_(Agent.acs["provider"]["organization"].astext.in_(filters.providerOrganizations_reject))
            )

        # ── 提供者国家代码 ──
        if filters.providerCountryCodes:
            clauses.append(Agent.acs["provider"]["countryCode"].astext.in_(filters.providerCountryCodes))
        if filters.providerCountryCodes_reject:
            clauses.append(
                not_(Agent.acs["provider"]["countryCode"].astext.in_(filters.providerCountryCodes_reject))
            )

        # ── 输入输出模式 ──
        if filters.inputModes:
            input_conditions = [
                or_(
                    func.jsonb_path_exists(
                        Agent.acs,
                        cast(f'$.defaultInputModes[*] ? (@ == "{mode}")', JSONPATH)
                    ),
                    func.jsonb_path_exists(
                        Agent.acs,
                        cast(f'$.skills[*].inputModes[*] ? (@ == "{mode}")', JSONPATH)
                    )
                )
                for mode in filters.inputModes
            ]
            clauses.append(or_(*input_conditions))

        if filters.outputModes:
            output_conditions = [
                or_(
                    func.jsonb_path_exists(
                        Agent.acs,
                        cast(f'$.defaultOutputModes[*] ? (@ == "{mode}")', JSONPATH)
                    ),
                    func.jsonb_path_exists(
                        Agent.acs,
                        cast(f'$.skills[*].outputModes[*] ? (@ == "{mode}")', JSONPATH)
                    )
                )
                for mode in filters.outputModes
            ]
            clauses.append(or_(*output_conditions))

        # ── isActive（明确设置时） ──
        if filters.isActive is not None:
            if filters.isActive:
                clauses.append(
                    or_(
                        Agent.acs["active"].astext.cast(Boolean) == True,
                        Agent.acs["active"].astext == "true"
                    )
                )
            else:
                clauses.append(
                    or_(
                        Agent.acs["active"].astext.cast(Boolean) == False,
                        Agent.acs["active"].astext == "false"
                    )
                )

        # ── aic ──
        if filters.aic:
            clauses.append(Agent.aic == filters.aic)
        if filters.aicStartWith:
            clauses.append(Agent.aic.like(f"{filters.aicStartWith}%"))

        # ── hasEndpoints ──
        if filters.hasEndpoints is not None:
            if filters.hasEndpoints:
                clauses.append(func.jsonb_array_length(Agent.acs["endPoints"]) > 0)
            else:
                clauses.append(
                    or_(
                        Agent.acs["endPoints"].is_(None),
                        Agent.acs["endPoints"].astext == "null",
                        func.jsonb_array_length(Agent.acs["endPoints"]) == 0
                    )
                )

        # ── hasWebAppUrl ──
        if filters.hasWebAppUrl is not None:
            if filters.hasWebAppUrl:
                clauses.append(
                    and_(
                        Agent.acs["webAppUrl"].is_not(None),
                        Agent.acs["webAppUrl"].astext != "null",
                        Agent.acs["webAppUrl"].astext != ""
                    )
                )
            else:
                clauses.append(
                    or_(
                        Agent.acs["webAppUrl"].is_(None),
                        Agent.acs["webAppUrl"].astext == "null",
                        Agent.acs["webAppUrl"].astext == ""
                    )
                )

        # ── capabilities ──
        if filters.capabilities:
            cap = filters.capabilities
            if cap.streaming is not None:
                val = True if cap.streaming else False
                clauses.append(
                    or_(
                        Agent.acs["capabilities"]["streaming"].astext.cast(Boolean) == val,
                        Agent.acs["capabilities"]["streaming"].astext == str(val).lower()
                    )
                )
            if cap.notification is not None:
                val = True if cap.notification else False
                clauses.append(
                    or_(
                        Agent.acs["capabilities"]["notification"].astext.cast(Boolean) == val,
                        Agent.acs["capabilities"]["notification"].astext == str(val).lower()
                    )
                )
            if cap.messageQueue:
                mq_conditions = [
                    func.jsonb_path_exists(
                        Agent.acs,
                        cast(f'$.capabilities.messageQueue[*] ? (@ == "{mq}")', JSONPATH)
                    )
                    for mq in cap.messageQueue
                ]
                clauses.append(or_(*mq_conditions))

        return clauses

    async def _enhanced_search_agents(
        self, query: str, agents_data, count: int = 5
    ) -> Tuple[List[DiscoveryAgentSkill], Dict, str]:
        """
        使用增强的搜索方法查找 Agent。

        Args:
            query: 搜索查询字符串
            agents_data: 包含所有 Agent.acs 数据的列表
            count: 返回的agents数量

        Returns:
            (匹配的 AgentSchema 列表, acs_dict, reasoning)
        """

        agents_schema = []
        reasoning = ""
        try:
            await AgentDiscovery.load_agents_async(agents_data)
            # 使用 discover_skills_enhanced 进行查询
            result = await AgentDiscovery.discover_skills_enhanced(
                task_description=query, k=count
            )
            skills = result["skills"]
            reasoning = result.get("reasoning", "")
            acs_dict = {}
            for agent in skills:
                agent_schema = DiscoveryAgentSkill(
                    aic=agent.get("aic"),
                    skillId=agent.get("skillid"),
                    ranking=agent.get("ranking"),
                    memo=agent.get("memo", ""),
                )
                agents_schema.append(agent_schema)
                acs_dict[agent.get('aic')] = agent.get('acs')
        except Exception as e:
            raise DiscoveryException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_name=DiscoveryError.ENHANCED_DISCOVERY_FAIL,
                error_msg=f"Failed to enhanced_discover: {str(e)}",
                input_params={"query": query, "count": count},
            )
        return agents_schema, acs_dict, reasoning

    @time_it_return_ms
    async def discover_agents_filtered(
        self, request: DiscoveryRequest
    ) -> Tuple[Tuple[List[DiscoveryAgentSkill], Dict], float]:
        """
        纯过滤模式：仅执行数据库过滤，不进行语义搜索/LLM排序。

        Returns:
            ((agents_list, acs_dict), duration_ms)
        """
        try:
            legacy_filters = convert_filter_to_legacy(request.filter)

            async with AsyncSessionLocal() as session:
                stmt = select(Agent)

                where_clauses = self._build_filter_clauses(legacy_filters)
                for clause in where_clauses:
                    stmt = stmt.where(clause)

                limit = request.limit or 10
                stmt = stmt.limit(limit)

                result = await session.execute(stmt)
                agents = result.scalars().all()

            agents_schema = []
            acs_dict = {}
            for rank, agent in enumerate(agents, start=1):
                agent_schema = DiscoveryAgentSkill(
                    aic=agent.aic,
                    skillId="",
                    ranking=rank,
                    memo="",
                )
                agents_schema.append(agent_schema)
                acs_dict[agent.aic] = agent.acs

            return agents_schema, acs_dict

        except Exception as e:
            raise DiscoveryException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_name=DiscoveryError.DATABASE_ERROR,
                error_msg=f"Filtered query failed: {str(e)}",
                input_params={"filter": str(request.filter)},
            )

# 创建全局服务实例
discovery_service = DiscoveryService()