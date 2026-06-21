"""
ACME API 路由

实现 ACME 协议的 API 端点，处理客户端的证书申请、验证、签发等请求。
"""

import base64
import json
import secrets
from typing import Dict, Any
from fastapi import APIRouter, Request, Response, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app.core.db_session import get_session
from app.core.config import Settings, get_settings
from .schemas import (
    ACMEDirectory,
    JWSRequest,
    AccountCreate,
    OrderCreate,
    AuthorizationCreate,
    ChallengeCreate,
)
from .services import (
    get_nonce_service,
    get_account_service,
    get_order_service,
    get_authorization_service,
    get_challenge_service,
    get_certificate_service,
    JWKService,
)
from .agent_registry import get_agent_registry_client
from .http01_validator import get_http01_validation_service
from .jws_verifier import get_jws_verifier
from .models import OrderStatus, AuthorizationStatus, ChallengeStatus, ChallengeType
from .exception import AcmeException, AcmeError
from .utils import (
    parse_protected_header,
    parse_payload,
    ACMEResponse,
)
from app.common.time_utils import beijing_now, format_datetime
from app.common.certificate_model import CertificateStatus

router = APIRouter()


# ================== 工具函数 ==================


def get_configured_acme_base_url(settings: Settings) -> str:
    """获取配置中的 ACME 基础 URL，去除尾部斜杠"""
    return settings.acme_directory_url.rstrip("/")


def create_acme_response(
    data: Dict[str, Any], nonce_service, status_code: int = 200
) -> JSONResponse:
    """创建 ACME 响应"""
    new_nonce = nonce_service.generate_nonce()
    return ACMEResponse(data, status_code).add_nonce(new_nonce).to_json_response()


def parse_jws_request(
    request_data: JWSRequest, nonce_service, expected_url: str = None
) -> tuple[Dict[str, Any], Dict[str, Any], str]:
    """解析并验证 JWS 请求"""
    try:
        # 解码 protected header 和 payload
        protected = parse_protected_header(request_data.protected)
        payload = parse_payload(request_data.payload)

        # 验证 nonce
        verify_nonce(protected, nonce_service)

        # 如果提供了预期URL，验证URL
        if expected_url and protected.get("url") != expected_url:
            raise AcmeException(
                status_code=400,
                error_name=AcmeError.MALFORMED_REQUEST,
                error_msg=f"URL mismatch: expected {expected_url}, got {protected.get('url')}",
            )

        return protected, payload, request_data.signature

    except AcmeException:
        raise
    except Exception as e:
        raise AcmeException(
            status_code=400,
            error_name=AcmeError.MALFORMED_REQUEST,
            error_msg=f"Invalid JWS format: {str(e)}",
        )


def verify_nonce(protected: Dict[str, Any], nonce_service):
    """验证 nonce"""
    nonce = protected.get("nonce")
    if not nonce:
        raise AcmeException(
            status_code=400,
            error_name="BAD_NONCE",
            error_msg="Missing nonce in protected header",
        )

    if not nonce_service.validate_and_consume_nonce(nonce):
        raise AcmeException(
            status_code=400,
            error_name="BAD_NONCE",
            error_msg="Invalid or expired nonce",
        )


def get_account_from_request(protected: Dict[str, Any], account_service) -> Any:
    """从请求中获取账户"""
    if "kid" in protected:
        # 使用账户 URL
        account_url = protected["kid"]
        account_id = account_url.split("/")[-1]
        account = account_service.get_account_by_id(int(account_id))
    elif "jwk" in protected:
        # 使用 JWK
        jwk = protected["jwk"]
        key_id = JWKService.compute_jwk_thumbprint(jwk)
        account = account_service.get_account_by_key_id(key_id)
    else:
        raise AcmeException(
            status_code=400,
            error_name="MALFORMED_REQUEST",
            error_msg="Missing kid or jwk in protected header",
        )

    if not account:
        raise AcmeException(
            status_code=404,
            error_name="ACCOUNT_NOT_FOUND",
            error_msg="Account not found",
        )

    return account


