"""create cheers (익명 응원)

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-08-22

"""
from alembic import op
import sqlalchemy as sa

revision = 'e6f7a8b9c0d1'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'cheers',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            'from_user_id', sa.Uuid(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False,
        ),
        sa.Column(
            'to_order_id', sa.Uuid(as_uuid=True),
            sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False,
        ),
        # 자유 텍스트가 아니라 편집국 문구 번호만 저장한다.
        sa.Column('template_id', sa.Integer(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index('ix_cheers_from_user_id', 'cheers', ['from_user_id'])
    op.create_index('ix_cheers_to_order_id', 'cheers', ['to_order_id'])
    op.create_index('ix_cheers_created_at', 'cheers', ['created_at'])
    # 한 사람이 같은 연재에 여러 번 보내면 「세 사람이 응원했다」가 거짓이 된다.
    op.create_unique_constraint(
        'uq_cheers_from_to', 'cheers', ['from_user_id', 'to_order_id']
    )


def downgrade() -> None:
    op.drop_constraint('uq_cheers_from_to', 'cheers', type_='unique')
    op.drop_index('ix_cheers_created_at', table_name='cheers')
    op.drop_index('ix_cheers_to_order_id', table_name='cheers')
    op.drop_index('ix_cheers_from_user_id', table_name='cheers')
    op.drop_table('cheers')
