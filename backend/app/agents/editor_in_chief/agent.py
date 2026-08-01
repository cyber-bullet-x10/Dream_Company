import uuid
import json
import pathlib
import hashlib
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.agents.base_agent import BaseAgent
from app.agents.reporter.agent import Reporter
from app.agents.ad_sales.agent import AdSales
from app.agents.marketing_director.agent import MarketingDirector
# from app.agents.content_director.agent import ContentDirector  # Phase 2: 이미지 생성 (보류)
from app.agents.hr_manager.agent import HRManager
from app.agents.editor_in_chief.prompts import ORCHESTRATOR_SYSTEM_PROMPT
from app.config import settings
import structlog

# 소통 파일 경로 (Docker 환경에서는 마운트 안됨 → None 처리)
try:
    _CEO_MD = pathlib.Path(__file__).parents[6] / "docs" / "work-plans" / "CEO.md"
    _EDITOR_MEMO = pathlib.Path(__file__).parents[6] / "docs" / "memos" / "editor_in_chief.md"
except IndexError:
    _CEO_MD = None
    _EDITOR_MEMO = None

logger = structlog.get_logger()


class EditorInChief(BaseAgent):
    """Editor-in-Chief (편집장) — 신문 제작 파이프라인 총괄"""

    def __init__(self):
        super().__init__(
            model=settings.ORCHESTRATOR_MODEL,
            max_tokens=4096,
            system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
            agent_name="editor-in-chief",
        )
        self.reporter = Reporter()
        self.ad_sales = AdSales()
        self.marketing_director = MarketingDirector()
        # self.content_director = ContentDirector()  # Phase 2: 이미지 생성 (보류)
        self.hr_manager = HRManager()

    async def process_new_order(self, order: dict) -> dict:
        """
        새 의뢰 전체 파이프라인 실행

        Args:
            order: {
                id, user_id, protagonist_name, dream_description,
                target_role, target_company, duration_days, future_year,
                payment_type, timezone
            }

        Returns:
            {order_id, sponsors, schedule, writer_type, status}
        """
        order_id = str(order.get("id", uuid.uuid4()))
        logger.info("orchestrator_new_order", order_id=order_id)

        # 1. 스폰서 매칭은 process_single_schedule에서만 실행 (중복 호출 제거)
        # — 스폰서는 실제 신문 생성 시점에 한 번만 매칭하면 됨
        sponsors = []

        # 2. 발행 스케줄 생성
        schedule = self._create_publication_schedule(order)

        # 3. WriterManager: AI vs 인간 작가 결정 + 배정
        # order에 writer_type이 명시된 경우 그대로 사용, 아니면 LLM이 결정
        if not order.get("writer_type") or order.get("writer_type") == "ai":
            decided_type = await self.hr_manager.decide_writer_type(order)
            order = {**order, "writer_type": decided_type}

        writer_assignment = await self._assign_writer(order)

        logger.info(
            "orchestrator_order_processed",
            order_id=order_id,
            schedule_count=len(schedule),
            writer_type=writer_assignment["type"],
        )

        return {
            "order_id": order_id,
            "sponsors": sponsors,
            "schedule": schedule,
            "writer_type": writer_assignment["type"],
            "assigned_writer_id": writer_assignment.get("writer_id"),
            "status": "active",
        }

    async def generate_single_newspaper(
        self,
        order: dict,
        episode: int,
        scheduled_date: datetime,
        sponsor_company: str = None,
        previous_summary: str = None,
    ) -> dict:
        """
        단일 신문 편 생성

        Args:
            order: 의뢰 정보
            episode: 에피소드 번호
            scheduled_date: 발행 예정일
            sponsor_company: 스폰서 회사명 (선택)
            previous_summary: 이전 편 요약 (선택)

        Returns:
            신문 콘텐츠 dict
        """
        # 미래 날짜 계산
        # 회차 간 실제 발행은 매일(하루 간격)이지만, 신문 '속' 미래 날짜는 회차마다
        # 약 한 달씩(25~40일 랜덤) 벌린다. 하루 만에 직책·성과가 확 바뀌는 비현실을 없애고
        # 이야기가 자연스럽게 진전되도록. 간격은 주문ID+회차로 시드를 고정해 항상 증가하고
        # 재생성해도 동일하다(순서 꼬임·중복 방지).
        future_year = order.get("future_year", 2030)

        # 시리즈 1편 기준일을 future_year로 매핑 (이 회차 발행일에서 회차 오프셋 제거)
        series_start = scheduled_date - timedelta(days=episode - 1)
        years_ahead = future_year - series_start.year
        try:
            base_date = series_start.replace(year=series_start.year + years_ahead).date()
        except ValueError:  # 2/29 → 평년 등 예외 방어
            base_date = series_start.replace(
                year=series_start.year + years_ahead, day=28
            ).date()

        # 2편부터 누적 간격(각 gap ≈ 한 달, 25~40일 랜덤, 시드 고정)
        order_id = str(order.get("id", ""))
        offset_days = 0
        for gap_idx in range(1, episode):
            seed = int(
                hashlib.sha256(f"{order_id}:{gap_idx}".encode()).hexdigest()[:12], 16
            )
            offset_days += random.Random(seed).randint(25, 40)
        future_date = base_date + timedelta(days=offset_days)

        weekdays_kr = ["월", "화", "수", "목", "금", "토", "일"]
        future_date_label = (
            f"{future_date.year}년 {future_date.month}월 "
            f"{future_date.day}일 "
            f"{weekdays_kr[future_date.weekday()]}요일"
        )

        order_context = {
            "protagonist_name": order["protagonist_name"],
            "dream_description": order["dream_description"],
            "target_role": order["target_role"],
            "target_company": order.get("target_company", ""),
            "future_date_label": future_date_label,
            "total_episodes": order["duration_days"],
            "sponsor_company": sponsor_company,
            "previous_summary": previous_summary,
        }

        # 인간 작가 의뢰: AI 편집 초안 생성 / AI 의뢰: 완성본 생성
        if order.get("writer_type") == "human":
            newspaper_content = await self.hr_manager.generate_ai_draft(order_context, episode)
            summary = f"[인간 작가 초안] {episode}편 초안이 작가에게 전달됐습니다."
        else:
            newspaper_content = self.reporter.generate_newspaper(order_context, episode)
            summary = self.reporter.summarize_episode(newspaper_content)

        full_text = f"{newspaper_content.get('headline')}\n{newspaper_content.get('body_content')}"

        sns_copy = await self.marketing_director.generate_sns_copy(full_text)
        # Phase 2: 이미지 생성 보류 — 토큰 절약 + Pollinations.ai 연동 추후 개발
        # visual_prompt = await self.content_director.generate_visual_prompt(full_text)
        visual_prompt = None

        return {
            **newspaper_content,
            "episode_number": episode,
            "future_date": future_date,
            "future_date_label": future_date_label,
            "episode_summary": summary,
            "sns_copy": sns_copy,
            "visual_prompt": visual_prompt,
        }

    def _create_publication_schedule(self, order: dict) -> list[dict]:
        """발행 스케줄 생성"""
        tz = ZoneInfo(order.get("timezone", "Asia/Seoul"))
        duration_days = order["duration_days"]
        publish_hour = int(str(order.get("publish_time", "08:00:00")).split(":")[0])

        # 내일부터 시작
        start_date = datetime.now(tz).replace(
            hour=publish_hour, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)

        schedule = []
        for i in range(duration_days):
            scheduled_at = start_date + timedelta(days=i)
            schedule.append({
                "episode": i + 1,
                "scheduled_at": scheduled_at.isoformat(),
                "future_date": scheduled_at.date().isoformat(),
                "status": "pending",
            })

        return schedule

    async def _assign_writer(self, order: dict) -> dict:
        """
        작가 배정
        - ai: Reporter 사용
        - human: HRManager로 최적 작가 자동 매칭
        """
        w_type = order.get("writer_type", "ai")

        if w_type == "human":
            match = await self.hr_manager.find_best_writer(order)
            if match:
                return {
                    "type": "human",
                    "writer_id": match["writer_id"],
                    "pen_name": match["pen_name"],
                    "model": None,
                }
            # 가용 작가 없으면 AI로 폴백
            logger.warning("no_available_human_writer_fallback_to_ai", order_id=order.get("id"))
            w_type = "ai"

        return {
            "type": w_type,
            "writer_id": None,
            "model": settings.WRITER_MODEL,
        }

    async def generate_with_editorial_loop(
        self,
        order: dict,
        episode: int,
        scheduled_date: datetime,
        sponsor_company: str = None,
        previous_summary: str = None,
        max_retries: int = 2,
    ) -> dict:
        """
        편집 루프: 생성 → 품질 검토 → 재시도(최대 max_retries회) → 에스컬레이션

        Loop:
          1. Reporter가 신문 생성
          2. EditorInChief가 품질 검토 (score 기준 0.6)
          3. 미달 시 피드백 포함 재생성 요청
          4. max_retries 초과 시 CTO에 에스컬레이션 + 현재 결과 자동 승인
        """
        order_id = str(order.get("id", "unknown"))
        last_content = None
        last_quality = None

        for attempt in range(1, max_retries + 1):
            logger.info("editorial_loop_attempt", order_id=order_id, episode=episode, attempt=attempt)

            last_content = await self.generate_single_newspaper(
                order=order,
                episode=episode,
                scheduled_date=scheduled_date,
                sponsor_company=sponsor_company,
                previous_summary=previous_summary,
            )

            last_quality = self.review_newspaper_quality(last_content)
            logger.info(
                "editorial_quality_check",
                order_id=order_id,
                episode=episode,
                attempt=attempt,
                score=last_quality.get("score"),
                approved=last_quality.get("approved"),
            )

            if last_quality.get("approved") or last_quality.get("score", 0) >= 0.6:
                logger.info("editorial_loop_approved", order_id=order_id, episode=episode, attempt=attempt)
                break

            if attempt < max_retries:
                # 피드백을 previous_summary에 반영해 재시도
                logger.info(
                    "editorial_loop_retry",
                    order_id=order_id,
                    episode=episode,
                    feedback=last_quality.get("feedback"),
                )
                previous_summary = (
                    f"[편집장 피드백] {last_quality.get('feedback', '')} / "
                    + (previous_summary or "")
                )
            else:
                # max_retries 소진 → CTO 에스컬레이션
                self._escalate_to_cto(
                    issue_type="품질 미달 자동 에스컬레이션",
                    details={
                        "order_id": order_id,
                        "episode": episode,
                        "score": last_quality.get("score"),
                        "feedback": last_quality.get("feedback"),
                    },
                )

        return {**last_content, "quality": last_quality}

    def _escalate_to_cto(self, issue_type: str, details: dict) -> None:
        """
        CTO에게 이슈 에스컬레이션 — CEO.md에 긴급 항목 자동 추가
        EditorInChief가 자체 해결할 수 없는 문제를 CTO에게 보고
        """
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            detail_str = " | ".join(f"{k}: {v}" for k, v in details.items())
            entry = f"\n- [ ] **[편집장 에스컬레이션 {timestamp}]** {issue_type} — {detail_str}\n"

            # CEO.md에 긴급 항목 삽입
            if _CEO_MD and _CEO_MD.exists():
                content = _CEO_MD.read_text(encoding="utf-8")
                marker = "### 긴급 (버그)"
                if marker in content:
                    insert_pos = content.index(marker) + len(marker)
                    content = content[:insert_pos] + entry + content[insert_pos:]
                else:
                    content += f"\n### 긴급 (버그)\n{entry}"
                _CEO_MD.write_text(content, encoding="utf-8")

            # editor_in_chief.md 에스컬레이션 로그에도 기록
            if _EDITOR_MEMO and _EDITOR_MEMO.exists():
                memo = _EDITOR_MEMO.read_text(encoding="utf-8")
                memo += f"\n### {timestamp} — {issue_type}\n- {detail_str}\n"
                _EDITOR_MEMO.write_text(memo, encoding="utf-8")

            logger.warning("escalated_to_cto", issue_type=issue_type, details=details)
        except Exception as e:
            logger.error("escalation_failed", error=str(e))

    def review_newspaper_quality(self, newspaper: dict) -> dict:
        """
        신문 품질 검토 (선택적 - sonnet 모델 사용)

        Returns:
            {"approved": bool, "feedback": str, "score": float}
        """
        prompt = f"""
다음 꿈신문 기사의 품질을 검토해주세요.

헤드라인: {newspaper.get('headline', '')}
서브헤드: {newspaper.get('subhead', '')}
리드: {newspaper.get('lead_paragraph', '')}
본문 (앞부분): {str(newspaper.get('body_content', ''))[:300]}

검토 기준:
1. 현재진행형으로 작성됐는가? (미래형 표현 없는지)
2. 주인공 실명이 자연스럽게 포함됐는가?
3. 생생하고 긍정적인 톤인가?
4. 신문 형식에 맞는가?

JSON으로 반환:
{{"approved": true/false, "score": 0.0-1.0, "feedback": "간단한 피드백"}}
"""
        try:
            content_text = self.run_sync(prompt)
            import json
            start = content_text.find("{")
            end = content_text.rfind("}") + 1
            if start != -1:
                return json.loads(content_text[start:end])
        except Exception as e:
            logger.error("quality_review_failed", error=str(e))

        return {"approved": True, "score": 0.8, "feedback": "자동 승인"}
