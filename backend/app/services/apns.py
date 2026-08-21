"""APNs 푸시 발송.

신문이 실제로 발행된 직후에 보낸다. 앱이 미리 예약해두던 로컬 알림과 달리,
발행이 밀려도 알림이 어긋나지 않고 그날 헤드라인을 실을 수 있다.

필요한 환경변수 (App Store Connect API 키와 **다른** 키다):
    APNS_KEY_ID        Certificates → Keys 에서 APNs 를 켜고 발급한 키의 ID
    APNS_TEAM_ID       개발자 팀 ID (10자리)
    APNS_PRIVATE_KEY   그 키의 .p8 내용 (PEM 전문)
    APNS_BUNDLE_ID     com.dreamnewspaper.app

주의 — APNs 는 HTTP/2 만 받는다. httpx 에 http2 extra 가 없으면
"Received HTTP/2 frame ..." 없이 그냥 연결이 실패한다.
"""
import time
from dataclasses import dataclass

import httpx
import structlog
from jose import jwt as jose_jwt

from app.config import settings

logger = structlog.get_logger()

_PROD = "https://api.push.apple.com"
_SANDBOX = "https://api.sandbox.push.apple.com"

# APNs 인증 토큰은 최대 1시간 쓸 수 있고, 20분 이내 재발급은 거부당한다.
# 매 발송마다 새로 만들면 TooManyProviderTokenUpdates 를 받는다.
_TOKEN_TTL = 45 * 60
_cached_token: tuple[str, float] | None = None


@dataclass
class PushResult:
    token: str
    ok: bool
    status: int | None = None
    reason: str | None = None

    @property
    def should_deactivate(self) -> bool:
        """이 기기로 다시 보내면 안 되는 상태인가.

        410 Unregistered = 앱이 지워졌거나 알림을 껐다.
        BadDeviceToken = 토큰이 이 환경(prod/sandbox)의 것이 아니다.
        """
        return self.status == 410 or self.reason in {
            "Unregistered", "BadDeviceToken", "DeviceTokenNotForTopic",
        }


def is_configured() -> bool:
    return bool(settings.APNS_KEY_ID and settings.APNS_TEAM_ID and settings.APNS_PRIVATE_KEY)


def _auth_token() -> str:
    global _cached_token
    now = time.time()
    if _cached_token and now - _cached_token[1] < _TOKEN_TTL:
        return _cached_token[0]

    token = jose_jwt.encode(
        {"iss": settings.APNS_TEAM_ID, "iat": int(now)},
        settings.APNS_PRIVATE_KEY,
        algorithm="ES256",
        headers={"kid": settings.APNS_KEY_ID},
    )
    _cached_token = (token, now)
    return token


async def send(
    tokens: list[tuple[str, str]],
    title: str,
    body: str,
    *,
    newspaper_id: str | None = None,
) -> list[PushResult]:
    """여러 기기에 같은 알림을 보낸다.

    tokens 는 (기기토큰, 환경) 쌍이다. 환경이 섞여 있으면 각각 맞는 호스트로
    보낸다 — TestFlight 이전 개발 빌드는 sandbox, 배포 빌드는 production 이라
    한 사용자가 둘 다 가질 수 있다.
    """
    if not tokens:
        return []
    if not is_configured():
        logger.warning("apns_not_configured", count=len(tokens))
        return [PushResult(t, False, reason="NotConfigured") for t, _ in tokens]

    payload = {
        "aps": {
            "alert": {"title": title, "body": body},
            "sound": "default",
            "badge": 1,
        }
    }
    if newspaper_id:
        # 알림을 탭했을 때 그 신문을 바로 열기 위해 싣는다.
        payload["newspaper_id"] = newspaper_id

    headers = {
        "apns-topic": settings.APNS_BUNDLE_ID,
        "apns-push-type": "alert",
        # 아침 배달이라 즉시 전달한다. 10 은 절전 모드에서도 바로 깨운다.
        "apns-priority": "10",
        # 기기가 꺼져 있어도 하루는 보관한다. 그 이상 지난 신문 알림은 무의미하다.
        "apns-expiration": str(int(time.time()) + 86400),
    }

    results: list[PushResult] = []
    async with httpx.AsyncClient(http2=True, timeout=15.0) as client:
        for token, environment in tokens:
            host = _SANDBOX if environment == "sandbox" else _PROD
            try:
                res = await client.post(
                    f"{host}/3/device/{token}",
                    json=payload,
                    headers={**headers, "authorization": f"bearer {_auth_token()}"},
                )
            except Exception as e:
                # 한 기기의 실패가 나머지 발송을 막지 않는다.
                logger.warning("apns_send_error", error=str(e), token=token[:12])
                results.append(PushResult(token, False, reason=type(e).__name__))
                continue

            if res.status_code == 200:
                results.append(PushResult(token, True, 200))
                continue

            reason = None
            try:
                reason = res.json().get("reason")
            except Exception:
                pass
            logger.info(
                "apns_rejected",
                status=res.status_code, reason=reason, token=token[:12],
            )
            results.append(PushResult(token, False, res.status_code, reason))

    sent = sum(1 for r in results if r.ok)
    logger.info("apns_sent", ok=sent, total=len(results))
    return results
