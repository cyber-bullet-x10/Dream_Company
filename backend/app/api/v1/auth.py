from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
import uuid
import asyncio
from functools import partial
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from datetime import timedelta, datetime, timezone
from app.database import get_db
from app.models.user import User
from app.models.refresh_token import RefreshToken
from app.schemas.user import UserRegister, UserLogin, UserResponse, TokenResponse, UserProfileUpdate, ActiveRoleUpdate
from app.core.security import get_password_hash, verify_password, create_access_token, create_refresh_token, decode_jwt
from app.core.exceptions import raise_conflict, raise_unauthorized
from app.config import settings
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.supabase_client import supabase, get_supabase_admin
from jose import jwt as jose_jwt, JWTError
import structlog

log = structlog.get_logger()

security = HTTPBearer()
# 로그인하지 않아도 열리는 화면용. 토큰이 없거나 틀려도 401을 내지 않는다.
optional_security = HTTPBearer(auto_error=False)

# Supabase Auth Integration
# Legacy Authlib registrations removed. Using Supabase OAuth via Frontend.


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Supabase JWT 검증 — SUPABASE_JWT_SECRET 있으면 로컬 검증(빠름), 없으면 run_in_executor 폴백"""
    token = credentials.credentials

    user_id: uuid.UUID
    email: str | None
    metadata: dict
    app_meta: dict

    local_verified = False
    if settings.SUPABASE_JWT_SECRET:
        # 로컬 JWT 검증 시도: 네트워크 호출 없이 수 밀리초
        try:
            payload = jose_jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
            )
            user_id = uuid.UUID(payload["sub"])
            email = payload.get("email")
            metadata = payload.get("user_metadata") or {}
            app_meta = payload.get("app_metadata") or {}
            local_verified = True
        except JWTError as e:
            log.warning("jwt_local_decode_failed_fallback", error=str(e), token_preview=token[:10] + "...")

    if not local_verified:
        # 폴백: Supabase 네트워크 호출 (로컬 검증 실패 또는 시크릿 미설정 시)
        try:
            loop = asyncio.get_running_loop()
            user_res = await loop.run_in_executor(None, partial(supabase.auth.get_user, token))
            if not user_res or not user_res.user:
                log.error("auth_failed", token_preview=token[:10] + "...")
                raise_unauthorized("Invalid session or user not found")
        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            log.error("auth_exception", error=str(e), token_preview=token[:10] + "...")
            raise_unauthorized(f"Auth error: {str(e)}")

        supabase_user = user_res.user
        user_id = uuid.UUID(supabase_user.id)
        email = supabase_user.email  # 카카오 로그인 시 None일 수 있음
        metadata = supabase_user.user_metadata or {}
        app_meta = supabase_user.app_metadata or {}

    # Supabase UUID로 조회 (이메일 없는 카카오 유저 지원)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        full_name = (
            metadata.get("full_name")
            or metadata.get("name")
            or metadata.get("nickname")
            or "꿈 참여자"
        )
        provider = app_meta.get("provider", "email")
        user = User(
            id=user_id,
            email=email,
            full_name=full_name,
            role="user",
            roles=["user"],
            oauth_provider=provider if provider != "email" else None,
            # supabase uid = JWT sub = user_id. (이전엔 supabase_user.id를 참조했는데
            # 로컬 JWT 검증 경로에선 supabase_user가 정의되지 않아 신규 유저마다 NameError→500)
            oauth_provider_id=str(user_id),
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        try:
            await db.commit()
            await db.refresh(user)
        except IntegrityError:
            # 동시 첫 요청 경쟁(같은 신규 유저의 병렬 요청) 또는 이미 존재하는 행 →
            # 롤백 후 재조회. 500 대신 정상 유저 반환(멱등).
            await db.rollback()
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user is None and email:
                result = await db.execute(select(User).where(User.email == email))
                user = result.scalar_one_or_none()
            if user is None:
                raise_unauthorized("User provisioning failed")

    if not user.is_active:
        raise_unauthorized("User is inactive")

    return user


def require_role(*allowed_roles: str):
    """특정 role을 '보유한' 유저만 접근 허용하는 FastAPI Depends.

    멀티-role: 활성 role(current_user.role)이 아니라 보유 집합(current_user.roles)을
    기준으로 판정한다. 예) 스폰서로 활성화돼 있어도 writer 역할을 보유했다면
    writer 전용 엔드포인트에 접근 가능. (roles가 비어있는 레거시 행은 active role로 폴백)
    """
    async def role_checker(current_user: User = Depends(get_current_user)):
        held = set(current_user.roles or [current_user.role])
        if held.isdisjoint(allowed_roles):
            log.warning("role_access_denied", user_id=str(current_user.id), roles=list(held), allowed=allowed_roles)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted for this role"
            )
        return current_user
    return role_checker

router = APIRouter(prefix="/auth", tags=["auth"])


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """로그인했으면 사용자, 아니면 None.

    꿈독자 명부처럼 **비로그인도 볼 수 있어야 하는 화면**에서, 로그인한
    사람에게만 「당신」 표시나 응원 버튼을 다르게 주기 위해 쓴다.
    토큰이 없거나 틀렸다고 401을 내면 화면 자체가 막히므로 조용히 None을 준다.
    """
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials=credentials, db=db)
    except Exception:
        return None


@router.post("/register", response_model=UserResponse)
async def register(user_data: UserRegister, db: AsyncSession = Depends(get_db)):
    """Backend Proxy Register: Supabase Admin SDK를 사용하여 유저 생성"""
    try:
        # 1. Supabase Admin API로 유저 생성 (Confirm Email 우회)
        # Note: email_confirm=True로 설정하여 즉시 활성화
        # 보안: 클라이언트가 보낸 role은 신뢰하지 않는다. 가입은 항상 "user"로 시작하며,
        # writer/sponsor 승격은 전용 엔드포인트(POST /writer/apply, POST /sponsor/register)
        # 에서 서버가 결정한다. (이전엔 client role을 그대로 수용 → 권한상승 가능했음)
        role = "user"

        admin_client = get_supabase_admin()
        res = admin_client.auth.admin.create_user({
            "email": str(user_data.email),
            "password": user_data.password,
            "email_confirm": True,
            "user_metadata": {"full_name": user_data.full_name, "role": role}
        })
        
        if not res or not res.user:
            raise HTTPException(status_code=400, detail="Supabase user creation failed")
            
        supabase_user = res.user
        
        # 2. 로컬 DB에 유저 정보 저장 (이미 존재하는지 체크)
        result = await db.execute(select(User).where(User.email == str(user_data.email)))
        user = result.scalar_one_or_none()
        
        if not user:
            user = User(
                id=uuid.UUID(supabase_user.id),
                email=str(user_data.email),
                full_name=user_data.full_name,
                role=role,
                roles=[role],  # 멀티-role: 보유 집합에 활성 role 포함
                is_active=True,
                is_verified=True
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            
        return user
    except Exception as e:
        import structlog
        log = structlog.get_logger()
        log.error("register_proxy_failed", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login", response_model=dict)
async def login(login_data: UserLogin, db: AsyncSession = Depends(get_db)):
    """Backend Proxy Login: Supabase Auth를 통해 세션 획득"""
    try:
        # Supabase API를 직접 호출하여 로그인
        res = supabase.auth.sign_in_with_password({
            "email": str(login_data.email),
            "password": login_data.password
        })
        
        if not res or not res.session:
            raise HTTPException(status_code=401, detail="Invalid email or password")
            
        # 세션 정보 반환 (프론트엔드에서 수동 저장용)
        return {
            "access_token": res.session.access_token,
            "refresh_token": res.session.refresh_token,
            "expires_in": res.session.expires_in,
            "user": {
                "id": res.user.id,
                "email": res.user.email,
                "full_name": res.user.user_metadata.get("full_name", "꿈 참여자")
            }
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """내 정보 조회 (Supabase 토큰 필요)"""
    return current_user


@router.patch("/me", response_model=UserResponse)
async def update_me(
    data: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """이름 업데이트 — 신규 소셜 로그인 유저 온보딩용.

    보안: role은 여기서 변경하지 않는다. 클라이언트가 PATCH로 role을 자가지정하면
    권한상승이 가능했으므로 제거. writer/sponsor 승격은 전용 엔드포인트에서만 일어난다.
    """
    if data.full_name is not None:
        current_user.full_name = data.full_name
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.patch("/active-role", response_model=UserResponse)
async def switch_active_role(
    data: ActiveRoleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """활성 role 전환 — 보유한 역할(roles) 중 하나로만 가능.

    멀티-role 유저가 독자/작가/스폰서 포털을 오갈 때 사용. 보유하지 않은 역할로는
    전환 불가(403). 보유 집합 자체는 전용 지원 엔드포인트로만 늘어난다.
    """
    held = set(current_user.roles or [current_user.role])
    if data.role not in held:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"보유하지 않은 역할입니다: {data.role}. 보유 역할: {sorted(held)}",
        )
    current_user.role = data.role
    await db.commit()
    await db.refresh(current_user)
    log.info("active_role_switched", user_id=str(current_user.id), role=data.role)
    return current_user
