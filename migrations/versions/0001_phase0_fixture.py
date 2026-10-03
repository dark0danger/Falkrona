"""Create the prior fixture schema used by the upgrade test."""

from alembic import op
import sqlalchemy as sa


revision = "0001_phase0_fixture"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "phase0_fixtures",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("phase0_fixtures")
