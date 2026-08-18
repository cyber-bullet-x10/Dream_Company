"""
Stripe 결제 API
- POST /payment/checkout-session        : (레거시) 의뢰별 Stripe Checkout
- POST /payment/credits/checkout        : 크레딧 팩 구매 Stripe Checkout
- GET  /payment/credits/packages        : 크레딧 팩 목록
- POST /payment/webhook                 : Stripe 웹훅 (결제 완료 처리)
- GET  /payment/session/{session_id}    : 세션 상태 조회
"""
import uuid
import asyncio
import stripe
from datetime import datetime, timezone
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.models.order import Order
from app.models.user import User
from app.models.credit_transaction import CreditTransaction
from app.models.sponsor import Sponsor, SponsorSlot
from app.api.v1.auth import get_current_user
from app.config import settings
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/payment", tags=["payment"])

# 기간별 가격 (레거시 — 의뢰별 결제)
PLAN_PRICES: dict[int, int] = {
    7:  9_900,
    14: 19_900,
    30: 39_900,
}

# 크레딧 팩 정의
CREDIT_PACKAGES: dict[str, dict] = {
    "starter": {"credits": 10,  "price_krw": 4_900,  "label": "스타터",  "per_credit": 490},
    "popular": {"credits": 30,  "price_krw": 12_900, "label": "인기",    "per_credit": 430},
    "power":   {"credits": 100, "price_krw": 39_900, "label": "파워",    "per_credit": 399},
}


# ─────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────

def _sync_create_stripe_session(
    metadata: dict,
    line_item_name: str,
    line_item_desc: str,
    amount: int,
    success_url: str,
    cancel_url: str,
) -> tuple[str, str]:
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "krw",
                "product_data": {"name": line_item_name, "description": line_item_desc},
                "unit_amount": amount,
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata,
        locale="ko",
    )
    return session.url, session.id


async def _credit_checkout(metadata: dict, name: str, desc: str, amount: int,
                           success_url: str, cancel_url: str) -> tuple[str, str]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: _sync_create_stripe_session(metadata, name, desc, amount, success_url, cancel_url),
    )


# ─────────────────────────────────────────────
# PortOne(아임포트) v2 — 의뢰 프리미엄 결제
# ─────────────────────────────────────────────

class PortoneCompleteRequest(BaseModel):
    payment_id: str          # PortOne 결제번호 (프론트 SDK가 반환)
    order_id: uuid.UUID


@router.get("/portone/config")
async def portone_public_config():
    """프론트가 결제 가능 여부/가격을 확인하는 공개 설정."""
    return {
        "enabled": bool(settings.PORTONE_API_SECRET and settings.PORTONE_STORE_ID),
        "plan_prices": PLAN_PRICES,
    }


