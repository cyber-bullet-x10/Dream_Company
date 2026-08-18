"""add external_txn_id to credit_transactions (Apple IAP 중복 지급 방지)

Revision ID: e2f3a4b5c6d7
Revises: b2c3d4e5f6a7
Create Date: 2026-08-16


[정리 메모 2026-08-17] revision id가 `a1b2c3d4e5f6`로 다른 두 파일과
겹쳐 있어 alembic이 체인을 풀지 못했다. Create Date 순서를 기준으로
이 파일에 고유 id를 새로 주고 down_revision을 직전 마이그레이션에 다시 걸었다.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e2f3a4b5c6d7'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'credit_transactions',
        sa.Column('external_txn_id', sa.String(length=100), nullable=True),
    )
    # UNIQUE 제약이 중복 지급을 막는 최종 방어선이다.
    # 애플리케이션 레벨 조회만으로는 동시 요청에서 두 번 지급될 수 있다.
    op.create_index(
        'ix_credit_transactions_external_txn_id',
        'credit_transactions',
        ['external_txn_id'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        'ix_credit_transactions_external_txn_id',
        table_name='credit_transactions',
    )
    op.drop_column('credit_transactions', 'external_txn_id')
