"""add public_aspiration to orders

Revision ID: b2c3d4e5f6a7
Revises: d1e2f3a4b5c6
Create Date: 2026-07-05

꿈 동료(같은 미래를 향한 사람들) 공간용 비식별 열망 한 줄. Supabase MCP로
프로덕션 선적용함. 멱등(IF NOT EXISTS).
"""
from alembic import op

revision = 'b2c3d4e5f6a7'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS public_aspiration text")


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS public_aspiration")
