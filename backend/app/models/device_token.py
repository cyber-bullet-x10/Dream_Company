import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, ForeignKey, func, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DeviceToken(Base):
    """푸시 알림을 받을 기기.

    한 사용자가 여러 기기를 쓸 수 있고, 한 기기를 여러 사용자가 번갈아 쓸 수도
    있다(가족 공용 아이패드, 로그아웃 후 다른 계정 로그인). 그래서 토큰을
    유일 키로 두고 user_id 를 갱신한다 — 그래야 이전 사용자의 신문 알림이
    다음 사용자에게 가지 않는다.
    """

    __tablename__ = "device_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # APNs 기기 토큰 (hex 64자). 기기를 지웠다 깔면 새 값이 나온다.
    token: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)

    platform: Mapped[str] = mapped_column(String(10), nullable=False, default="ios")

    # APNs 환경. 개발 빌드(Xcode·TestFlight 이전)는 sandbox, 배포 빌드는 production.
    # 서버가 잘못된 환경으로 보내면 BadDeviceToken 이 돌아온다.
    environment: Mapped[str] = mapped_column(String(12), nullable=False, default="production")

    # APNs 가 410 Unregistered 를 주면 끈다. 지우지 않는 이유는 언제 왜 꺼졌는지
    # 남겨두면 "알림이 안 와요" 문의를 추적할 수 있어서다.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
