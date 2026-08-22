from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pydantic import BaseModel
import uuid
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.models.order import Order
from app.models.newspaper import Newspaper
from app.models.schedule import PublicationSchedule
from app.models.user import User
from app.models.credit_transaction import CreditTransaction
from app.schemas.order import OrderCreate, OrderResponse, OrderStartResponse
from app.api.v1.auth import get_current_user
from app.core.exceptions import raise_not_found, raise_forbidden
import uuid

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    data: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """꿈 의뢰 생성"""
    # duration_days 검증 (3일=무료 체험, 7/14/30=유료 시리즈)
    if data.duration_days not in [3, 7, 14, 30]:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="기간은 3일, 7일, 14일, 30일 중 선택해야 합니다.")

    # 무료 플랜은 3일 체험만 허용
    if data.payment_type == "free" and data.duration_days != 3:
        raise HTTPException(status_code=400, detail="무료 플랜은 3일 체험 시리즈만 이용 가능합니다.")

    # 유료(크레딧) 플랜은 3일 불가 — 7일 이상
    if data.payment_type != "free" and data.duration_days == 3:
        raise HTTPException(status_code=400, detail="3일 체험은 무료 플랜에서만 이용 가능합니다.")

    # 크레딧 플랜: 잔액 미리 확인
    if data.payment_type == "credits":
        result = await db.execute(select(User).where(User.id == current_user.id))
        user = result.scalar_one_or_none()
        if not user or user.credits < data.duration_days:
            available = user.credits if user else 0
            raise HTTPException(
                status_code=402,
                detail=f"크레딧이 부족합니다. 필요: {data.duration_days}개, 보유: {available}개"
            )

    payment_status = "free" if data.payment_type == "free" else (
        "paid" if data.payment_type == "credits" else "pending"
    )

    order = Order(
        user_id=current_user.id,
        dream_description=data.dream_description,
        protagonist_name=data.protagonist_name,
        target_role=data.target_role,
        target_company=data.target_company,
        supporting_people=[p.model_dump() for p in data.supporting_people],
        duration_days=data.duration_days,
        series_theme=data.series_theme,
        future_year=data.future_year,
        payment_type=data.payment_type,
        payment_status=payment_status,
        writer_type="ai",
        status="draft",
    )
    db.add(order)
    await db.flush()
    await db.refresh(order)

    return _order_to_response(order, 0, 0)


@router.post("/{order_id}/start", response_model=OrderStartResponse)
async def start_order(
    order_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """의뢰 시작 (발행 스케줄 생성 + 오케스트레이터 실행)"""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()

    if not order:
        raise_not_found("의뢰")
    if order.user_id != current_user.id:
        raise_forbidden()
    if order.status not in ["draft"]:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"이미 {order.status} 상태인 의뢰입니다.")

    # 결제 상태 확인 (무료/크레딧 주문은 바로 시작)
    if order.payment_type not in ("free", "credits") and order.payment_status != "paid":
        raise HTTPException(status_code=402, detail="결제가 완료되지 않았습니다.")

    # 크레딧 차감
    if order.payment_type == "credits":
        user_result = await db.execute(select(User).where(User.id == current_user.id))
        user = user_result.scalar_one_or_none()
        if not user or user.credits < order.duration_days:
            available = user.credits if user else 0
            raise HTTPException(
                status_code=402,
                detail=f"크레딧이 부족합니다. 필요: {order.duration_days}개, 보유: {available}개"
            )
        credits_before = user.credits
        user.credits -= order.duration_days
        tx = CreditTransaction(
            user_id=user.id,
            type="consume",
            amount=-order.duration_days,
            credits_before=credits_before,
            credits_after=user.credits,
            description=f"{order.protagonist_name}의 꿈 {order.duration_days}편",
            order_id=order.id,
        )
        db.add(tx)

    # 상태 업데이트 + 발행 스케줄을 '동기적으로' 생성 후 즉시 커밋.
    # 스케줄은 순수 날짜 계산이라 AI가 필요 없다. 이렇게 확정해두면 백그라운드 AI 생성이
    # 실패/지연돼도 주문은 유효한 active 상태 + 스케줄로 남아 매일 8시 cron이 발행을 잇는다.
    # ⚠️ 왜 여기서 명시적 commit 하나: FastAPI는 yield 의존성(get_db)의 커밋을 백그라운드
    # 태스크 '이후'로 미룬다. 예전엔 status 변경/스케줄 생성을 백그라운드에 뒀는데, 그 안의
    # AI 호출이 멈추면 커밋까지 막혀 주문이 draft에 영구히 갇혔다(2026-07-14 장애 원인).
    order.status = "active"
    order.starts_at = datetime.now(timezone.utc)

    tz = ZoneInfo(order.timezone or "Asia/Seoul")
    publish_hour = order.publish_time.hour if order.publish_time else 8
    start_date = datetime.now(tz).replace(
        hour=publish_hour, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)
    for i in range(order.duration_days):
        db.add(PublicationSchedule(
            order_id=order.id,
            episode_number=i + 1,
            scheduled_at=start_date + timedelta(days=i),
            status="pending",
        ))
    await db.commit()

    # 백그라운드(best-effort): 첫 화 즉시 생성. 실패해도 위 상태/스케줄은 이미 확정됨.
    background_tasks.add_task(_process_order_background, str(order.id))

    return OrderStartResponse(
        order_id=order.id,
        status="active",
        schedule_count=order.duration_days,
        sponsors=[],
        message=f"{order.duration_days}일 시리즈가 시작됐습니다! 매일 오전 8시에 꿈신문이 발행됩니다.",
    )