def verify_jws_signature(
    request_data: JWSRequest, protected: Dict[str, Any], account
) -> bool:
    """验证 JWS 签名"""
    try:
        jws_verifier = get_jws_verifier()

        # 重构JWS字符串用于验证
        jws_string = (
            f"{request_data.protected}.{request_data.payload}.{request_data.signature}"
        )

        # 获取账户公钥
        import json

        account_jwk = json.loads(account.public_key)

        # 验证签名（不验证nonce，因为已经在parse_jws_request中验证过了）
        jws_verifier.verify_jws_signature(
            jws_string,
            account_jwk,
            expected_nonce=None,  # 已经验证过了
            expected_url=None,  # 已经验证过了
        )

        return True

    except Exception as e:
        raise AcmeException(
            status_code=400,
            error_name=AcmeError.BAD_SIGNATURE,
            error_msg=f"Invalid signature: {str(e)}",
        )


# ================== API 端点 ==================


@router.get("/directory", response_model=ACMEDirectory)
async def get_directory(
    request: Request, settings: Settings = Depends(get_settings)
) -> ACMEDirectory:
    """获取 ACME 服务目录"""
    base_url = settings.acme_directory_url

    return ACMEDirectory(
        newNonce=f"{base_url}/new-nonce",
        newAccount=f"{base_url}/new-account",
        newOrder=f"{base_url}/new-order",
        revokeCert=f"{base_url}/revoke-cert",
        keyChange=f"{base_url}/key-change",
        meta={
            "termsOfService": settings.acme_terms_of_service,
            "website": settings.acme_website,
            "caaIdentities": settings.acme_caa_identities_list,
            "externalAccountRequired": False,
        },
    )


