"""기기 등록 — 푸시 알림을 어디로 보낼지 관리한다."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.api.v1.auth import get_current_user
from app.database import get_db
from app.models.device_token import DeviceToken
from app.models.user import User

logger = structlog.get_logger()
router = APIRouter(prefix="/notifications", tags=["notifications"])


class DeviceRegister(BaseModel):
    token: str = Field(min_length=32, max_length=200)
    platform: str = "ios"
    environment: str = "production"  # production | sandbox


@router.post("/devices")
async def register_device(
    body: DeviceRegister,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """기기 토큰 등록. 앱이 켜질 때마다 부른다(멱등).

    같은 토큰이 이미 있으면 소유자를 지금 사용자로 옮긴다. 기기를 다른 계정으로
    쓰기 시작했는데 이전 사용자의 신문 알림이 계속 가면 안 된다.
    """
    if body.environment not in ("production", "sandbox"):
        raise HTTPException(status_code=400, detail="environment 는 production 또는 sandbox 여야 합니다.")

    existing = await db.execute(
        select(DeviceToken).where(DeviceToken.token == body.token)
    )
    device = existing.scalar_one_or_none()

    if device:
        device.user_id = current_user.id
        device.platform = body.platform
        device.environment = body.environment
        device.is_active = True
    else:
        device = DeviceToken(
            id=uuid.uuid4(),
            user_id=current_user.id,
            token=body.token,
            platform=body.platform,
            environment=body.environment,
        )
        db.add(device)

    await db.commit()
    logger.info(
        "device_registered",
        user_id=str(current_user.id), environment=body.environment,
        token=body.token[:12],
    )
    return {"status": "ok"}


@router.delete("/devices/{token}")
async def unregister_device(
    token: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """로그아웃 시 해제. 남의 계정으로 로그인한 뒤 이전 알림이 오는 것을 막는다."""
    res = await db.execute(
        select(DeviceToken).where(
            DeviceToken.token == token,
            DeviceToken.user_id == current_user.id,
        )
    )
    device = res.scalar_one_or_none()
    if device:
        device.is_active = False
        await db.commit()
    # 없어도 200 — 클라이언트가 재시도로 두 번 불러도 오류로 만들지 않는다.
    return {"status": "ok"}