async def _process_order_background(order_id: str):
    """백그라운드(best-effort): 첫 화 즉시 생성 + 비식별 열망 한 줄.

    스케줄과 active 상태는 start_order에서 이미 동기 확정됨. 여기서 실패/지연해도
    주문은 유효하며 나머지 화는 매일 8시 cron이 발행한다. AI 호출이 무한정 멈추는 것을
    막기 위해 전체를 하드 타임아웃으로 감싼다.
    """
    import asyncio as _asyncio
    try:
        await _asyncio.wait_for(_generate_first_episode(order_id), timeout=180)
    except Exception as e:
        import structlog
        structlog.get_logger().warning(
            "first_episode_generation_failed", order_id=order_id, error=str(e)
        )


async def _generate_first_episode(order_id: str):
    from app.database import get_db_session
    from app.agents.editor_in_chief.agent import EditorInChief
    from app.tasks.daily_publish import process_single_schedule
    import asyncio as _asyncio

    async with get_db_session() as db:
        result = await db.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            return

        # 꿈 동료 공간용 비식별 열망 한 줄(이름·사적정보 제거). 실패해도 발행엔 무관.
        if not order.public_aspiration:
            try:
                from app.services.dream_companions import generate_public_aspiration
                order.public_aspiration = await generate_public_aspiration(
                    target_role=order.target_role,
                    dream_description=order.dream_description,
                    future_year=order.future_year,
                    protagonist_name=order.protagonist_name,
                )
                await db.flush()
            except Exception:
                pass

        # 첫 번째 에피소드 즉시 생성 (스케줄은 start_order에서 이미 생성됨)
        first_result = await db.execute(
            select(PublicationSchedule)
            .where(PublicationSchedule.order_id == order.id)
            .order_by(PublicationSchedule.episode_number)
            .limit(1)
        )
        first_schedule = first_result.scalar_one_or_none()
        if first_schedule and first_schedule.status == "pending":
            orchestrator = EditorInChief()
            sem = _asyncio.Semaphore(1)
            await process_single_schedule(db, first_schedule, orchestrator, sem)


@router.get("", response_model=list[OrderResponse])
async def list_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """내 의뢰 목록"""
    result = await db.execute(
        select(Order)
        .where(Order.user_id == current_user.id)
        .order_by(Order.created_at.desc())
    )
    orders = result.scalars().all()

    responses = []
    for order in orders:
        # 신문 수 집계
        total_result = await db.execute(
            select(func.count()).where(Newspaper.order_id == order.id)
        )
        total = total_result.scalar() or 0

        pub_result = await db.execute(
            select(func.count()).where(
                and_(Newspaper.order_id == order.id, Newspaper.status == "published")
            )
        )
        published = pub_result.scalar() or 0

        responses.append(_order_to_response(order, total, published))

    return responses


