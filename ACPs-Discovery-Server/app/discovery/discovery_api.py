"""
发现 API 端点（支持服务器转发）。
此模块包含 Agent 发现功能的 FastAPI 路由和端点定义。
"""
import logging
import httpx
from typing import Optional
from fastapi import APIRouter, HTTPException
from app.discovery.schema import DiscoveryRequest, DiscoveryRequestV1, DiscoveryResponseV1, AgentSchemaV1
from acps_sdk.adp import DiscoveryResponse, DiscoveryResult
from app.discovery.service import discovery_service
from app.discovery.forwarder_config import (
    load_config, 
    get_config, 
    record_request
)
from fastapi.responses import JSONResponse
import asyncio
import time
from datetime import datetime
from typing import Optional as OptionalType
from pathlib import Path
import json
_health_check_task: OptionalType[asyncio.Task] = None
_forwarder_healthy: bool = False
_last_health_check: OptionalType[float] = None

# 创建路由器
router = APIRouter()
logger = logging.getLogger(__name__)

script_path = Path(__file__).resolve()
script_dir = script_path.parent
datalog_dir = script_dir / "datalog"
datalog_dir.mkdir(exist_ok=True, parents=True)

# 在模块加载时初始化配置
load_config()

def _save_forwarder_request_log(request_data: dict, response_data: dict, success: bool, error: str = None):
    """保存转发请求的 datalog"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        log_file = datalog_dir / f"forwarder_{timestamp}.log"

        log_data = {
            "session_id": f"forwarder_{timestamp}",
            "timestamp": datetime.now().isoformat(),
            "request": request_data,
            "response": response_data if success else None,
            "success": success,
            "error": error,
            "source": "forwarder_server"
        }

        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)

        logger.info(f"📝 转发请求日志已保存: {log_file.name}")
    except Exception as e:
        logger.warning(f"⚠️ 保存转发请求日志失败: {e}")



async def check_forwarder_health() -> bool:
    """检查转发服务器是否可用。"""
    config = get_config()
    if not config.forwarder_server_enabled or not config.forwarder_server_url:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            health_url = f"{config.forwarder_server_url}/health"
            response = await client.get(health_url)
            if response.status_code == 200:
                data = response.json()
                return data.get("status") == "healthy"
        return False
    except Exception as e:
        logger.debug(f"转发服务器健康检查失败: {e}")
        return False

async def periodic_health_check():
    """定期检查转发服务器健康状态的后台任务"""
    global _forwarder_healthy, _last_health_check
    config = get_config()
    while True:
        try:
            if config.forwarder_server_enabled:
                _forwarder_healthy = await check_forwarder_health()
                _last_health_check = time.time()
                status_emoji = "✅" if _forwarder_healthy else "❌"
                logger.info(f"{status_emoji} 转发服务器健康检查: {'可用' if _forwarder_healthy else '不可用'}")
            else:
                _forwarder_healthy = False
        except Exception as e:
            logger.error(f"健康检查任务出错: {e}")
            _forwarder_healthy = False
        await asyncio.sleep(config.forwarder_health_check_interval)


def get_forwarder_health_status() -> bool:
    """获取缓存的转发服务器健康状态（避免每次请求都检查）"""
    return _forwarder_healthy


async def start_health_check_task():
    """启动健康检查后台任务"""
    global _health_check_task
    
    config = get_config()
    
    if config.forwarder_server_enabled and _health_check_task is None:
        _health_check_task = asyncio.create_task(periodic_health_check())
        logger.info(f" 转发服务器健康检查任务已启动（间隔: {config.forwarder_health_check_interval}秒）")


async def stop_health_check_task():
    """停止健康检查后台任务"""
    global _health_check_task
    
    if _health_check_task is not None:
        _health_check_task.cancel()
        try:
            await _health_check_task
        except asyncio.CancelledError:
            pass
        _health_check_task = None
        logger.info(" 转发服务器健康检查任务已停止")


async def forward_to_forwarder(request: DiscoveryRequest) -> Optional[DiscoveryResponse]:
    """
    将请求转发到转发服务器。
    
    Args:
        request: 发现请求
        
    Returns:
        DiscoveryResponse: 转发服务器的响应，如果失败则返回 None
    """
    config = get_config()
    if not config.forwarder_server_enabled or not config.forwarder_server_url:
        return None

    retries = config.forwarder_request_retries
    attempt = 0

    request_data = request.model_dump(by_alias=True, exclude_none=True)
    response_data = None
    success = False
    error_msg = None

    while attempt <= retries:
        try:
            async with httpx.AsyncClient(timeout=config.forwarder_server_timeout) as client:
                forwarder_endpoint = f"{config.forwarder_server_url}/discover"
                log_prefix = "转发请求" if attempt == 0 else f"重试 ({attempt + 1}/{retries + 1})"
                logger.info(f"{log_prefix} 到转发服务器: {forwarder_endpoint}")
                logger.info(f"请求数据: {request_data}")

                response = await client.post(
                    forwarder_endpoint,
                    json=request_data,
                    headers={"accept": "application/json", "Content-Type": "application/json"}
                )
                response.raise_for_status()
                response_data = response.json()

                # 解析响应
                if "result" in response_data:
                    discovery_response = DiscoveryResponse.from_dict(response_data)
                    success = True
                    _save_forwarder_request_log(request_data, response_data, success)
                    return discovery_response
                else:
                    error_msg = f"转发服务器响应缺少 result 字段: {response_data}"
                    logger.warning(error_msg)
                    attempt += 1
                    continue

        except httpx.TimeoutException:
            error_msg = f"转发服务器请求超时 (>{config.forwarder_server_timeout}s)"
            logger.warning(error_msg)
            attempt += 1
            if attempt > retries:
                break
        except httpx.HTTPStatusError as e:
            error_msg = f"转发服务器返回错误状态码: {e.response.status_code}"
            logger.warning(error_msg)
            attempt += 1
            if attempt > retries:
                break
        except Exception as e:
            error_msg = f"转发到转发服务器时发生错误: {type(e).__name__}: {e}"
            logger.error(error_msg)
            attempt += 1
            if attempt > retries:
                break

    _save_forwarder_request_log(request_data, response_data, False, error_msg or "所有重试均失败")
    return None


@router.post(
    "/discover",
    response_model=DiscoveryResponse,
    summary="发现 Agent（POST 方法）",
    description="""
