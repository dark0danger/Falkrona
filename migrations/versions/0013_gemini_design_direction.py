"""Retain the Gemini creative direction with each immutable design revision."""
from alembic import op
import sqlalchemy as sa

revision = "0013_gemini_design_direction"
down_revision = "0012_phase10_publication"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("design_versions", sa.Column("creative_direction", sa.JSON(), nullable=False,
                                              server_default=sa.text("'{}'")))


def downgrade():
    op.drop_column("design_versions", "creative_direction")