@router.get("/dream-stats")
async def get_dream_stats(
    role: str = "",
    db: AsyncSession = Depends(get_db),
):
    """같은 꿈(target_role)을 가진 의뢰 수 반환 — 인증 불필요"""
    if not role:
        return {"count": 0}
    result = await db.execute(
        select(func.count(Order.id)).where(
            Order.target_role.ilike(f"%{role}%")
        )
    )
    count = result.scalar() or 0
    return {"count": count}


@router.get("/dream-companions")
async def get_dream_companions(role: str = "", db: AsyncSession = Depends(get_db)):
    """같은 미래를 향한 사람들 — 비식별 열망 목록 + 인원. 인증 불필요.

    개인정보 보호: 이름·원본 꿈 설명은 절대 반환하지 않는다. 저장된 비식별
    열망 한 줄(public_aspiration)과 미래연도만 노출. 실데이터가 적으면 시드로 채운다.
    """
    from app.services.dream_companions import SEED_ASPIRATIONS

    # 같은 분야(target_role) 인원 수
    if role:
        count = await db.scalar(
            select(func.count(Order.id)).where(Order.target_role.ilike(f"%{role}%"))
        ) or 0
    else:
        count = await db.scalar(select(func.count(Order.id))) or 0

    # 실주문의 비식별 열망(최신순). 같은 분야 우선, 부족하면 전체에서 보충.
    real: list[dict] = []
    seen: set[str] = set()

    async def _collect(q):
        res = await db.execute(q)
        for oid, asp, year in res.all():
            if asp and asp not in seen:
                seen.add(asp)
                # id 는 응원을 부칠 대상 식별자다. 불투명한 UUID라 그 자체로
                # 신원을 드러내지 않으며, 이름·꿈 원문은 여전히 나가지 않는다.
                real.append({"id": str(oid), "line": asp, "year": year})

    if role:
        await _collect(
            select(Order.id, Order.public_aspiration, Order.future_year)
            .where(Order.target_role.ilike(f"%{role}%"), Order.public_aspiration.isnot(None))
            .order_by(Order.created_at.desc())
            .limit(5)
        )
    if len(real) < 5:
        await _collect(
            select(Order.id, Order.public_aspiration, Order.future_year)
            .where(Order.public_aspiration.isnot(None))
            .order_by(Order.created_at.desc())
            .limit(5)
        )

    # 시드로 5개까지 채움(실데이터 우선)
    aspirations = real[:5]
    for seed in SEED_ASPIRATIONS:
        if len(aspirations) >= 5:
            break
        if seed["line"] not in seen:
            seen.add(seed["line"])
            # 시드는 실재하는 의뢰가 아니므로 id 가 없다. 앱은 id 가 없는 줄에
            # 응원 버튼을 그리지 않는다.
            aspirations.append({**seed, "id": None})

    # 이번 주 신규(같은 분야)
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    new_q = select(func.count(Order.id)).where(Order.created_at >= week_ago)
    if role:
        new_q = new_q.where(Order.target_role.ilike(f"%{role}%"))
    new_this_week = await db.scalar(new_q) or 0

    return {
        "count": count,
        "aspirations": aspirations,
        "new_this_week": new_this_week,
    }


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """의뢰 상세"""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()

    if not order:
        raise_not_found("의뢰")
    # 의뢰 소유자 or 배정된 작가 or 어드민만 접근 허용
    is_owner = order.user_id == current_user.id
    is_assigned_writer = order.assigned_writer_id == current_user.id
    is_admin = current_user.role == "admin"
    if not (is_owner or is_assigned_writer or is_admin):
        raise_forbidden()

    total_result = await db.execute(
        select(func.count()).where(Newspaper.order_id == order.id)
    )
    total = total_result.scalar() or 0

    pub_result = await db.execute(
        select(func.count()).where(
            and_(Newspaper.order_id == order.id, Newspaper.status == "published")
        )
    )
    published = pub_result.scalar() or 0

    return _order_to_response(order, total, published)