基于自然语言查询发现 Agent。

请求体模型：`DiscoveryRequest`

格式参考
{
  "type": "explicit",
  "query": "string",
  "context": {
    "conversationId": "string",
    "recentTurns": [
      "string"
    ],
    "userProfile": {
      "key": "value"
    }
  },
  "limit": 5,
  "filter": {
    "conditions": [
      {
        "field": "string",
        "op": "eq",
        "value": "string"
      }
    ],
    "groups": [
      "string"
    ],
    "logic": "and"
  },
  "forwardDepthLimit": 1,
  "forwardFanoutLimit": 1,
  "forwardFanoutRemaining": 0,
  "forwardChain": [
    "string"
  ],
  "forwardTrustedServers": [
    "string"
  ],
  "forwardSignatures": [
    "string"
  ],
  "forwardEachTimeoutMs": 10000,
  "forwardTotalTimeoutMs": 60000
}
"""
)
async def discover_agents_post(request: DiscoveryRequest) -> DiscoveryResponse:
    """
    基于自然语言查询发现 Agent（POST 方法）。
    
    此端点首先尝试将请求转发到转发服务器以获得更好的性能。
    如果转发服务器不可用或请求失败，则回退到本地 CPU 处理。
    
    Args:
        request: 包含查询文本、限制数量和类型的发现请求
        
    Returns:
        DiscoveryResponse: 匹配的 Agent 列表及其能力和技能
        
    Raises:
        HTTPException: 当所有处理方式都失败时抛出
    """
    config = get_config()
    logger.info(f"收到发现请求: query='{request.query}', limit={request.limit}, type={request.type}, filter={request.filter}")

    # ── filtered：纯过滤，跳过语义搜索和转发 ──
    if request.type == "filtered":
        logger.info("filtered 模式：仅执行数据库过滤")
        try:
            from app.discovery.schema import DiscoveryResult, DiscoveryRoute, DiscoveryAgentGroup  
            result_tuple, durationMs = await discovery_service.discover_agents_filtered(request)
            agent_response, acs_dict = result_tuple
            logger.info(f"过滤完成，返回 {len(agent_response)} 个智能体")
            discovery_agent_group = DiscoveryAgentGroup(
                group=request.query or "",
                agentSkills=agent_response,
            )
            discovery_route = DiscoveryRoute(          
                forwardChain=["AIC-DS-A"],
                agentGroups=[discovery_agent_group],
                status="ok",
                durationMs=int(durationMs)
            )
            response = DiscoveryResponse.success(
                result=DiscoveryResult(
                    acsMap=acs_dict,
                    agents=[discovery_agent_group],
                    routes=[discovery_route],
                )
            )
            return JSONResponse(content=response.to_dict(), status_code=200)
        except Exception as e:
            logger.error(f"filtered 模式处理失败: {type(e).__name__}: {e}")
            raise HTTPException(status_code=500, detail=f"过滤查询失败: {str(e)}") 
    
    forwarder_response = None
    used_forwarder = False
    forwarder_success = False
    
    if config.forwarder_server_enabled and get_forwarder_health_status():
        logger.info("尝试使用转发服务器处理请求")
        used_forwarder = True
        f_response = await forward_to_forwarder(request)
        
        if f_response is not None:
            logger.info("使用转发服务器响应")
            forwarder_success = True
            record_request(used_forwarder=True, success=True)
            return JSONResponse(content=f_response.to_dict(), status_code=200)
        else:
            logger.info("转发服务器处理失败")
            forwarder_success = False
            
            if not config.forwarder_fallback_to_local:
                record_request(used_forwarder=True, success=False)
                raise HTTPException(
                    status_code=503,
                    detail="转发服务器不可用，且已禁用回退"
                )
            
            logger.info("回退本地处理")
    else:
        logger.debug("转发服务器未配置，直接本地处理")
    
    # 回退到本地处理
    try:
        logger.info("使用本地服务处理请求")
        
        result_tuple, durationMs = await discovery_service.discover_agents_async(request)
        
        # 解包内层元组
        agent_response, acs_dict, reasoning = result_tuple
        
        logger.info("本地服务处理成功")
        logger.debug(f"返回 {len(agent_response)} 个智能体")
        
        # 构造 DiscoveryResponse
        from app.discovery.schema import DiscoveryResult, DiscoveryRoute, DiscoveryAgentGroup

        discovery_agent_group = DiscoveryAgentGroup(
            group=request.query,
            agentSkills=agent_response,
        )
        discovery_route = DiscoveryRoute(
            forwardChain=["AIC-DS-A"],
            agentGroups=[discovery_agent_group],
            status="ok",
            durationMs=int(durationMs)
        )
        discovery_result = DiscoveryResult(
            acsMap=acs_dict,
            agents=[discovery_agent_group],
            routes=[discovery_route],
        )
        
        # 构造最终的 DiscoveryResponse
        cpu_response = DiscoveryResponse.success(result=discovery_result)

        
        # 记录统计
        if used_forwarder:
            record_request(used_forwarder=True, success=False)
        else:
            record_request(used_forwarder=False, success=True)
        
        return JSONResponse(content=cpu_response.to_dict(), status_code=200)
        
    except Exception as e:
        logger.error(f"本地服务处理也失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        
        # 记录统计
        if used_forwarder:
            record_request(used_forwarder=True, success=False)
        else:
            record_request(used_forwarder=False, success=False)
        
        raise HTTPException(
            status_code=500,
            detail=f"Agent 发现失败: {str(e)}"
        )


@router.get(
    "/forwarder-status",
    summary="获取转发服务器状态",
    description="检查转发服务器是否配置和可用"
)
async def get_forwarder_status():
    """
    获取转发服务器的配置和健康状态。
    
    Returns:
        dict: 包含转发服务器配置和状态信息
    """
    global _forwarder_healthy, _last_health_check
    config = get_config()
    is_healthy = False
    
    if config.forwarder_server_enabled:
        logger.info("🔍 手动触发转发服务器健康检查")
        _forwarder_healthy = await check_forwarder_health()
        _last_health_check = time.time()
        
        status_emoji = "✅" if _forwarder_healthy else "❌"
        logger.info(f"{status_emoji} 手动健康检查完成: {'可用' if _forwarder_healthy else '不可用'}")
    
    return {
        "enabled": config.forwarder_server_enabled,
        "url": config.forwarder_server_url if config.forwarder_server_enabled else None,
        "timeout": config.forwarder_server_timeout,
        "healthy": _forwarder_healthy,
        "last_check_time": datetime.fromtimestamp(_last_health_check).isoformat() if _last_health_check else None,
        "check_interval": config.forwarder_health_check_interval,
        "fallback_to_local": config.forwarder_fallback_to_local,
        "retries": config.forwarder_request_retries,
        "status": "available" if _forwarder_healthy else (
            "configured_but_unavailable" if config.forwarder_server_enabled else "not_configured"
        )
    }


@router.post(
    "/discover/v1",
    response_model=DiscoveryResponseV1,
    summary="发现 Agent（V1 兼容版本）",
    description="""
