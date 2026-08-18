"""add reader_no to users (독자 번호)

가입 순서를 영구 번호로 박아두고, 앱의 구독 증서·내 정보에 「제0142호 독자」로 찍는다.

Revision ID: c4d5e6f7a8b9
Revises: e2f3a4b5c6d7
Create Date: 2026-08-17

주의 — 이 파일을 실제 저장소에 옮길 때 `down_revision`을 다시 확인할 것.
backend-ref에서는 `a1b2c3d4e5f6`가 세 파일에 중복돼 있던 것을 2026-08-17에
정리했고, 그 결과 이 파일의 직전은 `e2f3a4b5c6d7`(external_txn_id)이다.
실제 저장소의 체인이 다르면 그쪽 head에 맞춰야 한다.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c4d5e6f7a8b9'
down_revision = 'e2f3a4b5c6d7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) 컬럼을 우선 nullable로 연다. 기존 행이 있으면 NOT NULL로 바로 못 만든다.
    op.add_column('users', sa.Column('reader_no', sa.Integer(), nullable=True))

    # 2) 기존 회원에게 가입 순서대로 소급한다.
    #    `ADD COLUMN reader_no SERIAL` 한 줄로 끝내면 안 된다 — 그렇게 하면
    #    기존 행을 채우는 순서가 보장되지 않아, 초기 가입자가 뒷번호를 받을 수 있다.
    #    created_at이 동일한 행이 있어도 흔들리지 않도록 id를 2차 정렬키로 둔다.
    op.execute("""
        WITH ordered AS (
            SELECT id, row_number() OVER (ORDER BY created_at, id) AS rn
            FROM users
        )
        UPDATE users u SET reader_no = o.rn
        FROM ordered o WHERE u.id = o.id
    """)

    # 3) 이후 가입자는 시퀀스가 채운다.
    #    파이썬에서 COUNT(*)+1로 계산하면 동시 가입 시 같은 번호가 두 명에게 나간다.
    #    DB 시퀀스는 그 경합이 원천적으로 없다.
    op.execute("CREATE SEQUENCE users_reader_no_seq OWNED BY users.reader_no")
    op.execute("""
        SELECT setval(
            'users_reader_no_seq',
            COALESCE((SELECT MAX(reader_no) FROM users), 0) + 1,
            false
        )
    """)
    op.execute(
        "ALTER TABLE users ALTER COLUMN reader_no "
        "SET DEFAULT nextval('users_reader_no_seq')"
    )

    # 4) 이제 빈 값이 없으므로 잠근다.
    op.alter_column('users', 'reader_no', nullable=False)
    op.create_unique_constraint('uq_users_reader_no', 'users', ['reader_no'])


def downgrade() -> None:
    op.drop_constraint('uq_users_reader_no', 'users', type_='unique')
    # 컬럼이 시퀀스를 OWNED BY로 물고 있어 컬럼을 지우면 시퀀스도 함께 사라진다.
    # 그래도 과거에 수동 생성된 잔여 시퀀스를 대비해 한 번 더 정리한다.
    op.drop_column('users', 'reader_no')
    op.execute("DROP SEQUENCE IF EXISTS users_reader_no_seq")
