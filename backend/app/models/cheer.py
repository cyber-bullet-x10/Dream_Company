import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, func, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Cheer(Base):
    """응원 — 같은 꿈을 꾸는 사람에게 보내는 익명 한 줄.

    자유 입력을 받지 않는다. 편집국이 미리 짜둔 문구 중 하나를 고르게 하고
    그 번호만 저장한다. 그래서 이 테이블에는 신원이나 자유 텍스트가 한 글자도
    남지 않는다 — 커뮤니티를 만들되 익명성은 원천적으로 지켜진다.

    받는 쪽에는 「세 사람이 응원을 부쳤습니다」처럼 수만 집계해서 보여준다.
    보낸 사람이 누구인지는 어느 방향으로도 조회되지 않는다.
    """

    __tablename__ = "cheers"
    __table_args__ = (
        # 한 사람이 같은 연재에 여러 번 보내지 못하게 한다. 연타로 숫자를
        # 부풀리면 「세 사람이 응원했다」가 거짓말이 된다.
        UniqueConstraint("from_user_id", "to_order_id", name="uq_cheers_from_to"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    from_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    to_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # 편집국 문구 번호. 자유 텍스트가 아니다.
    template_id: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
