import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Integer, func, text, Uuid, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    # 소셜 로그인 유저는 비밀번호가 없을 수 있음
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="user", index=True
    )  # 활성(active) role — 라우팅/포털 결정용. user | writer | sponsor | admin
    # 보유한 역할 집합 (멀티-role 겸직). 활성 role은 항상 이 안에 포함됨.
    roles: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default="{}", default=list
    )

    # 소셜 로그인 제공자 정보
    oauth_provider: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True) # kakao | google | naver
    oauth_provider_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # 멀티테넌시(Sponsor)를 위한 조직 ID
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # 독자 번호 — 가입 순서. 앱의 구독 증서·내 정보에 「제0142호 독자」로 찍힌다.
    # 채번은 DB 시퀀스에 맡긴다. 파이썬에서 COUNT(*)+1로 계산하면
    # 동시 가입 시 같은 번호가 두 명에게 나간다.
    reader_no: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        unique=True,
        server_default=text("nextval('users_reader_no_seq')"),
    )

    # 크레딧 잔액
    credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # 구독 정보 (레거시)
    subscription_plan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    subscription_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # 관계
    orders: Mapped[list["Order"]] = relationship(  # noqa: F821
        "Order", back_populates="user", foreign_keys="Order.user_id"
    )
    assigned_orders: Mapped[list["Order"]] = relationship(  # noqa: F821
        "Order", back_populates="assigned_writer", foreign_keys="Order.assigned_writer_id"
    )
    writer_profile: Mapped["WriterProfile | None"] = relationship(  # noqa: F821
        "WriterProfile", back_populates="user", uselist=False
    )
    sponsor: Mapped["Sponsor | None"] = relationship(  # noqa: F821
        "Sponsor", back_populates="user", uselist=False
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    credit_transactions: Mapped[list["CreditTransaction"]] = relationship(  # noqa: F821
        "CreditTransaction", back_populates="user", cascade="all, delete-orphan"
    )
