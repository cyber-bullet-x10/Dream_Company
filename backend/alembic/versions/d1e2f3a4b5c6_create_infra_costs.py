"""create infra_costs table

Revision ID: d1e2f3a4b5c6
Revises: f6a7b8c9d0e1
Create Date: 2026-07-04

인프라 구독비(Render/Vercel/Supabase/Resend) 수동 입력 테이블 — 관리자
대시보드 손익 계산용. API로 자동 조회가 안 되는 항목은 CEO가 직접 입력.

프로덕션(Supabase)에는 Supabase MCP로 직접 선적용함. 멱등(IF NOT EXISTS/ON
CONFLICT DO NOTHING)이라 어느 환경에서 돌든/이미 적용돼 있든 안전.

[정리 메모 2026-08-17] revision id가 `a1b2c3d4e5f6`로 다른 두 파일과
겹쳐 있어 alembic이 체인을 풀지 못했다. Create Date 순서를 기준으로
이 파일에 고유 id를 새로 주고 down_revision을 직전 마이그레이션에 다시 걸었다.
"""
from alembic import op

revision = 'd1e2f3a4b5c6'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS infra_costs (
            service varchar(50) PRIMARY KEY,
            monthly_cost_krw integer NOT NULL DEFAULT 0,
            note text,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        INSERT INTO infra_costs (service, monthly_cost_krw, note) VALUES
            ('render', 0, '백엔드 호스팅 — 요금제 확인 후 CEO가 입력'),
            ('vercel', 0, '프론트 호스팅 — 요금제 확인 후 CEO가 입력'),
            ('supabase', 0, '무료 티어(Free plan) — 유료 전환 시 업데이트'),
            ('resend', 0, '이메일 발송 — 요금제 확인 후 CEO가 입력')
        ON CONFLICT (service) DO NOTHING
    """)
    op.execute("ALTER TABLE infra_costs ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS infra_costs")