@router.post("/portone/complete")
async def portone_complete(
    body: PortoneCompleteRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """PortOne 결제 완료 후 서버 검증 → 주문 결제완료 + 발행 시작.

    보안: 클라이언트의 '결제 성공' 신호를 믿지 않고, payment_id로 PortOne API를
    직접 조회해 status=PAID + 금액 일치를 서버가 확인한 뒤에만 paid 처리한다.
    """
    if not (settings.PORTONE_API_SECRET and settings.PORTONE_STORE_ID):
        raise HTTPException(status_code=503, detail="결제 서비스가 설정되지 않았습니다.")

    result = await db.execute(select(Order).where(Order.id == body.order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
    if order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="권한이 없습니다.")
    if order.payment_status == "paid":
        return {"status": "already_paid", "order_id": str(order.id)}  # 멱등

    # PortOne 서버 검증
    from app.services.portone_service import verify_payment
    loop = asyncio.get_event_loop()
    v = await loop.run_in_executor(None, lambda: verify_payment(body.payment_id))
    if not v["ok"] or v["status"] != "PAID":
        raise HTTPException(status_code=402, detail=f"결제 검증 실패: {v.get('error') or v.get('status')}")

    expected = PLAN_PRICES.get(order.duration_days, 9_900)
    if v["amount"] != expected:
        logger.warning("portone_amount_mismatch", order_id=str(order.id),
                       expected=expected, actual=v["amount"])
        raise HTTPException(status_code=400, detail=f"결제 금액이 일치하지 않습니다 (기대 {expected:,}원).")

    # 결제 완료 처리
    order.payment_status = "paid"
    order.imp_uid = body.payment_id
    order.amount_krw = v["amount"]
    method = v["raw"].get("method")
    order.payment_method = method.get("type") if isinstance(method, dict) else None
    if order.status == "draft":
        order.status = "active"
        order.starts_at = datetime.now(timezone.utc)
    await db.commit()

    # 발행 시작 (스케줄 생성 + 첫 화 즉시 생성)
    from app.api.v1.orders import _process_order_background
    background_tasks.add_task(_process_order_background, str(order.id))

    logger.info("portone_payment_confirmed", order_id=str(order.id), amount=v["amount"])
    return {"status": "paid", "order_id": str(order.id)}


# ─────────────────────────────────────────────
# 크레딧 팩 API
# ─────────────────────────────────────────────

@router.get("/credits/packages")
async def list_credit_packages():
    """크레딧 팩 목록 반환"""
    return [
        {"id": k, **v}
        for k, v in CREDIT_PACKAGES.items()
    ]


# ─────────────────────────────────────────────
# Apple In-App Purchase (iOS 전용)
# ─────────────────────────────────────────────

# App Store Connect에 등록할 상품 ID ↔ 크레딧 팩 매핑.
# 상품 ID는 App Store Connect에서 만든 것과 정확히 일치해야 한다.
APPLE_PRODUCTS: dict[str, str] = {
    "com.dreamnewspaper.credits.starter": "starter",
    "com.dreamnewspaper.credits.popular": "popular",
    "com.dreamnewspaper.credits.power": "power",
}


class AppleVerifyRequest(BaseModel):
    transaction_id: str
    product_id: str


@router.post("/apple/verify")
async def verify_apple_purchase(
    body: AppleVerifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """StoreKit 결제를 Apple에 확인하고 크레딧을 지급한다.

    클라이언트가 보낸 transaction_id를 App Store Server API로 조회해 실제 결제인지,
    우리 앱 것인지, 환불되지 않았는지 확인한 뒤에만 지급한다.

    중복 지급은 `credit_transactions.external_txn_id`의 UNIQUE 제약으로 막는다.
    조회 후 삽입 사이에 같은 요청이 두 번 들어와도 DB가 두 번째를 거부한다.
    """
    from app.services import apple_iap

    package_id = APPLE_PRODUCTS.get(body.product_id)
    if not package_id:
        raise HTTPException(status_code=400, detail="알 수 없는 상품입니다.")

    pkg = CREDIT_PACKAGES[package_id]
    txn_key = apple_iap.new_txn_key(body.transaction_id)

    # 이미 처리된 영수증이면 조용히 현재 잔액만 돌려준다.
    # 네트워크 재시도로 같은 요청이 두 번 오는 건 정상이므로 오류로 만들지 않는다.
    existing = await db.execute(
        select(CreditTransaction).where(
            CreditTransaction.external_txn_id == txn_key
        )
    )
    if existing.scalar_one_or_none():
        logger.info("apple_iap_already_granted", txn=txn_key)
        return {
            "status": "already_processed",
            "credits": current_user.credits,
            "credits_added": 0,
        }

    try:
        txn = await apple_iap.fetch_transaction(body.transaction_id)
        apple_iap.validate_transaction(txn, body.product_id)
    except apple_iap.AppleVerificationError as e:
        logger.warning("apple_iap_verify_failed", error=str(e), txn=txn_key)
        raise HTTPException(status_code=402, detail=str(e))

    credits_to_add = pkg["credits"]
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one()

    credits_before = user.credits
    user.credits += credits_to_add

    db.add(CreditTransaction(
        user_id=user.id,
        type="purchase",
        amount=credits_to_add,
        credits_before=credits_before,
        credits_after=user.credits,
        description=f"{pkg['label']} 팩 ({credits_to_add}크레딧) — App Store",
        external_txn_id=txn_key,
    ))

    try:
        await db.commit()
    except IntegrityError:
        # UNIQUE 충돌 = 동시에 들어온 같은 영수증. 다른 요청이 이미 지급했다.
        await db.rollback()
        fresh = await db.execute(select(User).where(User.id == current_user.id))
        u = fresh.scalar_one()
        logger.info("apple_iap_race_resolved", txn=txn_key)
        return {
            "status": "already_processed",
            "credits": u.credits,
            "credits_added": 0,
        }

    logger.info(
        "apple_iap_granted",
        user_id=str(user.id),
        credits_added=credits_to_add,
        total=user.credits,
        txn=txn_key,
    )
    return {
        "status": "ok",
        "credits": user.credits,
        "credits_added": credits_to_add,
    }


@router.post("/credits/checkout")
async def create_credit_checkout(
    package_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """크레딧 팩 Stripe Checkout 세션 생성"""
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="결제 서비스가 설정되지 않았습니다.")

    pkg = CREDIT_PACKAGES.get(package_id)
    if not pkg:
        raise HTTPException(status_code=400, detail="존재하지 않는 크레딧 팩입니다.")

    stripe.api_key = settings.STRIPE_SECRET_KEY

    success_url = f"{settings.FRONTEND_URL}/payment/credits/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url  = f"{settings.FRONTEND_URL}/credits"

    metadata = {
        "type": "credit_pack",
        "package_id": package_id,
        "user_id": str(current_user.id),
        "credits": str(pkg["credits"]),
    }

    checkout_url, session_id = await _credit_checkout(
        metadata=metadata,
        name=f"꿈신문사 크레딧 {pkg['credits']}개 ({pkg['label']})",
        desc=f"신문 {pkg['credits']}편을 읽을 수 있는 크레딧입니다. (편당 {pkg['per_credit']}원)",
        amount=pkg["price_krw"],
        success_url=success_url,
        cancel_url=cancel_url,
    )

    logger.info("credit_checkout_created", user_id=str(current_user.id), package=package_id, session_id=session_id)
    return {"checkout_url": checkout_url, "session_id": session_id}


@router.get("/credits/balance")
async def get_credit_balance(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """현재 크레딧 잔액 조회"""
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one_or_none()
    credits = user.credits if user else 0

    # 최근 거래 내역 10건
    tx_result = await db.execute(
        select(CreditTransaction)
        .where(CreditTransaction.user_id == current_user.id)
        .order_by(CreditTransaction.created_at.desc())
        .limit(10)
    )
    transactions = tx_result.scalars().all()

    return {
        "credits": credits,
        "transactions": [
            {
                "id": str(tx.id),
                "type": tx.type,
                "amount": tx.amount,
                "credits_before": tx.credits_before,
                "credits_after": tx.credits_after,
                "description": tx.description,
                "created_at": tx.created_at.isoformat(),
            }
            for tx in transactions
        ],
    }


# ─────────────────────────────────────────────
# Stripe 웹훅
# ─────────────────────────────────────────────

@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Stripe 웹훅 — 결제 완료 이벤트 처리"""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    stripe.api_key = settings.STRIPE_SECRET_KEY

    if settings.STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
        except stripe.errors.SignatureVerificationError:
            logger.warning("stripe_webhook_invalid_signature")
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        import json
        event = json.loads(payload)

    event_type = event.get("type")
    logger.info("stripe_webhook_received", event_type=event_type)

    if event_type == "checkout.session.completed":
        session_obj = event["data"]["object"]
        metadata = session_obj.get("metadata", {})
        payment_intent = session_obj.get("payment_intent", "")

        if metadata.get("type") == "credit_pack":
            await _handle_credit_purchase(db, session_obj, metadata, payment_intent)
        elif metadata.get("type") == "sponsor_slot":
            await _handle_sponsor_slot_purchase(db, metadata, payment_intent)
        else:
            await _handle_order_payment(db, metadata, payment_intent)

    return {"status": "ok"}


async def _handle_credit_purchase(db: AsyncSession, session_obj: dict, metadata: dict, payment_intent: str):
    """크레딧 팩 구매 완료 처리"""
    user_id_str = metadata.get("user_id")
    credits_str = metadata.get("credits", "0")
    session_id = session_obj.get("id", "")

    if not user_id_str:
        return

    try:
        user_uuid = uuid.UUID(user_id_str)
        credits_to_add = int(credits_str)
    except (ValueError, TypeError):
        return

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if not user:
        return

    credits_before = user.credits
    user.credits += credits_to_add
    credits_after = user.credits

    tx = CreditTransaction(
        user_id=user.id,
        type="purchase",
        amount=credits_to_add,
        credits_before=credits_before,
        credits_after=credits_after,
        description=f"크레딧 {credits_to_add}개 구매",
        stripe_session_id=session_id,
    )
    db.add(tx)
    await db.commit()

    logger.info("credit_purchase_confirmed", user_id=user_id_str, credits_added=credits_to_add, total=credits_after)


async def _handle_order_payment(db: AsyncSession, metadata: dict, payment_intent: str):
    """의뢰별 결제 완료 처리 (레거시)"""
    order_id_str = metadata.get("order_id")
    if not order_id_str:
        return

    try:
        order_uuid = uuid.UUID(order_id_str)
    except ValueError:
        return

    result = await db.execute(select(Order).where(Order.id == order_uuid))
    order = result.scalar_one_or_none()
    if order and order.payment_status != "paid":
        order.payment_status = "paid"
        order.stripe_payment_intent_id = payment_intent
        await db.commit()
        logger.info("stripe_payment_confirmed", order_id=order_id_str)


# ─────────────────────────────────────────────
# 스폰서 슬롯 Stripe Checkout
# ─────────────────────────────────────────────

PRICE_NATIVE  = 100  # 원/노출 — 네이티브 본문 삽입
PRICE_SIDEBAR = 30   # 원/노출 — 사이드바 광고 박스


@router.post("/sponsor/checkout")
async def create_sponsor_slot_checkout(
    native_qty: int = 0,
    native_text: str = "",
    sidebar_qty: int = 0,
    sidebar_text: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """스폰서 광고 슬롯 구매 Stripe Checkout 세션 생성"""
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="결제 서비스가 설정되지 않았습니다.")

    if native_qty < 0 or sidebar_qty < 0:
        raise HTTPException(status_code=400, detail="수량은 0 이상이어야 합니다.")
    if native_qty == 0 and sidebar_qty == 0:
        raise HTTPException(status_code=400, detail="구매 수량을 입력하세요.")
    if native_qty > 0 and not native_text.strip():
        raise HTTPException(status_code=400, detail="네이티브 삽입 텍스트를 입력하세요.")

    total_amount = native_qty * PRICE_NATIVE + sidebar_qty * PRICE_SIDEBAR
    stripe.api_key = settings.STRIPE_SECRET_KEY

    success_url = f"{settings.FRONTEND_URL}/payment/sponsor/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url  = f"{settings.FRONTEND_URL}/sponsor/slots"

    metadata = {
        "type":        "sponsor_slot",
        "user_id":     str(current_user.id),
        "native_qty":  str(native_qty),
        "native_text": native_text[:490],
        "sidebar_qty": str(sidebar_qty),
        "sidebar_text": sidebar_text[:490],
    }

    desc_parts = []
    if native_qty > 0:
        desc_parts.append(f"네이티브 {native_qty}회({native_qty * PRICE_NATIVE:,}원)")
    if sidebar_qty > 0:
        desc_parts.append(f"사이드바 {sidebar_qty}회({sidebar_qty * PRICE_SIDEBAR:,}원)")

    loop = asyncio.get_event_loop()
    checkout_url, session_id = await loop.run_in_executor(
        None,
        lambda: _sync_create_stripe_session(
            metadata=metadata,
            line_item_name="꿈신문사 광고 슬롯",
            line_item_desc=" + ".join(desc_parts),
            amount=total_amount,
            success_url=success_url,
            cancel_url=cancel_url,
        ),
    )

    logger.info("sponsor_checkout_created", user_id=str(current_user.id), total=total_amount, session_id=session_id)
    return {"checkout_url": checkout_url, "session_id": session_id}


async def _handle_sponsor_slot_purchase(db: AsyncSession, metadata: dict, payment_intent: str):
    """스폰서 슬롯 구매 완료 처리 — 웹훅에서 호출"""
    user_id_str = metadata.get("user_id")
    native_qty  = int(metadata.get("native_qty",  "0") or "0")
    native_text = metadata.get("native_text", "")
    sidebar_qty = int(metadata.get("sidebar_qty", "0") or "0")
    sidebar_text = metadata.get("sidebar_text", "")

    if not user_id_str:
        return
    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError:
        return

    sponsor_result = await db.execute(select(Sponsor).where(Sponsor.user_id == user_uuid))
    sponsor = sponsor_result.scalar_one_or_none()
    if not sponsor:
        logger.warning("sponsor_slot_webhook_no_sponsor", user_id=user_id_str)
        return

    if native_qty > 0 and native_text:
        db.add(SponsorSlot(
            sponsor_id=sponsor.id,
            slot_type="company_name",
            variable_value=native_text,
            purchased_quantity=native_qty,
            remaining_quantity=native_qty,
            price_per_unit=PRICE_NATIVE,
            total_amount=native_qty * PRICE_NATIVE,
            payment_status="paid",
            is_auto_matched=True,
        ))

    if sidebar_qty > 0:
        db.add(SponsorSlot(
            sponsor_id=sponsor.id,
            slot_type="sidebar",
            variable_value=sidebar_text or "",
            purchased_quantity=sidebar_qty,
            remaining_quantity=sidebar_qty,
            price_per_unit=PRICE_SIDEBAR,
            total_amount=sidebar_qty * PRICE_SIDEBAR,
            payment_status="paid",
            is_auto_matched=True,
        ))

    await db.commit()
    logger.info("sponsor_slot_purchase_confirmed", sponsor_id=str(sponsor.id),
                native=native_qty, sidebar=sidebar_qty)


# ─────────────────────────────────────────────
# 레거시: 의뢰별 Stripe Checkout
# ─────────────────────────────────────────────

@router.post("/checkout-session")
async def create_checkout_session(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """(레거시) 의뢰별 Stripe Checkout"""
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="결제 서비스가 설정되지 않았습니다.")

    stripe.api_key = settings.STRIPE_SECRET_KEY

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
    if order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="권한이 없습니다.")
    if order.payment_status == "paid":
        raise HTTPException(status_code=400, detail="이미 결제 완료된 주문입니다.")

    amount = PLAN_PRICES.get(order.duration_days, 9_900)
    success_url = f"{settings.FRONTEND_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url  = f"{settings.FRONTEND_URL}/payment/cancel?order_id={order_id}"

    loop = asyncio.get_event_loop()
    checkout_url, session_id = await loop.run_in_executor(
        None,
        lambda: _sync_create_stripe_session(
            metadata={"order_id": str(order_id)},
            line_item_name=f"꿈신문사 {order.duration_days}일 시리즈",
            line_item_desc="기자단이 매일 오전 8시 꿈 신문을 발행합니다.",
            amount=amount,
            success_url=success_url,
            cancel_url=cancel_url,
        ),
    )

    order.stripe_session_id = session_id
    await db.commit()

    logger.info("stripe_checkout_created", order_id=str(order_id), session_id=session_id)
    return {"checkout_url": checkout_url, "session_id": session_id}


@router.get("/session/{session_id}")
async def get_session_order(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stripe session_id로 연결된 order 상태 조회"""
    result = await db.execute(select(Order).where(Order.stripe_session_id == session_id))
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
    if order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    return {
        "order_id": str(order.id),
        "payment_status": order.payment_status,
        "status": order.status,
        "duration_days": order.duration_days,
    }