def _order_to_response(order: Order, total: int, published: int) -> OrderResponse:
    return OrderResponse(
        id=order.id,
        user_id=order.user_id,
        dream_description=order.dream_description,
        protagonist_name=order.protagonist_name,
        target_role=order.target_role,
        target_company=order.target_company,
        duration_days=order.duration_days,
        future_year=order.future_year,
        payment_type=order.payment_type,
        payment_status=order.payment_status,
        writer_type=order.writer_type,
        status=order.status,
        created_at=order.created_at,
        starts_at=order.starts_at,
        ends_at=order.ends_at,
        total_newspapers=total,
        published_newspapers=published,
    )

# ============================
# 응원 부치기 — 익명 커뮤니티
# ============================

class CheerCreate(BaseModel):
    to_order_id: uuid.UUID
    template_id: int


@router.get("/dream-companions/templates")
async def get_cheer_templates():
    """편집국이 짜둔 응원 문구. 자유 입력은 받지 않는다."""
    from app.services.cheer_templates import CHEER_TEMPLATES

    return {
        "templates": [
            {"id": k, "text": v} for k, v in sorted(CHEER_TEMPLATES.items())
        ]
    }


@router.post("/dream-companions/cheer", status_code=status.HTTP_201_CREATED)
async def send_cheer(
    body: CheerCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """같은 꿈을 꾸는 사람에게 응원을 부친다.

    보내는 사람의 신원은 받는 쪽에 어떤 형태로도 전달되지 않는다. 저장되는
    것은 문구 번호뿐이라 자유 텍스트가 흘러들 통로 자체가 없다.
    """
    from app.services import cheer_templates
    from app.models.cheer import Cheer

    if not cheer_templates.is_valid(body.template_id):
        raise HTTPException(status_code=400, detail="없는 문구입니다.")

    target = await db.get(Order, body.to_order_id)
    if not target:
        raise HTTPException(status_code=404, detail="그 의뢰를 찾을 수 없습니다.")

    # 자기 자신에게 보내면 「세 사람이 응원했다」가 자화자찬이 된다.
    if target.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="자신의 꿈에는 보낼 수 없습니다.")

    db.add(Cheer(
        from_user_id=current_user.id,
        to_order_id=body.to_order_id,
        template_id=body.template_id,
    ))
    try:
        await db.commit()
    except IntegrityError:
        # 이미 보낸 상대다. 재시도로 두 번 눌린 것일 수 있으니 오류로 만들지
        # 않고 조용히 넘어간다 — UNIQUE 제약이 숫자 부풀리기를 막아준다.
        await db.rollback()
        return {"status": "already_sent"}

    return {"status": "sent"}


@router.get("/dream-companions/inbox")
async def get_cheer_inbox(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """내가 받은 응원. 보낸 사람은 집계에서만 존재한다.

    숫자는 주장이고 받은 한 줄은 증거다. 이 편지함이 「혼자가 아니다」를
    실제로 증명하는 유일한 자리다.
    """
    from app.models.cheer import Cheer
    from app.services import cheer_templates

    my_orders = (await db.execute(
        select(Order.id).where(Order.user_id == current_user.id)
    )).scalars().all()

    if not my_orders:
        return {"received": 0, "senders": 0, "recent": []}

    received = await db.scalar(
        select(func.count(Cheer.id)).where(Cheer.to_order_id.in_(my_orders))
    ) or 0

    # 「몇 사람이」를 말하려면 사람 수를 세야 한다. 같은 사람이 내 연재 둘에
    # 보냈어도 한 사람이다.
    senders = await db.scalar(
        select(func.count(func.distinct(Cheer.from_user_id)))
        .where(Cheer.to_order_id.in_(my_orders))
    ) or 0

    rows = (await db.execute(
        select(Cheer.template_id, Cheer.created_at)
        .where(Cheer.to_order_id.in_(my_orders))
        .order_by(Cheer.created_at.desc())
        .limit(5)
    )).all()

    return {
        "received": received,
        "senders": senders,
        "recent": [
            {
                "template_id": tid,
                "text": cheer_templates.text_of(tid),
                "sent_at": created.isoformat(),
            }
            for tid, created in rows
        ],
    }
