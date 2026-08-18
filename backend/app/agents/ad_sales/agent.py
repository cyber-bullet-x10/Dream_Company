import json
from app.agents.base_agent import BaseAgent
from app.vector_store import COMPANIES_COLLECTION
from app.config import settings
import structlog

logger = structlog.get_logger()


class AdSales(BaseAgent):
    """Ad Sales (광고 영업팀) — pgvector 스폰서 자동 매칭"""

    def __init__(self):
        super().__init__(
            model=settings.SPONSOR_MODEL,
            max_tokens=1024,
            system_prompt="""
당신은 꿈신문사의 스폰서 매칭 전문가입니다.
사용자의 꿈과 가장 관련성 높은 기업을 3개 선택하고 이유를 설명합니다.
반드시 JSON 배열 형식으로만 반환하세요.
""",
            agent_name="ad-sales",
        )

    async def find_sponsors(self, order: dict) -> list[dict]:
        """
        1. Paid Sponsors (DB) + Vector Search (Potential) 후보 병합
        2. Claude/Gemini가 최적 3개 선택 (Paid 우선 가이드)
        """
        from app.vector_store import query_vector_store, COMPANIES_COLLECTION
        from app.database import AsyncSessionLocal
        from app.models.sponsor import Sponsor, SponsorSlot
        from sqlalchemy import select
        
        candidates = []
        # 회사명 → 슬롯 ID. LLM 응답에는 slot_id가 실려 오지 않으므로(환각 위험),
        # 선택된 회사명을 이 표로 되짚어 실제 슬롯을 복원한다.
        paid_slot_ids: dict[str, str] = {}

        # 1. Paid Sponsor (유료 광고주) 조회
        try:
            async with AsyncSessionLocal() as session:
                paid_query = select(Sponsor, SponsorSlot).join(
                    SponsorSlot, Sponsor.id == SponsorSlot.sponsor_id
                ).where(
                    SponsorSlot.remaining_quantity > 0,
                    SponsorSlot.payment_status == "paid",
                    Sponsor.is_active == True
                )
                paid_results = await session.execute(paid_query)
                
                for sponsor, slot in paid_results:
                    paid_slot_ids[sponsor.company_name] = str(slot.id)
                    candidates.append({
                        "company_name": sponsor.company_name,
                        "industry": sponsor.industry,
                        "description": sponsor.description[:200] if sponsor.description else "",
                        "is_paid": True,
                        "slot_type": slot.slot_type,
                        "score": 1.0 # 유료는 기본 점수 높음
                    })
        except Exception as e:
            logger.warning("paid_sponsor_fetch_failed", error=str(e))

        # 2. 벡터 검색으로 연관 기업(잠재 광고주) 추가 추출
        try:
            query_text = (
                f"{order.get('target_role', '')} "
                f"{order.get('target_company', '')} "
                f"{order.get('dream_description', '')}"
            )

            results = await query_vector_store(
                COMPANIES_COLLECTION,
                query_text,
                n_results=10
            )

            if results["ids"] and results["ids"][0]:
                for meta, doc, dist in zip(
                    results["metadatas"][0],
                    results["documents"][0],
                    results["distances"][0],
                ):
                    # 이미 유료 기업군에 있으면 중복 추가 방지
                    if any(c["company_name"] == meta.get("name") for c in candidates):
                        continue
                        
                    candidates.append({
                        "company_name": meta.get("name", ""),
                        "industry": meta.get("industry", ""),
                        "description": doc[:200],
                        "is_paid": False,
                        "similarity": round(1 - dist, 3),
                    })

        except Exception as e:
            logger.warning("vector_search_failed", error=str(e))
            if not candidates:
                candidates = self._get_fallback_candidates(order)

        if not candidates:
            candidates = self._get_fallback_candidates(order)

        # 3. LLM이 최종 선택
        prompt = f"""
당신은 꿈신문사의 스폰서 매칭 전문가입니다.
사용자의 꿈과 가장 관련성 높은 기업을 후보 목록에서 3개 선택하세요.

사용자 정보:
- 꿈/목표: {order.get('dream_description', '')}
- 목표 직업: {order.get('target_role', '')}
- 목표 회사: {order.get('target_company', '없음')}

후보 기업 목록 (is_paid=True는 실제 유료 광고주이므로 우선 고려하세요):
{json.dumps(candidates, ensure_ascii=False, indent=2)}

선택 기준: 
1. `is_paid: true`인 기업을 우선적으로 고려하되, 꿈의 내용과 너무 동떨어지지 않아야 함.
2. 직업/꿈과의 연관성, 브랜드 인지도, 독자 공감도.

반드시 다음 JSON 배열 형식으로만 반환하세요:
[
  {{"company_name": "회사명", "slot_type": "company_name", "score": 0.95, "reason": "선택 이유", "is_paid": true/false}},
  ...
]
"""
        try:
            result_text = await self.run_async(prompt)

            # JSON 파싱
            start = result_text.find("[")
            end = result_text.rfind("]") + 1
            if start != -1 and end > start:
                sponsors = json.loads(result_text[start:end])
                logger.info("sponsor_match_success", count=len(sponsors))
                return self._attach_slot_ids(sponsors[:3], paid_slot_ids)

        except Exception as e:
            logger.error("sponsor_match_failed", error=str(e))

        # 폴백: 점수/유사도 순으로 반환
        fallback = sorted(
            candidates, key=lambda x: x.get("is_paid", False), reverse=True
        )[:3]
        return self._attach_slot_ids(fallback, paid_slot_ids)

    @staticmethod
    def _attach_slot_ids(
        sponsors: list[dict], paid_slot_ids: dict[str, str]
    ) -> list[dict]:
        """선택된 회사명을 실제 SponsorSlot과 다시 연결한다.

        LLM이 `is_paid`를 잘못 붙여 보낼 수 있으므로 그 값을 믿지 않고,
        유료 슬롯 표에 회사명이 있는지로 판정한다. 이 slot_id가 있어야
        발행 시점에 슬롯 차감과 노출 집계가 이뤄진다.
        """
        for s in sponsors:
            slot_id = paid_slot_ids.get(s.get("company_name", ""))
            s["slot_id"] = slot_id
            s["is_paid"] = slot_id is not None
        return sponsors

    def _get_fallback_candidates(self, order: dict) -> list[dict]:
        """ChromaDB 연결 실패 시 폴백 후보"""
        target_company = order.get("target_company", "")
        target_role = order.get("target_role", "")

        # 직업 기반 기본 매칭
        fallbacks = []

        if any(kw in target_role for kw in ["개발", "엔지니어", "IT", "AI", "데이터"]):
            fallbacks = [
                {"company_name": "삼성전자", "industry": "IT", "description": "글로벌 IT 기업", "similarity": 0.9},
                {"company_name": "카카오", "industry": "IT", "description": "국내 IT 플랫폼", "similarity": 0.85},
                {"company_name": "네이버", "industry": "IT", "description": "검색/AI 기업", "similarity": 0.8},
            ]
        elif any(kw in target_role for kw in ["의사", "의료", "간호", "헬스"]):
            fallbacks = [
                {"company_name": "삼성서울병원", "industry": "의료", "description": "국내 최고 병원", "similarity": 0.9},
            ]
        else:
            fallbacks = [
                {"company_name": "삼성전자", "industry": "IT", "description": "글로벌 기업", "similarity": 0.7},
            ]

        if target_company:
            fallbacks.insert(0, {
                "company_name": target_company,
                "industry": "목표 기업",
                "description": f"사용자의 목표 기업",
                "similarity": 0.95,
            })

        return fallbacks