@router.get("/ca-cert")
async def get_ca_certificate() -> Response:
    """获取 CA 根证书"""
    from app.core.ca_manager import get_ca_manager

    try:
        ca_manager = get_ca_manager()
        ca_cert_pem = ca_manager.get_ca_certificate_pem()

        return Response(
            content=ca_cert_pem,
            media_type="application/x-pem-file",
            headers={
                "Content-Disposition": "attachment; filename=ca.crt",
                "Cache-Control": "public, max-age=86400",  # 缓存1天
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve CA certificate: {str(e)}"
        )


@router.head("/new-nonce")
@router.get("/new-nonce")
async def get_new_nonce(session: Session = Depends(get_session)) -> Response:
    """获取新的 nonce"""
    nonce_service = get_nonce_service(session)
    new_nonce = nonce_service.generate_nonce()

    return Response(
        status_code=200,
        headers={"Replay-Nonce": new_nonce, "Cache-Control": "no-store"},
    )


@router.post("/new-account")
async def create_account(
    request_data: JWSRequest,
    _request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """创建新账户"""
    nonce_service = get_nonce_service(session)
    account_service = get_account_service(session)

    try:
        # 对于新账户请求，不验证URL，因为JWK是首次出现
        protected, payload, signature = parse_jws_request(
            request_data, nonce_service, expected_url=None
        )

        # 验证必须包含 jwk
        if "jwk" not in protected:
            raise AcmeException(
                status_code=400,
                error_name="MALFORMED_REQUEST",
                error_msg="New account request must include jwk",
            )

        jwk = protected["jwk"]
        key_id = JWKService.compute_jwk_thumbprint(jwk)

        # 检查是否是查询已存在账户
        if payload.get("onlyReturnExisting", False):
            existing_account = account_service.get_account_by_key_id(key_id)
            if not existing_account:
                raise AcmeException(
                    status_code=404,
                    error_name="ACCOUNT_NOT_FOUND",
                    error_msg="Account does not exist",
                )

            account = existing_account

            # 对于已存在的账户，验证JWS签名
            verify_jws_signature(request_data, protected, account)
        else:
            # 对于新账户，我们需要验证JWS签名，但账户还不存在
            # 我们可以直接使用protected header中的JWK来验证
            try:
                jws_verifier = get_jws_verifier()
                jws_string = f"{request_data.protected}.{request_data.payload}.{request_data.signature}"
                jws_verifier.verify_jws_signature(
                    jws_string, jwk, expected_nonce=None, expected_url=None
                )
            except Exception as e:
                raise AcmeException(
                    status_code=400,
                    error_name=AcmeError.BAD_SIGNATURE,
                    error_msg=f"Invalid signature for new account: {str(e)}",
                )

            # 创建新账户
            account_data = AccountCreate(
                key_id=key_id,
                public_key=json.dumps(jwk),
                contact=payload.get("contact"),
                terms_of_service_agreed=payload.get("termsOfServiceAgreed", False),
                external_account_binding=payload.get("externalAccountBinding"),
            )

            account = account_service.create_account(account_data)

        base_url = get_configured_acme_base_url(settings)
        account_url = f"{base_url}/acct/{account.id}"

        response_data = {
            "status": account.status,
            "contact": account.contact,
            "termsOfServiceAgreed": account.terms_of_service_agreed,
            "orders": f"{account_url}/orders",
        }

        # 检查账户是否是新创建的
        # 如果账户的created_at时间很近（比如5秒内），则认为是新创建的
        from datetime import timedelta
        from app.common.time_utils import beijing_now, BEIJING_TZ

        account_created_at = account.created_at
        if account_created_at.tzinfo is None:
            account_created_at = account_created_at.replace(tzinfo=BEIJING_TZ)

        is_new_account = (beijing_now() - account_created_at) < timedelta(seconds=5)
        status_code = 201 if is_new_account else 200

        response = create_acme_response(response_data, nonce_service, status_code)
        response.headers["Location"] = account_url

        return response

    except AcmeException:
        raise
    except Exception as e:
        raise AcmeException(
            status_code=500,
            error_name="INTERNAL_ERROR",
            error_msg=f"Account creation failed: {str(e)}",
        )


@router.post("/acct/{account_id}")
async def update_account(
    account_id: int,
    request_data: JWSRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """更新账户信息"""
    nonce_service = get_nonce_service(session)
    account_service = get_account_service(session)

    try:
        protected, payload, signature = parse_jws_request(request_data)
        verify_nonce(protected, nonce_service)

        account = get_account_from_request(protected, account_service)

        if account.id != account_id:
            raise AcmeException(
                status_code=403,
                error_name="UNAUTHORIZED",
                error_msg="Account ID mismatch",
            )

        # 更新账户信息
        update_data = {}
        if "contact" in payload:
            update_data["contact"] = payload["contact"]
        if "status" in payload:
            update_data["status"] = payload["status"]

        if update_data:
            account = account_service.update_account(account, **update_data)

        base_url = get_configured_acme_base_url(settings)
        response_data = {
            "status": account.status,
            "contact": account.contact,
            "termsOfServiceAgreed": account.terms_of_service_agreed,
            "orders": f"{base_url}/acct/{account.id}/orders",
        }

        return create_acme_response(response_data, nonce_service)

    except AcmeException:
        raise
    except Exception as e:
        raise AcmeException(
            status_code=500,
            error_name="INTERNAL_ERROR",
            error_msg=f"Account update failed: {str(e)}",
        )


@router.post("/new-order")
async def create_order(
    request_data: JWSRequest,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """创建新订单"""
    nonce_service = get_nonce_service(session)
    account_service = get_account_service(session)
    order_service = get_order_service(session)
    authorization_service = get_authorization_service(session)
    challenge_service = get_challenge_service(session)
    agent_registry = get_agent_registry_client()

    try:
        # 构造期望的URL
        expected_url = f"{request.url.scheme}://{request.url.netloc}{request.url.path}"

        protected, payload, signature = parse_jws_request(
            request_data, nonce_service, expected_url
        )

        account = get_account_from_request(protected, account_service)

        # 验证JWS签名
        verify_jws_signature(request_data, protected, account)

        # 验证标识符
        identifiers = payload.get("identifiers", [])
        if not identifiers:
            raise AcmeException(
                status_code=400,
                error_name="MALFORMED_REQUEST",
                error_msg="Missing identifiers",
            )

        # 验证所有标识符都是有效的AIC
        validated_agents = []
        for identifier in identifiers:
            if identifier.get("type") != "agent":
                raise AcmeException(
                    status_code=400,
                    error_name="UNSUPPORTED_IDENTIFIER",
                    error_msg=f"Unsupported identifier type: {identifier.get('type')}",
                )

            aic = identifier.get("value")
            if not aic:
                raise AcmeException(
                    status_code=400,
                    error_name="MALFORMED_REQUEST",
                    error_msg="Missing identifier value",
                )

            # 验证AIC并获取Agent信息
            agent_info = await agent_registry.validate_aic_and_get_info(aic)
            if not agent_info:
                raise AcmeException(
                    status_code=400,
                    error_name="INVALID_IDENTIFIER",
                    error_msg=f"Invalid or inactive agent: {aic}",
                )

            # 注意: 在当前实现中，我们假设任何有效的Agent都可以被任何ACME账户申请证书
            # 这简化了流程，避免了额外的所有权验证步骤
            # 实际的权限控制可以在Agent层面或通过其他机制实现

            validated_agents.append(agent_info)

        # 预验证所有Agent端点是否可访问（仅在非Mock模式下进行实际验证）
        http01_validator = get_http01_validation_service()
        for agent_info in validated_agents:
            pre_validation_result = await http01_validator.pre_validate_agent_endpoint(
                agent_info
            )
            if not pre_validation_result.success:
                raise AcmeException(
                    status_code=400,
                    error_name="INVALID_IDENTIFIER",
                    error_msg=f"Agent endpoint validation failed for {agent_info.aic}: {pre_validation_result.error}",
                )

        # 创建订单
        order_data = OrderCreate(
            account_id=account.id,
            identifiers=identifiers,
            not_before=payload.get("notBefore"),
            not_after=payload.get("notAfter"),
        )

        order = order_service.create_order(order_data)

        # 为每个标识符创建授权和挑战
        authorizations = []
        base_url = get_configured_acme_base_url(settings)

        for identifier, agent_info in zip(identifiers, validated_agents):
            # 创建授权
            auth_data = AuthorizationCreate(
                order_id=order.id,
                identifier=identifier,
                expires=order.expires,
            )
            authorization = authorization_service.create_authorization(auth_data)

            # 创建 HTTP-01 挑战
            challenge_data = ChallengeCreate(
                authorization_id=authorization.id,
                type=ChallengeType.HTTP_01,
                token=base64.urlsafe_b64encode(secrets.token_bytes(32))
                .decode("ascii")
                .rstrip("="),
            )
            challenge_service.create_challenge(challenge_data)

            authorizations.append(f"{base_url}/authz/{authorization.authz_id}")

        # 向Agent注册服务通知证书请求
        for agent_info in validated_agents:
            await agent_registry.register_certificate_request(
                agent_info.aic, order.order_id
            )

        # 更新订单的授权列表
        order.authorizations = authorizations
        session.add(order)
        session.commit()

        order_url = f"{base_url}/order/{order.order_id}"

        response_data = {
            "status": order.status,
            "expires": format_datetime(order.expires),
            "identifiers": order.identifiers,
            "authorizations": authorizations,
            "finalize": f"{order_url}/finalize",
        }

        if order.not_before:
            response_data["notBefore"] = format_datetime(order.not_before)
        if order.not_after:
            response_data["notAfter"] = format_datetime(order.not_after)

        response = create_acme_response(response_data, nonce_service, 201)
        response.headers["Location"] = order_url

        return response

    except AcmeException:
        raise
    except Exception as e:
        raise AcmeException(
            status_code=500,
            error_name="INTERNAL_ERROR",
            error_msg=f"Order creation failed: {str(e)}",
        )


@router.post("/order/{order_id}")
async def get_order(
    order_id: str,
    request_data: JWSRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """获取订单状态"""
    nonce_service = get_nonce_service(session)
    account_service = get_account_service(session)
    order_service = get_order_service(session)

    try:
        protected, payload, signature = parse_jws_request(request_data, nonce_service)

        account = get_account_from_request(protected, account_service)
        order = order_service.get_order_by_id(order_id)

        if not order or order.account_id != account.id:
            raise AcmeException(
                status_code=404,
                error_name="ORDER_NOT_FOUND",
                error_msg="Order not found",
            )

        base_url = get_configured_acme_base_url(settings)
        response_data = {
            "status": order.status,
            "expires": format_datetime(order.expires),
            "identifiers": order.identifiers,
            "authorizations": order.authorizations or [],
            "finalize": f"{base_url}/order/{order.order_id}/finalize",
        }

        if order.certificate:
            response_data["certificate"] = order.certificate

        return create_acme_response(response_data, nonce_service)

    except AcmeException:
        raise
    except Exception as e:
        raise AcmeException(
            status_code=500,
            error_name="INTERNAL_ERROR",
            error_msg=f"Order retrieval failed: {str(e)}",
        )


@router.post("/authz/{authz_id}")
async def get_authorization(
    authz_id: str,
    request_data: JWSRequest,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """获取授权信息"""
    nonce_service = get_nonce_service(session)
    account_service = get_account_service(session)
    authorization_service = get_authorization_service(session)

    try:
        protected, payload, signature = parse_jws_request(request_data, nonce_service)

        account = get_account_from_request(protected, account_service)
        authorization = authorization_service.get_authorization_by_id(authz_id)

        if not authorization:
            raise AcmeException(
                status_code=404,
                error_name="AUTHORIZATION_NOT_FOUND",
                error_msg="Authorization not found",
            )

        # 验证账户权限
        if authorization.order.account_id != account.id:
            raise AcmeException(
                status_code=403,
                error_name="UNAUTHORIZED",
                error_msg="Unauthorized access to authorization",
            )

        # 构建挑战列表
        base_url = get_configured_acme_base_url(settings)
        challenges = []

        for challenge in authorization.challenges:
            challenge_data = {
                "type": challenge.type,
                "url": f"{base_url}/challenge/{challenge.challenge_id}",
                "status": challenge.status,
                "token": challenge.token,
            }

            if challenge.validated:
                challenge_data["validated"] = format_datetime(challenge.validated)

            if challenge.error:
                challenge_data["error"] = challenge.error

            challenges.append(challenge_data)

        response_data = {
            "identifier": authorization.identifier,
            "status": authorization.status,
            "expires": format_datetime(authorization.expires),
            "challenges": challenges,
        }

        return create_acme_response(response_data, nonce_service)

    except AcmeException:
        raise
    except Exception as e:
        raise AcmeException(
            status_code=500,
            error_name="INTERNAL_ERROR",
            error_msg=f"Authorization retrieval failed: {str(e)}",
        )


@router.post("/challenge/{challenge_id}")
async def respond_to_challenge(
    challenge_id: str,
    request_data: JWSRequest,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """响应挑战"""
    nonce_service = get_nonce_service(session)
    account_service = get_account_service(session)
    challenge_service = get_challenge_service(session)
    authorization_service = get_authorization_service(session)
    order_service = get_order_service(session)
    http01_validator = get_http01_validation_service()
    agent_registry = get_agent_registry_client()

    try:
        # 构造期望的URL
        expected_url = f"{request.url.scheme}://{request.url.netloc}{request.url.path}"

        protected, payload, signature = parse_jws_request(
            request_data, nonce_service, expected_url
        )

        account = get_account_from_request(protected, account_service)

        # 验证JWS签名
        verify_jws_signature(request_data, protected, account)

        challenge = challenge_service.get_challenge_by_id(challenge_id)

        if not challenge:
            raise AcmeException(
                status_code=404,
                error_name="CHALLENGE_NOT_FOUND",
                error_msg="Challenge not found",
            )

        authorization = challenge.authorization
        if authorization.order.account_id != account.id:
            raise AcmeException(
                status_code=403,
                error_name="UNAUTHORIZED",
                error_msg="Unauthorized access to challenge",
            )

        # 更新挑战状态为处理中
        challenge = challenge_service.update_challenge_status(
            challenge, ChallengeStatus.PROCESSING
        )

        # 执行验证
        if challenge.type == ChallengeType.HTTP_01:
            # 获取Agent信息
            identifier = authorization.identifier
            aic = identifier.get("value")

            agent_info = await agent_registry.validate_aic_and_get_info(aic)
            if not agent_info:
                error = {
                    "type": "urn:ietf:params:acme:error:unauthorized",
                    "detail": f"Agent {aic} is no longer valid or active",
                }
                challenge = challenge_service.update_challenge_status(
                    challenge, ChallengeStatus.INVALID, error
                )
            else:
                # 获取账户的 JWK
                import json

                account_jwk = json.loads(account.public_key)
                key_authorization = JWKService.create_key_authorization(
                    challenge.token, account_jwk
                )

                # 执行HTTP-01验证
                validation_result = await http01_validator.validate_challenge(
                    agent_info, challenge.token, key_authorization
                )

                if validation_result.success:
                    # 验证成功
                    challenge = challenge_service.update_challenge_status(
                        challenge, ChallengeStatus.VALID
                    )
                    authorization = authorization_service.update_authorization_status(
                        authorization, AuthorizationStatus.VALID
                    )

                    # 检查订单是否准备就绪
                    # 获取该订单的所有授权
                    order = order_service.get_order_by_pk(authorization.order_id)
                    authorizations = (
                        authorization_service.get_authorizations_by_order_id(order.id)
                    )

                    # 检查是否所有授权都已经有效
                    all_valid = all(
                        auth.status == AuthorizationStatus.VALID
                        for auth in authorizations
                    )

                    if all_valid and order.status == OrderStatus.PENDING:
                        # 更新订单状态为准备就绪
                        order_service.update_order_status(order, OrderStatus.READY)
                else:
                    # 验证失败
                    error = {
                        "type": "urn:ietf:params:acme:error:unauthorized",
                        "detail": validation_result.error,
                    }
                    challenge = challenge_service.update_challenge_status(
                        challenge, ChallengeStatus.INVALID, error
                    )

        base_url = get_configured_acme_base_url(settings)

        response_data = {
            "type": challenge.type,
            "url": f"{base_url}/challenge/{challenge.challenge_id}",
            "status": challenge.status,
            "token": challenge.token,
        }

        if challenge.validated:
            response_data["validated"] = format_datetime(challenge.validated)

        if challenge.error:
            response_data["error"] = challenge.error

        return create_acme_response(response_data, nonce_service)

    except AcmeException:
        raise
    except Exception as e:
        raise AcmeException(
            status_code=500,
            error_name="INTERNAL_ERROR",
            error_msg=f"Challenge processing failed: {str(e)}",
        )


@router.post("/order/{order_id}/finalize")
async def finalize_order(
    order_id: str,
    request_data: JWSRequest,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """完成订单，签发证书"""
    nonce_service = get_nonce_service(session)
    account_service = get_account_service(session)
    order_service = get_order_service(session)
    certificate_service = get_certificate_service(session)
    agent_registry = get_agent_registry_client()

    try:
        # 构造期望的URL
        expected_url = f"{request.url.scheme}://{request.url.netloc}{request.url.path}"

        protected, payload, signature = parse_jws_request(
            request_data, nonce_service, expected_url
        )

        account = get_account_from_request(protected, account_service)

        # 验证JWS签名
        verify_jws_signature(request_data, protected, account)

        order = order_service.get_order_by_id(order_id)

        if not order or order.account_id != account.id:
            raise AcmeException(
                status_code=404,
                error_name="ORDER_NOT_FOUND",
                error_msg="Order not found",
            )

        if order.status != OrderStatus.READY:
            raise AcmeException(
                status_code=400,
                error_name="ORDER_NOT_READY",
                error_msg="Order is not ready for finalization",
            )

        # 解码 CSR
        csr_data = payload.get("csr")
        if not csr_data:
            raise AcmeException(
                status_code=400, error_name="MALFORMED_REQUEST", error_msg="Missing CSR"
            )

        csr_der = base64.urlsafe_b64decode(csr_data + "==")

        # 验证CSR与订单标识符匹配，并收集Agent信息用于证书签发
        agent_infos = []
        for identifier in order.identifiers:
            aic = identifier.get("value")
            agent_info = await agent_registry.validate_aic_and_get_info(aic)
            if not agent_info:
                raise AcmeException(
                    status_code=400,
                    error_name="INVALID_IDENTIFIER",
                    error_msg=f"Agent {aic} is no longer valid",
                )
            agent_infos.append(agent_info)

        # 更新订单状态为处理中
        order = order_service.update_order_status(order, OrderStatus.PROCESSING)

        # 签发证书 - 传递Agent信息用于构造证书DN
        # 现在返回证书列表（每个Agent一张证书）
        certificates = certificate_service.issue_certificate(
            order, csr_der, agent_infos
        )

        base_url = get_configured_acme_base_url(settings)

        # 更新订单状态为有效
        # 为多证书订单，提供第一张证书的URL作为主要证书URL
        if certificates:
            primary_cert_url = f"{base_url}/cert/{certificates[0].cert_id}"
            order.certificate = primary_cert_url

        order = order_service.update_order_status(order, OrderStatus.VALID)

        # 通知Agent注册服务证书已签发
        for i, agent_info in enumerate(agent_infos):
            cert_id = (
                certificates[i].cert_id
                if i < len(certificates)
                else certificates[0].cert_id
            )
            await agent_registry.notify_certificate_issued(
                agent_info.aic, order.order_id, cert_id
            )

        # 构造响应数据，包含多证书信息
        response_data = {
            "status": order.status,
            "expires": format_datetime(order.expires),
            "identifiers": order.identifiers,
            "authorizations": order.authorizations or [],
            "finalize": f"{base_url}/order/{order.order_id}/finalize",
            "certificate": order.certificate,
        }

        # 如果有多张证书，添加扩展信息
        if len(certificates) > 1:
            cert_urls = [f"{base_url}/cert/{cert.cert_id}" for cert in certificates]
            response_data["certificates"] = cert_urls
            response_data["certificate_count"] = len(certificates)

        return create_acme_response(response_data, nonce_service)

    except AcmeException:
        raise
    except Exception as e:
        raise AcmeException(
            status_code=500,
            error_name="INTERNAL_ERROR",
            error_msg=f"Order finalization failed: {str(e)}",
        )


@router.post("/cert/{cert_id}")
async def get_certificate(
    cert_id: str,
    request_data: JWSRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    """获取证书"""
    nonce_service = get_nonce_service(session)
    account_service = get_account_service(session)
    certificate_service = get_certificate_service(session)
    order_service = get_order_service(session)

    try:
        expected_url = f"{request.url.scheme}://{request.url.netloc}{request.url.path}"
        protected, payload, signature = parse_jws_request(
            request_data, nonce_service, expected_url
        )

        account = get_account_from_request(protected, account_service)
        certificate = certificate_service.get_certificate_by_id(cert_id)

        if not certificate:
            raise AcmeException(
                status_code=404,
                error_name=AcmeError.CERTIFICATE_NOT_FOUND,
                error_msg="Certificate not found",
            )

        # 获取关联的订单来验证访问权限
        order = order_service.get_order_by_pk(certificate.order_id)
        if not order or order.account_id != account.id:
            raise AcmeException(
                status_code=403,
                error_name="UNAUTHORIZED",
                error_msg="Unauthorized access to certificate",
            )

        new_nonce = nonce_service.generate_nonce()

        return Response(
            content=certificate.certificate_pem,
            media_type="application/pem-certificate-chain",
            headers={"Replay-Nonce": new_nonce, "Cache-Control": "no-store"},
        )

    except AcmeException:
        raise
    except Exception as e:
        raise AcmeException(
            status_code=500,
            error_name="INTERNAL_ERROR",
            error_msg=f"Certificate retrieval failed: {str(e)}",
        )


@router.post("/revoke-cert")
async def revoke_certificate(
    request_data: JWSRequest, session: Session = Depends(get_session)
) -> JSONResponse:
    """吊销证书"""
    nonce_service = get_nonce_service(session)
    account_service = get_account_service(session)
    certificate_service = get_certificate_service(session)

    try:
        protected, payload, signature = parse_jws_request(request_data, nonce_service)

        account = get_account_from_request(protected, account_service)

        # 验证JWS签名
        verify_jws_signature(request_data, protected, account)

        # 解码证书
        cert_data = payload.get("certificate")
        if not cert_data:
            raise AcmeException(
                status_code=400,
                error_name="MALFORMED_REQUEST",
                error_msg="Missing certificate",
            )

        try:
            cert_der = base64.urlsafe_b64decode(cert_data + "==")
        except Exception:
            raise AcmeException(
                status_code=400,
                error_name="MALFORMED_REQUEST",
                error_msg="Invalid certificate encoding",
            )

        # 解析证书并提取序列号
        try:
            from cryptography import x509
            from cryptography.hazmat.backends import default_backend

            cert = x509.load_der_x509_certificate(cert_der, default_backend())
            serial_number = f"{cert.serial_number:X}"  # 转换为十六进制字符串

            # 查找数据库中的证书记录
            from sqlmodel import select
            from .models import AcmeCertificate

            statement = select(AcmeCertificate).where(
                AcmeCertificate.serial_number == serial_number
            )
            acme_cert = session.exec(statement).first()

            if not acme_cert:
                raise AcmeException(
                    status_code=404,
                    error_name="CERTIFICATE_NOT_FOUND",
                    error_msg="Certificate not found",
                )

            # 验证证书所有权：检查证书是否属于该账户
            order = acme_cert.order
            if not order or order.account_id != account.id:
                raise AcmeException(
                    status_code=403,
                    error_name="UNAUTHORIZED",
                    error_msg="Certificate does not belong to this account",
                )

            # 检查证书是否已经被吊销
            if acme_cert.status == CertificateStatus.REVOKED:
                raise AcmeException(
                    status_code=400,
                    error_name="ALREADY_REVOKED",
                    error_msg="Certificate is already revoked",
                )

        except AcmeException:
            raise
        except Exception as e:
            raise AcmeException(
                status_code=400,
                error_name="MALFORMED_REQUEST",
                error_msg=f"Invalid certificate format: {str(e)}",
            )

        # 获取吊销原因
        reason_code = payload.get("reason", 0)
        if not isinstance(reason_code, int) or reason_code < 0 or reason_code > 5:
            raise AcmeException(
                status_code=400,
                error_name="MALFORMED_REQUEST",
                error_msg="Invalid revocation reason code",
            )

        # 执行证书吊销
        certificate_service.revoke_certificate(acme_cert, reason_code)

        # 返回成功响应
        response_data = {
            "status": "success",
            "message": "Certificate revoked successfully",
            "revocation_date": format_datetime(beijing_now()),
            "reason": reason_code,
        }

        return create_acme_response(response_data, nonce_service, 200)

    except AcmeException:
        raise
    except Exception as e:
        raise AcmeException(
            status_code=500,
            error_name="INTERNAL_ERROR",
            error_msg=f"Certificate revocation failed: {str(e)}",
        )


@router.post("/key-change")
async def change_key(
    request_data: JWSRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """更换账户密钥"""
    nonce_service = get_nonce_service(session)
    account_service = get_account_service(session)

    try:
        protected, payload, signature = parse_jws_request(request_data, nonce_service)

        account = get_account_from_request(protected, account_service)

        # 验证JWS签名
        verify_jws_signature(request_data, protected, account)

        # 解析内层JWS（新密钥签名的请求）
        if not payload:
            raise AcmeException(
                status_code=400,
                error_name="MALFORMED_REQUEST",
                error_msg="Missing payload in key change request",
            )

        # 内层JWS应该包含账户的新公钥信息
        # payload 应该是一个JWS字符串，使用新密钥签名
        try:
            # 解析内层JWS的protected header来获取新的JWK
            inner_jws_parts = payload.split(".")
            if len(inner_jws_parts) != 3:
                raise ValueError("Invalid inner JWS format")

            inner_protected_b64 = inner_jws_parts[0]
            inner_payload_b64 = inner_jws_parts[1]
            inner_signature_b64 = inner_jws_parts[2]

            # 解码内层protected header
            inner_protected = parse_protected_header(inner_protected_b64)

            if "jwk" not in inner_protected:
                raise AcmeException(
                    status_code=400,
                    error_name="MALFORMED_REQUEST",
                    error_msg="New JWK must be provided in inner JWS",
                )

            new_jwk = inner_protected["jwk"]

            # 验证内层JWS签名（使用新密钥）
            jws_verifier = get_jws_verifier()
            inner_jws_string = payload
            try:
                jws_verifier.verify_jws_signature(
                    inner_jws_string, new_jwk, expected_nonce=None, expected_url=None
                )
            except Exception as e:
                raise AcmeException(
                    status_code=400,
                    error_name="BAD_SIGNATURE",
                    error_msg=f"Invalid signature on inner JWS: {str(e)}",
                )

            # 解码内层payload
            inner_payload = parse_payload(inner_payload_b64)

            # 验证内层payload包含正确的account URL和oldKey
            base_url = get_configured_acme_base_url(settings)
            expected_account_url = f"{base_url}/acct/{account.id}"
            if inner_payload.get("account") != expected_account_url:
                raise AcmeException(
                    status_code=400,
                    error_name="MALFORMED_REQUEST",
                    error_msg="Account URL mismatch in inner payload",
                )

            # 验证oldKey与当前账户密钥匹配
            import json

            current_jwk = json.loads(account.public_key)
            provided_old_key = inner_payload.get("oldKey")

            if not provided_old_key or provided_old_key != current_jwk:
                raise AcmeException(
                    status_code=400,
                    error_name="MALFORMED_REQUEST",
                    error_msg="oldKey does not match current account key",
                )

            # 计算新密钥的指纹
            new_key_id = JWKService.compute_jwk_thumbprint(new_jwk)

            # 检查新密钥是否已被其他账户使用
            existing_account = account_service.get_account_by_key_id(new_key_id)
            if existing_account and existing_account.id != account.id:
                raise AcmeException(
                    status_code=409,
                    error_name="KEY_IN_USE",
                    error_msg="New key is already associated with another account",
                )

            # 更新账户密钥
            account = account_service.update_account(
                account,
                key_id=new_key_id,
                public_key=json.dumps(new_jwk),
            )

        except AcmeException:
            raise
        except Exception as e:
            raise AcmeException(
                status_code=400,
                error_name="MALFORMED_REQUEST",
                error_msg=f"Invalid key change request format: {str(e)}",
            )

        # 构建响应
        base_url = get_configured_acme_base_url(settings)
        response_data = {
            "status": account.status,
            "contact": account.contact,
            "termsOfServiceAgreed": account.terms_of_service_agreed,
            "orders": f"{base_url}/acct/{account.id}/orders",
        }

        return create_acme_response(response_data, nonce_service)

    except AcmeException:
        raise
    except Exception as e:
        raise AcmeException(
            status_code=500,
            error_name="INTERNAL_ERROR",
            error_msg=f"Key change failed: {str(e)}",
        )
