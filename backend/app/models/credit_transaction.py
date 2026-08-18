import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, func, Uuid, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # purchase | consume | bonus | refund
    amount: Mapped[int] = mapped_column(Integer, nullable=False)   # 양수=충전, 음수=소비
    credits_before: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_after: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)
    stripe_session_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 외부 결제 식별자 (Apple StoreKit transactionId 등). 같은 영수증으로 두 번
    # 지급되는 것을 막기 위해 UNIQUE. Stripe는 위 컬럼을 계속 쓴다.
    external_txn_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    user: Mapped["User"] = relationship("User", back_populates="credit_transactions")  # noqa: F821
