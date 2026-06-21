import logging
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from acps_ca_challenge.schema import AgentAIC, ChallengeToken
from acps_ca_challenge.service import get_challenge, save_challenge
from acps_ca_challenge.exception import ChallengeNotFoundError, ChallengeStorageError

router = APIRouter()
LOGGER = logging.getLogger("challenge_server")


@router.get("/health", tags=["System"])
async def health_check():
    """健康检查端点。"""
    return {"status": "OK"}


@router.get(
    "/{agent_aic}/{token}",
    response_class=PlainTextResponse,
    summary="Get Challenge Response",
    tags=["Challenge"],
    responses={
        200: {"description": "Challenge response found", "content": {"text/plain": {}}},
        404: {"description": "Challenge not found"},
        422: {"description": "Validation Error"},
    },
)
def get_challenge_endpoint(agent_aic: AgentAIC, token: ChallengeToken):
    """
    获取指定 Agent 和 Token 的挑战响应。
    此端点由 CA 服务器在验证期间调用。
    """
    try:
        content = get_challenge(agent_aic, token)
        LOGGER.info(f"Served challenge: AIC={agent_aic} Token={token}")
        return content
    except ChallengeNotFoundError:
        LOGGER.warning(f"Challenge not found: AIC={agent_aic} Token={token}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found"
        )
    except ChallengeStorageError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal Server Error",
        )


@router.post(
    "/{agent_aic}/{token}",
    summary="Set Challenge Response",
    tags=["Challenge"],
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Challenge set successfully"},
        422: {"description": "Validation Error"},
        500: {"description": "Internal Server Error"},
    },
)
async def set_challenge_endpoint(
    agent_aic: AgentAIC,
    token: ChallengeToken,
    request: Request,
):
    """
    设置指定 Agent 和 Token 的挑战响应。
    此端点由 CA 客户端 (Agent) 调用。
    """
    # 将请求体作为文本读取
    body = await request.body()
    payload = body.decode("utf-8").strip()

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty body"
        )

    try:
        save_challenge(agent_aic, token, payload)
        LOGGER.info(f"Set challenge: AIC={agent_aic} Token={token}")
        return PlainTextResponse("Challenge set successfully")
    except ChallengeStorageError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save challenge",
        )
