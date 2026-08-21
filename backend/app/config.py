from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
import json


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow", # Allow Supabase keys from env
    )

    # ============================
    # AI API
    # ============================
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""

    # ============================
    # 보안
    # ============================
    SECRET_KEY: str = "migration_placeholder_key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ============================
    # 데이터베이스
    # ============================
    DATABASE_URL: str = "postgresql+asyncpg://dream:dream_secret@localhost:5432/dream_newspaper"

    # ============================
    # ChromaDB
    # ============================
    CHROMA_HOST: str = "localhost"
    CHROMA_PORT: int = 8001
    CHROMA_AUTH_TOKEN: str = ""

    # ============================
    # 앱 설정
    # ============================
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    BACKEND_URL: str = "http://localhost:8000"
    
    # Supabase (Zero Cost Pivot) - Allow prefixes for Vercel harmony
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    NEXT_PUBLIC_SUPABASE_URL: str = ""
    NEXT_PUBLIC_SUPABASE_ANON_KEY: str = ""

    SUPABASE_SERVICE_ROLE_KEY: str = "" # Backend only
    SUPABASE_JWT_SECRET: str = ""       # For local JWT verification (Settings → API → JWT Secret)
    FRONTEND_URL: str = "http://localhost:3000"
    BACKEND_CORS_ORIGINS: str = '["http://localhost:3000"]'

    @property
    def is_production(self) -> bool:
        import os
        return self.ENVIRONMENT == "production" or os.getenv("VERCEL_ENV") == "production"

    @property
    def supabase_url(self) -> str:
        return self.SUPABASE_URL or self.NEXT_PUBLIC_SUPABASE_URL

    @property
    def supabase_anon_key(self) -> str:
        return self.SUPABASE_ANON_KEY or self.NEXT_PUBLIC_SUPABASE_ANON_KEY

    @property
    def cors_origins(self) -> List[str]:
        try:
            origins = json.loads(self.BACKEND_CORS_ORIGINS)
            # Add dynamic Vercel origins
            if self.is_production:
                origins.append("https://dream-newspaper-phi.vercel.app")
                origins.append("https://dream-newspaper.vercel.app")
            return origins
        except Exception:
            return ["http://localhost:3000", "https://dream-newspaper-phi.vercel.app"]

    # ============================
    # AI 모델 설정
    # ============================
    ORCHESTRATOR_MODEL: str = "claude-haiku-4-5-20251001"
    WRITER_MODEL: str = "claude-haiku-4-5-20251001"
    SPONSOR_MODEL: str = "claude-haiku-4-5-20251001"
    MAX_CONCURRENT_GENERATIONS: int = 5

    # ============================
    # 스케줄러 설정
    # ============================
    PUBLISH_HOUR: int = 8
    PUBLISH_MINUTE: int = 0
    PUBLISH_TIMEZONE: str = "Asia/Seoul"
    # 외부 크론이 발행 배치를 깨워/트리거할 때 쓰는 공유 시크릿.
    # Render 무료 티어는 유휴 시 슬립되어 8시 in-process 스케줄러가 안 도므로,
    # GitHub Actions 크론이 매일 08:00 KST에 /api/v1/cron/publish 를 이 시크릿으로 호출한다.
    CRON_SECRET: str = ""

    # ============================
    # Stripe 결제 (레거시)
    # ============================
    # Apple In-App Purchase (iOS 앱 크레딧 결제).
    # iOS는 디지털 재화를 Apple 결제로만 팔 수 있어(가이드라인 3.1.1) Stripe와 별개 경로가 필요하다.
    APPLE_ISSUER_ID: str = ""
    APPLE_KEY_ID: str = ""
    APPLE_PRIVATE_KEY: str = ""          # .p8 파일 내용 (PEM 전문)
    APPLE_BUNDLE_ID: str = "com.dreamnewspaper.app"
    APPLE_ENVIRONMENT: str = "Production"  # Production | Sandbox

    # APNs 푸시 (신문 배달 알림).
    # App Store Connect API 키와 다른 키다 — Certificates → Keys 에서
    # APNs 를 켜고 발급받아야 한다.
    APNS_KEY_ID: str = ""
    APNS_TEAM_ID: str = ""
    APNS_PRIVATE_KEY: str = ""            # .p8 파일 내용 (PEM 전문)
    APNS_BUNDLE_ID: str = "com.dreamnewspaper.app"

    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # ============================
    # PortOne(아임포트) v2 결제 — 국내 간편결제
    # PORTONE_API_SECRET: 백엔드 결제 검증용 시크릿 (PortOne 콘솔 → API Keys)
    # PORTONE_STORE_ID:   상점 ID (store-... 형식)
    # 프론트는 NEXT_PUBLIC_PORTONE_STORE_ID + NEXT_PUBLIC_PORTONE_CHANNEL_KEY 사용
    # ============================
    PORTONE_API_SECRET: str = ""
    PORTONE_STORE_ID: str = ""

    # ============================
    # Resend 이메일
    # ============================
    RESEND_API_KEY: str = ""
    FROM_EMAIL: str = "noreply@dreamnewspaper.com"
    FROM_NAME: str = "꿈신문사"
    # 제휴 문의(스폰서/작가) 알림 수신 이메일 — CEO 확인용
    ADMIN_NOTIFY_EMAIL: str = "junholee940930@gmail.com"

    # ============================
    # 소셜 로그인 (OAuth)
    # ============================
    KAKAO_CLIENT_ID: str = ""
    KAKAO_CLIENT_SECRET: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""


settings = Settings()