基于自然语言查询发现 Agent。

请求体模型：`DiscoveryRequestV1`
"""
)
async def discover_agents_v1(request: DiscoveryRequestV1) -> DiscoveryResponseV1:
    """
    V1 版本的 Agent 发现接口（兼容旧版本）。
    
    此接口保持与 V1 版本的完全兼容，仅使用本地 CPU 处理，不进行转发
    
    Args:
        request: V1 格式的发现请求
        
    Returns:
        V1 格式的发现响应
        
    Raises:
        HTTPException: 当处理失败时抛出
    """
    logger.info(f"[V1 API] 收到请求: query='{request.query}', limit={request.limit}")
    
    try:
        # 1. 将 V1 请求转换为 V2 请求格式
        from app.discovery.schema import DiscoveryRequest
        v2_request = DiscoveryRequest(
            type='explicit',
            query=request.query,
            limit=request.limit or 5,
            forwardDepthLimit=1,
            forwardFanoutLimit=1,
        )
        
        # 2. 直接调用本地 CPU 服务
        logger.info("[V1 API] 使用本地 CPU 服务处理请求")
        result_tuple, duration_ms = await discovery_service.discover_agents_async(v2_request)
        
        # 解包结果：现在包含 reasoning
        agent_list, acs_dict, reasoning = result_tuple
        
        logger.info(f"[V1 API] 本地 CPU 处理成功，耗时: {duration_ms:.2f}ms")
        if reasoning:
            logger.info(f"[V1 API] 大模型推理: {reasoning[:100]}...")
        
        # 3. 将 V2 结果转换为 V1 格式
        v1_agents = []
        for agent_skill in agent_list:
            # 从 acs_dict 中获取完整的 ACS 信息
            aic = agent_skill.aic
            acs = acs_dict.get(aic, {})
            
            # 提取技能描述
            skill_description = ""
            skill_id = agent_skill.skillId if hasattr(agent_skill, 'skillId') else ""
            
            # 如果有 skillId，从 ACS 的 skills 中找到对应的描述
            if skill_id and acs:
                skills = acs.get('skills', [])
                for skill in skills:
                    if skill.get('id') == skill_id:
                        skill_description = skill.get('description', '')
                        break
            
            # 如果没找到技能描述，使用 Agent 的描述
            if not skill_description and acs:
                skill_description = acs.get('description', '')
            
            # 构造 V1 格式的 Agent
            v1_agent = AgentSchemaV1(
                acs=acs,
                skill_description=skill_description,
                skill_id=skill_id,
                ranking=agent_skill.ranking if hasattr(agent_skill, 'ranking') else None,
                memo=agent_skill.memo if hasattr(agent_skill, 'memo') else "",
            )
            v1_agents.append(v1_agent)
        
        # 4. 构造 V1 响应（包含 reasoning）
        v1_response = DiscoveryResponseV1(
            query=request.query,
            agents=v1_agents,
            reasoning=reasoning
        )
        
        logger.info(f"[V1 API] 返回 {len(v1_agents)} 个智能体")
        
        # 5. 返回 JSON 响应
        response_dict = v1_response.model_dump(exclude_none=True)
        return JSONResponse(content=response_dict, status_code=200)
        
    except Exception as e:
        logger.error(f"[V1 API] 处理失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        
        raise HTTPException(
            status_code=500,
            detail=f"V1 Agent 发现失败: {str(e)}"
        )
    
@router.get(
    "/stats",
    summary="获取本地数据库统计信息",
    description="获取CPU服务器数据库中agents的数量统计"
)
async def get_local_database_stats():
    """
    获取CPU服务器本地数据库统计信息
    
    Returns:
        dict: 包含agents数量的统计信息
    """
    try:
        from app.core.database import get_async_session
        from sqlmodel import select, func
        from app.sync.model import Agent
        
        async for session in get_async_session():
            # 查询agents总数
            agents_count_result = await session.execute(
                select(func.count()).select_from(Agent)
            )
            agents_count = agents_count_result.scalar()
            
            # 统计总技能数（所有agents的skills数组长度之和）
            from sqlalchemy import text
            total_skills_result = await session.execute(
                text("""
                    SELECT COALESCE(SUM(jsonb_array_length(acs->'skills')), 0) 
                    FROM agents
                """)
            )
            total_skills = total_skills_result.scalar()
            
            return JSONResponse(
                content={
                    "status": "ok",
                    "data": {
                        "agents": agents_count,
                        "skills": total_skills
                    },
                    "timestamp": datetime.now().isoformat(),
                    "server_type": "cpu"
                },
                status_code=200
            )
            break
        
    except Exception as e:
        logger.error(f"获取CPU数据库统计信息失败: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            content={
                "status": "error",
                "error": str(e)
            },
            status_code=500
        )    
    
@router.get(
    "/forwarder-stats",
    summary="获取转发服务器数据库统计信息",
    description="从转发服务器获取agents和skills的数量统计"
)
async def get_forwarder_database_stats():
    """
    从转发服务器获取数据库统计信息
    
    Returns:
        dict: 转发服务器数据库的统计信息
    """
    config = get_config()
    
    if not config.forwarder_server_enabled or not config.forwarder_server_url:
        raise HTTPException(
            status_code=503,
            detail="转发服务器未配置或未启用"
        )
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 构建转发服务器的stats端点URL
            forwarder_stats_url = f"{config.forwarder_server_url}/stats" 
            
            logger.info(f"🔍 请求转发服务器统计信息: {forwarder_stats_url}")
            
            response = await client.get(forwarder_stats_url)
            response.raise_for_status()
            
            stats_data = response.json()
            logger.info(f"✅ 转发服务器统计信息获取成功")
            
            return JSONResponse(
                content={
                    "status": "ok",
                    "forwarder_server": {
                        "url": config.forwarder_server_url,
                        "healthy": get_forwarder_health_status(),
                    },
                    "stats": stats_data.get("data", {}),
                    "retrieved_at": datetime.now().isoformat()
                },
                status_code=200
            )
            
    except httpx.TimeoutException:
        logger.error("转发服务器统计信息请求超时")
        raise HTTPException(
            status_code=504,
            detail="转发服务器请求超时"
        )
    except httpx.HTTPStatusError as e:
        logger.error(f"转发服务器返回错误: {e.response.status_code}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"转发服务器错误: {e.response.text}"
        )
    except Exception as e:
        logger.error(f"获取转发服务器统计信息失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取转发服务器统计信息失败: {str(e)}"
        )    
    
@router.get(
    "/forwarder-random-agents",
    summary="从转发服务器随机获取agents",
    description="从转发服务器随机获取指定数量的agents"
)
async def get_forwarder_random_agents(count: int = 5):
    """
    从转发服务器随机获取agents
    
    Args:
        count: 获取的数量，默认5个
    
    Returns:
        dict: 转发服务器返回的随机agents数据
    """
    config = get_config()
    
    if not config.forwarder_server_enabled or not config.forwarder_server_url:
        raise HTTPException(
            status_code=503,
            detail="转发服务器未配置或未启用"
        )
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 构建转发服务器的random-agents端点URL
            forwarder_random_url = f"{config.forwarder_server_url}/random-agents"
            
            logger.info(f"🔍 请求转发服务器随机agents: {forwarder_random_url}?count={count}")
            
            response = await client.get(forwarder_random_url, params={"count": count})
            response.raise_for_status()
            
            random_data = response.json()
            logger.info(f"✅ 转发服务器随机agents获取成功: {random_data.get('data', {}).get('count', 0)} 个")
            
            return JSONResponse(
                content={
                    "status": "ok",
                    "forwarder_server": {
                        "url": config.forwarder_server_url,
                        "healthy": get_forwarder_health_status(),
                    },
                    "data": random_data.get("data", {}),
                    "retrieved_at": datetime.now().isoformat()
                },
                status_code=200
            )
            
    except httpx.TimeoutException:
        logger.error("转发服务器随机agents请求超时")
        raise HTTPException(
            status_code=504,
            detail="转发服务器请求超时"
        )
    except httpx.HTTPStatusError as e:
        logger.error(f"转发服务器返回错误: {e.response.status_code}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"转发服务器错误: {e.response.text}"
        )
    except Exception as e:
        logger.error(f"获取转发服务器随机agents失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取转发服务器随机agents失败: {str(e)}"
        )    