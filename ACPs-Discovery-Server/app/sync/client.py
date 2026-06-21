"""
DRC（发现注册中心协调）客户端实现。

此模块实现从注册中心服务器同步数据的客户端逻辑。
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional, List, AsyncGenerator
from urllib.parse import urljoin

import httpx
from fastapi import status
from sqlmodel import select

from app.core.config import settings
from app.core.database import get_async_session
from .model import (
    Envelope,
    DRCState,
    SnapshotResponseHeader,
    RegistryInfo,
    Agent,
    OperationType,
)
from .exception import SyncException, SyncError
from pathlib import Path
from app.discovery.singleton import AgentDiscovery
logger = logging.getLogger(__name__)


class DRCClient:
    """
    用于从注册中心服务器同步数据的 DRC 客户端。
    """

    def __init__(
        self,
        registry_base_url: str,
        sync_interval: int = 30,
        target_types: Optional[List[str]] = None,
    ):
        """
        初始化 DRC 客户端。

        Args:
            registry_base_url: 注册中心服务器的基础 URL
            sync_interval: 轮询变更的间隔时间（秒）
            target_types: 要同步的对象类型列表（默认：["acs"]）
        """
        self.registry_base_url = registry_base_url.rstrip("/")
        self.sync_interval = sync_interval
        self.target_types = target_types or ["acs"]

        # 客户端状态 - 将在 start_background_sync 时初始化
        self.state = None
        self.is_running = False
        self._sync_task: Optional[asyncio.Task] = None

        # HTTP 客户端
        self.http_client: Optional[httpx.AsyncClient] = None
        # 语义匹配器实例
        self.semantic_matcher = AgentDiscovery.semantic_matcher

    # def _init_semantic_matcher(self):
    #     """初始化语义匹配器"""
    #     try:

    #         # 获取项目根目录路径
    #         current_file = Path(__file__).resolve()
    #         project_root = current_file.parent.parent  # /path/to/project/app
    #         discovery_cache_dir = (
    #             project_root / "discovery" / "semantic_cache"
    #         )  # 缓存统一放到discovery目录下
    #         self.semantic_matcher = SemanticAgentMatcher(
    #             model_name=getattr(settings, "SEMANTIC_MODEL_NAME", "all-MiniLM-L6-v2"),
    #             cache_dir=str(discovery_cache_dir),
    #             similarity_threshold=getattr(settings, "SEMANTIC_SIMILARITY_THRESHOLD", 0.3)
    #         )
    #         logger.info(f"语义匹配器初始化成功，缓存目录: {discovery_cache_dir}")
    #     except Exception as e:
    #         logger.error(f"语义匹配器初始化失败: {e}")
    #         self.semantic_matcher = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端。"""
        if self.http_client is None:
            self.http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0), follow_redirects=True
            )
        return self.http_client

    async def close(self):
        """关闭 HTTP 客户端并清理资源。"""
        if self.http_client:
            await self.http_client.aclose()
            self.http_client = None

    def _build_url(self, endpoint: str) -> str:
        """为 DRC API 端点构建完整 URL。"""
        return urljoin(f"{self.registry_base_url}/", endpoint)

    async def get_registry_info(self) -> Optional[RegistryInfo]:
        """获取注册中心服务器信息。"""
        try:
            client = await self._get_http_client()
            url = self._build_url("info")

            logger.info(f"从 {url} 获取注册中心信息")
            response = await client.get(url, headers={"Accept": "application/json"})

            if response.status_code == 200:
                data = response.json()
                return RegistryInfo(**data)
            else:
                logger.warning(f"获取注册中心信息失败: {response.status_code}")
                return None

        except httpx.ConnectError as e:
            logger.error(f"连接注册中心失败: {e}")
            raise SyncException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                error_name=SyncError.CONNECTION_FAIL,
                error_msg=f"连接注册中心失败: {e}",
                input_params={"registry_url": self.registry_base_url},
            )
        except httpx.TimeoutException as e:
            logger.error(f"连接注册中心超时: {e}")
            raise SyncException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                error_name=SyncError.CONNECTION_FAIL,
                error_msg=f"连接注册中心超时: {e}",
                input_params={"registry_url": self.registry_base_url},
            )
        except Exception as e:
            logger.error(f"获取注册中心信息时出错: {e}")
            raise SyncException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_name=SyncError.REGISTRY_UNAVAILABLE,
                error_msg=f"获取注册中心信息时出错: {e}",
                input_params={"registry_url": self.registry_base_url},
            )

    async def create_snapshot(
        self,
        types: Optional[List[str]] = None,
        from_seq: Optional[int] = None,
        limit: int = 10000,
    ) -> AsyncGenerator[Envelope, None]:
        """
        创建并获取快照数据。

        Args:
            types: 要同步的对象类型（默认为 self.target_types）
            from_seq: 增量快照的起始序列
            limit: 每个块的最大对象数量

        Yields:
            来自快照的 Envelope 对象
        """
        types = types or self.target_types

        try:
            client = await self._get_http_client()

            # 构建快照请求 URL
            url = self._build_url("snapshots")
            params = {"types": ",".join(types), "limit": limit}
            if from_seq:
                params["from_seq"] = from_seq

            logger.info(f"创建快照: types={types}, from_seq={from_seq}, limit={limit}")

            # 请求第一个块
            response = await client.get(
                url, params=params, headers={"Accept": "application/x-ndjson"}
            )

            if response.status_code != 200:
                raise SyncException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    error_name=SyncError.SNAPSHOT_FAIL,
                    error_msg=f"快照请求失败: {response.status_code} {response.text}",
                    input_params={"types": types, "from_seq": from_seq, "limit": limit},
                )

            # 从响应头解析快照元数据
            snapshot_info = SnapshotResponseHeader(
                snapshot_id=response.headers.get("X-Snapshot-Id", ""),
                snapshot_seq=int(response.headers.get("X-Snapshot-Seq", "0")),
                chunk_index=int(response.headers.get("X-Snapshot-Chunk-Index", "0")),
                chunk_total=int(response.headers.get("X-Snapshot-Chunk-Total", "1")),
                object_count=int(response.headers.get("X-Snapshot-Object-Count", "0")),
            )

            logger.info(
                f"Snapshot created: {snapshot_info.snapshot_id}, "
                f"seq={snapshot_info.snapshot_seq}, "
                f"chunks={snapshot_info.chunk_total}, "
                f"objects={snapshot_info.object_count}"
            )

            # Yield objects from first chunk
            first_chunk_object_count = 0
            for line in response.text.strip().split("\n"):
                if line:
                    try:
                        envelope_data = json.loads(line)
                        yield Envelope(**envelope_data)
                        first_chunk_object_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to parse envelope: {e}")
                        raise SyncException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            error_name=SyncError.INVALID_RESPONSE,
                            error_msg=f"解析快照数据失败: {e}",
                            input_params={"line": line},
                        )

                # 如果有剩余的数据块则继续获取
            for chunk_index in range(1, snapshot_info.chunk_total):
                chunk_params = {
                    "id": snapshot_info.snapshot_id,
                    "chunk": chunk_index,
                    "limit": limit,
                }

                logger.debug(
                    f"Fetching chunk {chunk_index}/{snapshot_info.chunk_total}"
                )

                chunk_response = await client.get(
                    url, params=chunk_params, headers={"Accept": "application/x-ndjson"}
                )

                if chunk_response.status_code != 200:
                    logger.error(
                        f"Chunk request failed: URL={url}, params={chunk_params}, response={chunk_response.text}"
                    )
                    raise SyncException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        error_name=SyncError.SNAPSHOT_FAIL,
                        error_msg=f"Chunk {chunk_index} request failed: {chunk_response.status_code} - {chunk_response.text}",
                        input_params={
                            "chunk_index": chunk_index,
                            "snapshot_id": snapshot_info.snapshot_id,
                            "url": url,
                            "params": chunk_params,
                        },
                    )

                # Yield objects from chunk
                chunk_object_count = 0
                for line in chunk_response.text.strip().split("\n"):
                    if line:
                        try:
                            envelope_data = json.loads(line)
                            yield Envelope(**envelope_data)
                            chunk_object_count += 1
                        except Exception as e:
                            logger.warning(f"Failed to parse envelope: {e}")
                            raise SyncException(
                                status_code=status.HTTP_502_BAD_GATEWAY,
                                error_name=SyncError.INVALID_RESPONSE,
                                error_msg=f"解析快照数据失败: {e}",
                                input_params={"line": line, "chunk_index": chunk_index},
                            )

            # 使用快照序列更新客户端状态
            self.state.last_seq = snapshot_info.snapshot_seq
            self.state.needs_snapshot = False

            logger.info(f"Snapshot sync completed, seq={snapshot_info.snapshot_seq}")

            # 在服务器上清理快照（可选）
            try:
                await client.delete(
                    self._build_url(f"snapshots/{snapshot_info.snapshot_id}")
                )
            except Exception as e:
                logger.debug(f"Failed to cleanup snapshot: {e}")

        except SyncException:
            raise
        except httpx.ConnectError as e:
            raise SyncException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                error_name=SyncError.CONNECTION_FAIL,
                error_msg=f"连接注册中心失败: {e}",
                input_params={"registry_url": self.registry_base_url},
            )
        except httpx.TimeoutException as e:
            raise SyncException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                error_name=SyncError.CONNECTION_FAIL,
                error_msg=f"快照请求超时: {e}",
                input_params={"types": types, "from_seq": from_seq},
            )
        except Exception as e:
            raise SyncException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_name=SyncError.SNAPSHOT_FAIL,
                error_msg=f"快照同步失败: {e}",
                input_params={"types": types, "from_seq": from_seq},
            )

    async def get_changes(
        self,
        seq: int,
        types: Optional[List[str]] = None,
        limit: int = 1000,
        wait: Optional[int] = None,
    ) -> AsyncGenerator[Envelope, None]:
        """
        从注册中心获取增量变更。

        Args:
            seq: 起始序列号
            types: 要同步的对象类型（默认为 self.target_types）
            limit: 最大变更条目数
            wait: 长轮询等待时间（秒）

        Yields:
            来自变更流的 Envelope 对象
        """
        types = types or self.target_types

        try:
            client = await self._get_http_client()

            url = self._build_url("changes")
            params = {"types": ",".join(types), "seq": seq, "limit": limit}
            if wait:
                params["wait"] = f"{wait}s"

            logger.debug(f"Fetching changes from seq={seq}")

            response = await client.get(
                url, params=params, headers={"Accept": "application/x-ndjson"}
            )

            if response.status_code == 200:
                # Parse next sequence from headers
                next_seq = response.headers.get("X-Next-Seq")
                if next_seq:
                    self.state.last_seq = int(next_seq)

                # 统计变更数量
                change_count = 0

                # 产出变更记录
                for line in response.text.strip().split("\n"):
                    if line:
                        try:
                            envelope_data = json.loads(line)
                            change_count += 1
                            yield Envelope(**envelope_data)
                        except Exception as e:
                            logger.warning(f"Failed to parse envelope: {e}")
                            raise SyncException(
                                status_code=status.HTTP_502_BAD_GATEWAY,
                                error_name=SyncError.INVALID_RESPONSE,
                                error_msg=f"解析变更数据失败: {e}",
                                input_params={"line": line},
                            )

                logger.debug(f"Processed {change_count} changes, next_seq={next_seq}")

            elif response.status_code == 204:
                # 无可用变更 - 不产出任何数据，这会让调用方知道没有更多数据
                next_seq = response.headers.get("X-Next-Seq")
                if next_seq:
                    self.state.last_seq = int(next_seq)

                logger.debug(f"No changes available (204), next_seq={next_seq or seq}")
                # 不 yield 任何数据，生成器会自然结束

            elif response.status_code == 410:
                # 超出保留窗口，需要执行快照同步
                logger.warning(
                    "Client has fallen behind retention window, snapshot needed"
                )
                self.state.needs_snapshot = True
                raise SyncException(
                    status_code=status.HTTP_409_CONFLICT,
                    error_name=SyncError.RETENTION_WINDOW_EXCEEDED,
                    error_msg="Client fallen behind retention window",
                    input_params={"seq": seq, "types": types},
                )

            else:
                raise SyncException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    error_name=SyncError.CHANGES_FAIL,
                    error_msg=f"Changes request failed: {response.status_code} {response.text}",
                    input_params={"seq": seq, "types": types},
                )

        except SyncException:
            raise
        except httpx.ConnectError as e:
            raise SyncException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                error_name=SyncError.CONNECTION_FAIL,
                error_msg=f"连接注册中心失败: {e}",
                input_params={"registry_url": self.registry_base_url},
            )
        except httpx.TimeoutException as e:
            raise SyncException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                error_name=SyncError.CONNECTION_FAIL,
                error_msg=f"变更请求超时: {e}",
                input_params={"seq": seq, "types": types},
            )
        except Exception as e:
            raise SyncException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_name=SyncError.CHANGES_FAIL,
                error_msg=f"获取变更失败: {e}",
                input_params={"seq": seq, "types": types},
            )

    def should_apply_envelope(self, envelope: Envelope) -> bool:
        """
        判断是否应应用该 envelope（幂等性检查）。

        Args:
            envelope: 待检查的 Envelope 对象

        Returns:
            如果应应用返回 True，否则返回 False
        """
        # 获取当前对象的版本
        current_version = self.state.object_versions.get(envelope.type, {}).get(
            envelope.id, 0
        )

        # 如果版本较新则应用
        return envelope.version > current_version

    async def _apply_to_database(self, envelope: Envelope):
        """
        将 envelope 的数据应用到数据库的内部函数。

        Args:
            envelope: 要应用的 Envelope 对象

        Raises:
            SyncException: 数据库操作失败时抛出
        """
        try:
            # 获取数据库会话
            async for session in get_async_session():
                # 查找现有的 Agent 记录
                stmt = select(Agent).where(Agent.aic == envelope.id)
                result = await session.execute(stmt)
                existing_agent = result.scalar_one_or_none()

                if envelope.op == OperationType.DELETE:
                    # 处理删除操作
                    logger.debug(
                        f"Applying DELETE: {envelope.type}:{envelope.id} v{envelope.version}"
                    )

                    if existing_agent:
                        await session.delete(existing_agent)
                        logger.debug(f"Deleted agent from database: {envelope.id}")
                    else:
                        logger.debug(f"Agent not found for deletion: {envelope.id}")

                else:
                    # 处理 upsert 操作（默认）
                    logger.debug(
                        f"Applying UPSERT: {envelope.type}:{envelope.id} v{envelope.version}"
                    )

                    if existing_agent:
                        # 更新现有记录
                        existing_agent.version = envelope.version
                        existing_agent.seq = envelope.seq
                        existing_agent.acs = envelope.payload
                        session.add(existing_agent)
                    else:
                        # 创建新记录
                        agent = Agent(
                            aic=envelope.id,
                            version=envelope.version,
                            seq=envelope.seq,
                            acs=envelope.payload,
                        )
                        session.add(agent)

                # 提交事务
                await session.commit()

                logger.debug(
                    f"Applied envelope to database: {envelope.type}:{envelope.id} v{envelope.version} op={envelope.op or 'upsert'}"
                )
                break  # 成功处理后退出循环

        except Exception as e:
            logger.error(f"Failed to apply envelope to database: {e}")
            raise SyncException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_name=SyncError.DATABASE_ERROR,
                error_msg=f"数据库操作失败: {e}",
                input_params={
                    "envelope_type": envelope.type,
                    "envelope_id": envelope.id,
                    "envelope_version": envelope.version,
                },
            )

    async def updateSearchIndex(self, envelope: Envelope):
        """
        更新搜索索引。

        Args:
            envelope: 要处理的 Envelope 对象
        """
        try:
            # 仅处理acs类型的数据
            if envelope.type != "acs":
                return

            # 检查语义匹配器是否可用
            if self.semantic_matcher is None:
                logger.debug("语义匹配器未初始化，跳过embedding更新")
                return
            # 处理创建/更新操作
            await self._handle_agent_upsert_semantic(envelope)

        except Exception as e:
            logger.error(f"处理语义索引时出错 {envelope.type}:{envelope.id}: {e}")

    async def _handle_agent_upsert_semantic(self, envelope: Envelope):
        """处理智能体创建/更新的语义索引"""
        try:
            # 解析智能体数据
            agent_data = envelope.payload
            if not agent_data:
                logger.debug(f"智能体 {envelope.id} 数据为空，跳过语义索引更新")
                return

            # 确保agent_data包含AIC
            if "AIC" not in agent_data:
                agent_data["AIC"] = envelope.id

            # 添加版本和序列号信息用于缓存管理
            agent_data["version"] = envelope.version
            agent_data["seq"] = envelope.seq
            agent_data["lastModifiedTime"] = envelope.seq  # 使用seq作为修改时间标识

            # 更新语义索引
            await self.semantic_matcher._update_agent_index(agent_data)

            logger.debug(f"已更新智能体 {envelope.id} 的语义索引")

        except Exception as e:
            logger.error(f"更新智能体 {envelope.id} 语义索引失败: {e}")

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
        await self.updateSearchIndex(envelope)# - 更新搜索索引
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

    async def sync_once(self):
        """
        执行一次同步循环。

        根据协议规范实现 DRC 的核心同步逻辑。
        """
        start_time = datetime.now()

        try:
            if self.state.needs_snapshot:
                logger.info("需要Snapshot同步 (初始同步或数据过期)")

                # Try incremental snapshot first if we have a sequence
                from_seq = self.state.last_seq if self.state.last_seq else None

                async for envelope in self.create_snapshot(
                    types=self.target_types,
                    from_seq=from_seq,
                    limit=settings.DRC_SNAPSHOT_CHUNK_SIZE,
                ):
                    await self.apply(envelope)

                logger.info(f"Snapshot sync completed, seq={self.state.last_seq}")

                # 获取当前Agent数量并记录
                async for session in get_async_session():
                    result = await session.execute(select(Agent))
                    agents = result.scalars().all()
                    agent_count = len(agents)
                    logger.info(f"Snapshot同步完成! 当前Agent数量: {agent_count}")
                    break
            else:
                # Incremental sync via changes API
                await self._sync_changes_continuously()

            # Update last sync time
            self.state.last_sync_time = start_time

        except SyncException:
            raise
        except Exception as e:
            logger.error(f"Sync error: {e}")
            raise SyncException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_name=SyncError.SYNC_FAIL,
                error_msg=f"同步失败: {e}",
                input_params={
                    "sync_interval": self.sync_interval,
                    "target_types": self.target_types,
                },
            )

    async def _sync_changes_continuously(self):
        """
        连续同步变更数据，直到服务器返回 204 No Content 为止。
        """
        seq = self.state.last_seq or 0
        total_change_count = 0

        while True:
            try:
                change_count = 0
                has_changes = False

                async for envelope in self.get_changes(
                    seq=seq,
                    types=self.target_types,
                    limit=settings.DRC_CHANGES_CHUNK_SIZE,
                    wait=min(self.sync_interval, 20),  # Use long polling but cap at 20s
                ):
                    await self.apply(envelope)
                    change_count += 1
                    has_changes = True

                total_change_count += change_count

                if change_count > 0:
                    logger.debug(
                        f"Processed {change_count} changes in this batch, seq={self.state.last_seq}"
                    )

                # 如果没有变更数据，说明收到了 204，退出循环
                if not has_changes:
                    logger.debug(
                        f"No more changes available (received 204), total processed: {total_change_count}"
                    )
                    break

                # 更新序列号为下一次请求
                seq = self.state.last_seq or 0

            except SyncException as e:
                if e.error_name == SyncError.RETENTION_WINDOW_EXCEEDED:
                    logger.info("数据保留窗口超期，切换到Snapshot同步")
                    self.state.needs_snapshot = True
                    await self.sync_once()  # Retry with snapshot
                    return
                else:
                    raise

        # 记录总的同步结果
        if total_change_count > 0:
            # 获取当前Agent数量并记录
            async for session in get_async_session():
                result = await session.execute(select(Agent))
                agents = result.scalars().all()
                agent_count = len(agents)
                logger.info(
                    f"Changes连续同步完成! 总共处理了 {total_change_count} 个变更，当前Agent数量: {agent_count}"
                )
                break
        else:
            logger.debug("Changes同步检查完成，无新数据")

    async def start_background_sync(self):
        """启动后台同步任务。"""
        if self.is_running:
            logger.warning("Background sync is already running")
            return

        # 从数据库加载同步状态
        self.state = await DRCState.load_from_db()
        logger.info(
            f"Loaded sync state: last_seq={self.state.last_seq}, needs_snapshot={self.state.needs_snapshot}"
        )

        self.is_running = True
        self._sync_task = asyncio.create_task(self._background_sync_loop())
        logger.info(f"Started DRC background sync with {self.sync_interval}s interval")

    async def stop_background_sync(self):
        """停止后台同步任务。"""
        if not self.is_running:
            return

        self.is_running = False
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
            self._sync_task = None

        logger.info("Stopped DRC background sync")

    async def _background_sync_loop(self):
        """后台任务循环，用于定期执行同步。"""
        logger.info(f"Starting DRC sync loop (interval: {self.sync_interval}s)")

        while self.is_running:
            try:
                await self.sync_once()

                # Wait for next sync interval
                await asyncio.sleep(self.sync_interval)

            except asyncio.CancelledError:
                logger.info("DRC sync loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in sync loop: {e}")
                # Wait a bit before retrying to avoid tight error loops
                await asyncio.sleep(min(self.sync_interval, 10))


# Global DRC client instance
_drc_client: Optional[DRCClient] = None


def get_drc_client() -> DRCClient:
    """获取或创建全局的 DRC 客户端实例。"""
    global _drc_client
    if _drc_client is None:
        try:
            _drc_client = DRCClient(
                registry_base_url=settings.DRC_BASE_URL,
                sync_interval=settings.DRC_CHANGES_PULL_INTERVAL,
                target_types=["acs"],  # Focus on ACS objects for agent discovery
            )
        except Exception as e:
            raise SyncException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_name=SyncError.CLIENT_CONFIG_ERROR,
                error_msg=f"创建DRC客户端失败: {e}",
                input_params={
                    "drc_base_url": settings.DRC_BASE_URL,
                    "sync_interval": settings.DRC_CHANGES_PULL_INTERVAL,
                },
            )
    return _drc_client


async def start_drc_sync():
    """启动 DRC 同步服务。"""
    client = get_drc_client()
    await client.start_background_sync()


async def stop_drc_sync():
    """停止 DRC 同步服务。"""
    global _drc_client
    if _drc_client:
        await _drc_client.stop_background_sync()
        await _drc_client.close()
