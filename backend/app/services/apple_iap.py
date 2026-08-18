"""Apple In-App Purchase 영수증 검증.

App Store Server API로 거래를 조회해 진짜 결제인지 확인한다.

왜 서버 검증이 필요한가 — 클라이언트가 "결제했어요"라고 보낸 말을 믿고 크레딧을
지급하면, 위조 요청 한 줄로 크레딧을 무한히 받아갈 수 있다. 반드시 Apple에
직접 물어봐야 한다.

필요한 환경변수:
    APPLE_ISSUER_ID       App Store Connect API Issuer ID (UUID)
    APPLE_KEY_ID          API 키 ID (10자리)
    APPLE_PRIVATE_KEY     .p8 파일 내용 (PEM 전문)
    APPLE_BUNDLE_ID       com.dreamnewspaper.app
    APPLE_ENVIRONMENT     Production | Sandbox  (기본 Production)
"""
import json
import time
import uuid
from base64 import urlsafe_b64decode

import httpx
import structlog
from jose import jwt as jose_jwt

from app.config import settings

logger = structlog.get_logger()

_PROD = "https://api.storekit.itunes.apple.com"
_SANDBOX = "https://api.storekit-sandbox.itunes.apple.com"


class AppleVerificationError(Exception):
    """검증 실패 — 호출부에서 402/400으로 바꿔 응답한다."""


def _api_token() -> str:
    """App Store Server API 호출용 ES256 JWT. 유효기간은 짧게 잡는다."""
    now = int(time.time())
    return jose_jwt.encode(
        {
            "iss": settings.APPLE_ISSUER_ID,
            "iat": now,
            "exp": now + 600,
            "aud": "appstoreconnect-v1",
            "bid": settings.APPLE_BUNDLE_ID,
        },
        settings.APPLE_PRIVATE_KEY,
        algorithm="ES256",
        headers={"kid": settings.APPLE_KEY_ID, "typ": "JWT"},
    )


def _decode_jws_payload(signed: str) -> dict:
    """JWS의 페이로드를 꺼낸다.

    서명 검증은 Apple 서버가 직접 준 응답이라는 점(HTTPS + 인증된 API 호출)으로
    갈음한다. 클라이언트가 준 JWS를 그대로 믿는 경로는 만들지 않는다 —
    이 함수는 오직 Apple API 응답에만 쓴다.
    """
    try:
        payload_b64 = signed.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        return json.loads(urlsafe_b64decode(payload_b64))
    except Exception as e:
        raise AppleVerificationError(f"영수증을 해석하지 못했습니다: {e}")


async def fetch_transaction(transaction_id: str) -> dict:
    """거래 ID로 Apple에 조회. 프로덕션에서 못 찾으면 샌드박스도 시도한다.

    TestFlight 빌드는 샌드박스 거래를 만들기 때문에, 두 환경을 모두 봐야
    내부 테스트 중 결제가 실패하지 않는다.
    """
    if not settings.APPLE_PRIVATE_KEY or not settings.APPLE_ISSUER_ID:
        raise AppleVerificationError("Apple 결제 설정이 서버에 없습니다.")

    token = _api_token()
    headers = {"Authorization": f"Bearer {token}"}

    hosts = [_PROD, _SANDBOX]
    if settings.APPLE_ENVIRONMENT.lower() == "sandbox":
        hosts = [_SANDBOX, _PROD]

    last_status = None
    async with httpx.AsyncClient(timeout=20.0) as client:
        for host in hosts:
            url = f"{host}/inApps/v1/transactions/{transaction_id}"
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                signed = res.json().get("signedTransactionInfo", "")
                if not signed:
                    raise AppleVerificationError("Apple 응답에 거래 정보가 없습니다.")
                return _decode_jws_payload(signed)
            last_status = res.status_code
            if res.status_code == 404:
                continue  # 다른 환경에서 재시도
            if res.status_code == 401:
                raise AppleVerificationError("Apple API 인증에 실패했습니다.")
            break

    raise AppleVerificationError(
        f"거래를 확인하지 못했습니다 (status={last_status})."
    )


def validate_transaction(txn: dict, expected_product_id: str) -> None:
    """조회된 거래가 우리 앱의 정상 결제인지 확인한다."""
    if txn.get("bundleId") != settings.APPLE_BUNDLE_ID:
        raise AppleVerificationError("다른 앱의 영수증입니다.")

    if txn.get("productId") != expected_product_id:
        raise AppleVerificationError("상품 정보가 일치하지 않습니다.")

    # 환불·취소된 거래로 크레딧을 받아가지 못하게 막는다.
    if txn.get("revocationDate"):
        raise AppleVerificationError("환불된 결제입니다.")

    # 크레딧은 소모품(consumable)이다. 구독이나 다른 유형이면 거부.
    if txn.get("type") not in (None, "Consumable"):
        raise AppleVerificationError("지원하지 않는 상품 유형입니다.")


def new_txn_key(transaction_id: str) -> str:
    """DB에 저장할 외부 거래 식별자. 다른 결제 수단과 섞이지 않게 접두어를 둔다."""
    return f"apple:{transaction_id}"


def fallback_txn_key() -> str:
    """거래 ID가 비어 있는 비정상 케이스용 — 실제로는 도달하면 안 된다."""
    return f"apple:unknown:{uuid.uuid4()}"
