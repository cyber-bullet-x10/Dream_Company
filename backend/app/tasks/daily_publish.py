"""
매일 오전 8시 KST 자동 발행 배치 작업.
APScheduler를 사용해 pending 상태의 스케줄을 처리합니다.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, and_, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db_session
from app.models.schedule import PublicationSchedule
from app.models.order import Order
from app.models.newspaper import Newspaper
from app.models.sponsor import SponsorSlot
from app.agents.editor_in_chief.agent import EditorInChief
from app.agents.base_agent import reset_usage_tracking, get_usage_tracking
from app.config import settings
from app.models.user import User
from app.core import progress_store
import structlog

logger = structlog.get_logger()

# 글로벌 스케줄러 인스턴스
scheduler = AsyncIOScheduler(timezone=settings.PUBLISH_TIMEZONE)


async def process_single_schedule(
    db: AsyncSession,
    schedule: PublicationSchedule,
    orchestrator: EditorInChief,
    semaphore: asyncio.Semaphore,
):
    """단일 스케줄 처리"""
    async with semaphore:
        try:
            # 토큰 실측 집계 시작 (이 신문 1편 파이프라인 전체: 스폰서매칭+작성+요약+SNS)
            reset_usage_tracking()

            # 처리 중으로 상태 변경
            schedule.status = "processing"
            await db.flush()

            await progress_store.emit(
                str(schedule.order_id), "starting", "편집국이 꿈을 분석하고 있습니다"
            )

            # 의뢰 정보 로드
            order_result = await db.execute(
                select(Order).where(Order.id == schedule.order_id)
            )
            order = order_result.scalar_one_or_none()
            if not order:
                schedule.status = "failed"
                schedule.error_message = "Order not found"
                return

            # 이전 편 요약 로드
            previous_summary = None
            if schedule.episode_number > 1:
                prev_result = await db.execute(
                    select(Newspaper).where(
                        and_(
                            Newspaper.order_id == order.id,
                            Newspaper.episode_number == schedule.episode_number - 1,
                        )
                    )
                )
                prev_newspaper = prev_result.scalar_one_or_none()
                if prev_newspaper and prev_newspaper.sidebar_content:
                    previous_summary = prev_newspaper.sidebar_content.get("episode_summary", "")

            # 의뢰를 dict로 변환 (스폰서 매칭보다 먼저 생성해야 함)
            order_dict = {
                "id": str(order.id),
                "protagonist_name": order.protagonist_name,
                "dream_description": order.dream_description,
                "target_role": order.target_role,
                "target_company": order.target_company,
                "duration_days": order.duration_days,
                "future_year": order.future_year,
                "timezone": order.timezone,
                "publish_time": str(order.publish_time),
                "writer_type": order.writer_type,
            }

            # 스폰서 매칭: AdSales 에이전트로 최적 스폰서 선택
            sponsor_company = order.target_company
            sponsor_data = None
            try:
                matched = await orchestrator.ad_sales.find_sponsors(order_dict)
                if matched:
                    top = matched[0]
                    sponsor_company = top.get("company_name", order.target_company)
                    sponsor_data = top
                    logger.info("sponsor_matched_for_publish", company=sponsor_company)
            except Exception as e:
                logger.warning("sponsor_match_skipped", error=str(e))

            await progress_store.emit(
                str(schedule.order_id),
                "sponsor_matching",
                "맞춤 스폰서를 찾았습니다",
                sponsor_company=sponsor_company,
            )

            # 신문 생성 (품질 검수 루프 제거 — 직접 생성)
            # 품질 검수는 v2에서 규칙 기반(LLM 없이)으로 재도입 예정
            scheduled_date = schedule.scheduled_at.astimezone(ZoneInfo(order.timezone))

            await progress_store.emit(
                str(schedule.order_id), "writing", "기자단이 기사를 작성하고 있습니다"
            )

            newspaper_content = await orchestrator.generate_single_newspaper(
                order=order_dict,
                episode=schedule.episode_number,
                scheduled_date=scheduled_date,
                sponsor_company=sponsor_company,
                previous_summary=previous_summary,
            )

            # 토큰 실측 집계 읽기 (파이프라인 전체 합산)
            _usage = get_usage_tracking() or {"input": 0, "output": 0}

            # 유료 슬롯 확보 + 차감.
            #
            # 이전에는 sponsor_slot_id를 한 번도 채우지 않아서, (1) 광고주가 구매한
            # 슬롯이 영원히 소진되지 않고 (2) 스폰서 대시보드의 노출 수가 항상 0으로
            # 집계됐다(sponsor.py의 Newspaper.sponsor_slot_id.in_(...) 조회).
            # 여기서 연결해야 수익화 루프가 닫힌다.
            #
            # 차감은 조건부 UPDATE 한 방으로 한다. 읽어서 검사하고 빼는 방식은
            # 안 된다 — 발행 배치는 스케줄마다 별도 세션으로 동시에 돌기 때문에
            # (process_schedule_isolated 참고), 남은 수량이 1인 슬롯을 두 회차가
            # 동시에 읽으면 둘 다 통과해 하나를 두 번 팔게 된다.
            # WHERE remaining_quantity > 0 을 UPDATE에 실으면 행 잠금이 걸려
            # 한쪽만 이긴다. RETURNING이 비면 진 쪽이다.
            #
            # 신문 INSERT보다 먼저 확보해야 「광고」 표기와 실제 차감이 어긋나지
            # 않는다. 실패하면 같은 트랜잭션이 롤백되므로 수량도 함께 되돌아간다.
            claimed_slot_id = None
            raw_slot_id = sponsor_data.get("slot_id") if sponsor_data else None
            if raw_slot_id:
                try:
                    slot_uuid = uuid.UUID(str(raw_slot_id))
                except ValueError:
                    slot_uuid = None
                    logger.warning("sponsor_slot_id_invalid", slot_id=str(raw_slot_id))

                if slot_uuid:
                    claimed = await db.execute(
                        update(SponsorSlot)
                        .where(
                            SponsorSlot.id == slot_uuid,
                            SponsorSlot.remaining_quantity > 0,
                        )
                        .values(
                            remaining_quantity=SponsorSlot.remaining_quantity - 1
                        )
                        .returning(SponsorSlot.remaining_quantity)
                    )
                    remaining = claimed.scalar_one_or_none()
                    if remaining is not None:
                        claimed_slot_id = slot_uuid
                        logger.info(
                            "sponsor_slot_consumed",
                            slot_id=str(slot_uuid),
                            company=sponsor_company,
                            remaining=remaining,
                        )
                    else:
                        # 매칭과 발행 사이에 다른 회차가 마지막 수량을 가져갔다.
                        # 기사는 그대로 나가되 유료 표기는 하지 않는다.
                        logger.info(
                            "sponsor_slot_exhausted",
                            slot_id=str(slot_uuid),
                            company=sponsor_company,
                        )

            # DB에 신문 저장
            newspaper = Newspaper(
                order_id=order.id,
                episode_number=schedule.episode_number,
                future_date=newspaper_content["future_date"],
                future_date_label=newspaper_content["future_date_label"],
                headline=newspaper_content.get("headline"),
                subhead=newspaper_content.get("subhead"),
                lead_paragraph=newspaper_content.get("lead_paragraph"),
                body_content=newspaper_content.get("body_content"),
                sidebar_content={
                    **newspaper_content.get("sidebar", {}),
                    "episode_summary": newspaper_content.get("episode_summary", ""),
                },
                raw_content=newspaper_content.get("raw_content"),
                variables_used={
                    "protagonist": order.protagonist_name,
                    "company": order.target_company,
                    "sponsor": sponsor_company,
                    "sponsor_industry": sponsor_data.get("industry", "") if sponsor_data else "",
                    "sponsor_reason": sponsor_data.get("reason", "") if sponsor_data else "",
                    # 실제로 슬롯을 확보했을 때만 유료다. 확보 실패한 회차를
                    # 「광고」로 표기하면 지면 표기와 과금이 어긋난다.
                    "sponsor_is_paid": claimed_slot_id is not None,
                },
                ai_model=newspaper_content.get("ai_model"),
                generation_ms=newspaper_content.get("generation_ms"),
                token_count=_usage["input"] + _usage["output"],
                input_tokens=_usage["input"],
                output_tokens=_usage["output"],
                sns_copy=newspaper_content.get("sns_copy", {}),
                visual_prompt=newspaper_content.get("visual_prompt"),
                status="published",
                published_at=datetime.now(timezone.utc),
                scheduled_at=schedule.scheduled_at,
                sponsor_slot_id=claimed_slot_id,
            )
            db.add(newspaper)
            await db.flush()

            # 스케줄 완료 처리
            schedule.status = "completed"
            schedule.newspaper_id = newspaper.id
            schedule.executed_at = datetime.now(timezone.utc)

            await progress_store.emit(
                str(schedule.order_id),
                "done",
                "신문이 완성됐습니다!",
                newspaper_id=str(newspaper.id),
                headline=newspaper_content.get("headline", ""),
                subhead=newspaper_content.get("subhead", ""),
                future_date_label=newspaper_content.get("future_date_label", ""),
                sponsor_company=sponsor_company,
            )

            logger.info(
                "newspaper_published",
                order_id=str(order.id),
                episode=schedule.episode_number,
                headline=newspaper.headline,
            )

            # 이메일 알림 발송
            try:
                user_result = await db.execute(select(User).where(User.id == order.user_id))
                user = user_result.scalar_one_or_none()
                if user and user.email and settings.RESEND_API_KEY:
                    from app.services.email_service import (
                        send_newspaper_published,
                        send_series_completed,
                    )
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, lambda: send_newspaper_published(
                        email=user.email,
                        full_name=user.full_name,
                        headline=newspaper.headline or "새 신문이 도착했습니다",
                        episode_number=schedule.episode_number,
                        total_episodes=order.duration_days,
                        newspaper_id=str(newspaper.id),
                    ))
                    # 마지막 화 발행 시 시리즈 완료 메일도 발송
                    if schedule.episode_number >= order.duration_days:
                        await loop.run_in_executor(None, lambda: send_series_completed(
                            email=user.email,
                            full_name=user.full_name,
                            duration_days=order.duration_days,
                        ))
            except Exception as e:
                logger.warning("email_notification_failed", error=str(e))

        except Exception as e:
            schedule.status = "failed"
            schedule.error_message = str(e)
            schedule.retry_count += 1
            logger.error(
                "newspaper_publish_failed",
                schedule_id=str(schedule.id),
                episode=schedule.episode_number,
                error=str(e),
            )


async def _process_schedule_in_own_session(
    schedule_id,
    orchestrator: EditorInChief,
    semaphore: asyncio.Semaphore,
):
    """각 스케줄을 '독립 DB 세션'에서 처리한다.

    ⚠️ 동시성 안전의 핵심: SQLAlchemy AsyncSession은 여러 코루틴이 동시에
    사용하면 안 된다(`another operation is in progress`). 따라서 gather로
    병렬 실행하는 각 작업은 각자 세션을 연다. 실패는 process_single_schedule
    내부에서 스케줄 행에 기록되고, 세션은 정상 커밋된다(작업 간 격리).
    """
    async with get_db_session() as db:
        result = await db.execute(
            select(PublicationSchedule).where(PublicationSchedule.id == schedule_id)
        )
        schedule = result.scalar_one_or_none()
        if not schedule:
            return
        await process_single_schedule(db, schedule, orchestrator, semaphore)


async def daily_publication_job():
    """매일 8시 실행되는 발행 배치 작업"""
    logger.info("daily_publication_job_start")

    # 1) pending 스케줄을 주문별로 묶어 조회 (조회용 세션은 바로 반납)
    async with get_db_session() as db:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(
                PublicationSchedule.id,
                PublicationSchedule.order_id,
                PublicationSchedule.episode_number,
            ).where(
                and_(
                    PublicationSchedule.status == "pending",
                    PublicationSchedule.scheduled_at <= now,
                    PublicationSchedule.retry_count < 3,
                )
            )
        )
        rows = result.all()

    if not rows:
        logger.info("daily_publication_no_pending")
        return

    # 주문별로 그룹화하고 회차 순서대로 정렬
    by_order: dict = {}
    for sid, oid, ep in rows:
        by_order.setdefault(oid, []).append((ep, sid))
    for oid in by_order:
        by_order[oid].sort(key=lambda t: t[0])

    logger.info(
        "daily_publication_processing", count=len(rows), orders=len(by_order)
    )

    # 2) 같은 주문의 회차는 순차(순서 보장 → 메일도 순서대로), 주문끼리는 병렬.
    #    전체 동시 생성량은 세마포어로 상한.
    orchestrator = EditorInChief()
    semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_GENERATIONS)

    async def _process_order_series(episodes: list[tuple]):
        for _ep, sid in episodes:
            await _process_schedule_in_own_session(sid, orchestrator, semaphore)

    tasks = [_process_order_series(eps) for eps in by_order.values()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 실패 카운트 (주문 단위)
    failures = sum(1 for r in results if isinstance(r, Exception))
    logger.info(
        "daily_publication_job_done",
        total=len(rows),
        orders=len(by_order),
        order_failures=failures,
    )


def setup_scheduler():
    """스케줄러 설정 및 시작"""
    scheduler.add_job(
        daily_publication_job,
        trigger=CronTrigger(
            hour=settings.PUBLISH_HOUR,
            minute=settings.PUBLISH_MINUTE,
            timezone=settings.PUBLISH_TIMEZONE,
        ),
        id="daily_publication",
        replace_existing=True,
        max_instances=1,
        # 프로세스가 정각에 바쁘거나 방금 깨어난 경우에도 최대 1시간까지는
        # 놓친 실행을 따라잡는다(무료 티어 콜드스타트 대비).
        misfire_grace_time=3600,
        coalesce=True,
    )

    scheduler.start()
    logger.info(
        "scheduler_started",
        publish_time=f"{settings.PUBLISH_HOUR:02d}:{settings.PUBLISH_MINUTE:02d} {settings.PUBLISH_TIMEZONE}",
    )
    return scheduler


def shutdown_scheduler():
    """스케줄러 종료"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("scheduler_stopped")
