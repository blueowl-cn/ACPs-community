import json
import os
from pathlib import Path
from typing import List, Optional
import logging 
from fastapi import status
from sqlmodel import select
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
    AgentSchema,
)
from app.discovery.singleton import AgentDiscovery

logger = logging.getLogger(__name__)

class DiscoveryService:
    """Agent 发现功能的服务类。"""

    def __init__(self):
        """初始化发现服务。"""
        pass

    async def discover_agents_async(
        self, request: DiscoveryRequest
    ) -> DiscoveryResponse:
        """
        基于自然语言查询发现 Agent（异步版本）。
        """
        try:
            all_agents = await self._discovery_agents_async(request.query,limit=request.limit)

            return DiscoveryResponse(
                query=request.query,
                agents=all_agents,
            )
        except Exception as e:
            # 处理意外错误
            raise DiscoveryException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_name=DiscoveryError.DISCOVERY_FAIL,
                error_msg=f"Failed to discover: {str(e)}",
                input_params={"query": request.query},
            )

    async def _search_agents_async(self, query: str) -> List[AgentSchema]:
        """
        异步搜索 Agent。

        使用 JSONB 操作直接在数据库层面查询 acs.description 包含查询关键词的 Agent。

        Args:
            query: 搜索查询字符串

        Returns:
            匹配的 AgentSchema 列表
        """
        agents_schema = []

        try:
            # 获取数据库中的 Agent，使用 JSONB 操作符根据查询参数进行查询
            async with AsyncSessionLocal() as session:
                # 使用 JSONB 的 ->> 操作符提取 description 字段，然后进行 LIKE 查询
                # 按照seq反向排序（seq越大排序越在前），限制返回3条数据
                stmt = (
                    select(Agent)
                    .where(Agent.acs["description"].astext.like(f"%{query}%"))
                    .order_by(Agent.seq.desc())
                    .limit(3)
                )
                result = await session.execute(stmt)
                agents = result.scalars().all()

                # 转换为 AgentSchema
                for agent in agents:
                    # 安全地从 JSONB 字段中提取数据
                    description = ""
                    url = ""

                    if agent.acs and isinstance(agent.acs, dict):
                        description = agent.acs.get("description", "")
                        url = agent.acs.get("url", "")

                    agent_schema = AgentSchema(
                        aic=agent.aic,
                        description=description,
                        url=url,
                        skill_id=None,  # 暂时设为 None，因为数据库中没有这个字段
                        ranking=None,  # 暂时设为 None，因为数据库中没有这个字段
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
    
    async def _discovery_agents_async(self, query: str, limit: int) -> List[AgentSchema]:
        """
        使用发现智能体方法搜索 Agent。

        调用写好的发现智能体方法进行搜索。

        Args:
            query: 搜索查询字符串
            limit: 返回的agents数量限制

        Returns:
            匹配的 AgentSchema 列表
        """
        agents_schema = []

        try:
            # 获取数据库中的 Agent，使用 JSONB 操作符根据查询参数进行查询
            async with AsyncSessionLocal() as session:
                # 使用 JSONB 的 ->> 操作符提取 description 字段，然后进行 LIKE 查询
                stmt = select(Agent).where(
                    Agent.acs["description"].astext.like(f"%{query}%")
                )
                stmt = select(Agent) # 暂时用全搜，测试更方便
                result = await session.execute(stmt)
                agents = result.scalars().all()

                # 由于schema里的字段都可以在acs里找到，所以这里直接用acs的字典列表来构造
                agents_data = [agent.acs for agent in agents]

            # enhanced_button控制是否使用增强搜索，这里默认为使用    
            enhanced_button = True
            if enhanced_button:
                agents_schema = await self._enhanced_search_agents(query, agents_data, limit)
            else:
                # 直接转换为 AgentSchema（取前limit个）
                for agent in agents_data[:limit]:
                    agent_schema = AgentSchema(
                        acs=agent,
                        skill_description="",
                        skill_id=None,
                        ranking=None,
                        memo=""
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

    async def _enhanced_search_agents(
        self, query: str, agents_data, count: int = 5
    ) -> List[AgentSchema]:
        """
        使用增强的搜索方法查找 Agent。

        Args:
            query: 搜索查询字符串
            agents_data: 包含所有 Agent.acs 数据的列表
            count: 返回的agents数量

        Returns:
            匹配的 AgentSchema 列表
        """

        agents_schema = []
        api_key = settings.DEEPSEEK_API_KEY
        try:
            await AgentDiscovery.load_agents_async(agents_data)
            # 使用 discover_skills_enhanced 进行查询
            result = await AgentDiscovery.discover_skills_enhanced(
                task_description=query, k=count
            )
            skills = result["skills"]
            for agent in skills:
                agent_schema = AgentSchema(
                    acs=agent.get("acs"),
                    skill_description=agent.get("description"),
                    skill_id=agent.get("skillid"),
                    ranking=agent.get("ranking"),
                    memo=agent.get("memo",""),
                )
                agents_schema.append(agent_schema)
        except Exception as e:
            raise DiscoveryException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_name=DiscoveryError.ENHANCED_DISCOVERY_FAIL,
                error_msg=f"Failed to enhanced_discover: {str(e)}",
                input_params={
                    "query": query,
                    "agents_data": agents_data,
                    "count": count,
                },
            )

        return agents_schema


# 创建全局服务实例
discovery_service = DiscoveryService()
