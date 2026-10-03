"""Required owner-supplied branding; recurring reporting enrollment."""
from alembic import op
import sqlalchemy as sa

revision = "0015_branding_setup"
down_revision = "0014_phase11_weekly_results"
branch_labels = depends_on = None


def upgrade():
    op.create_table("engagement_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("post_id", sa.String(36), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id", "post_id"], ["social_posts.workspace_id", "social_posts.id"], ondelete="CASCADE", name="fk_engagement_post"),
        sa.UniqueConstraint("workspace_id", "post_id", "day", "source", name="uq_engagement_daily_source"))
    op.create_index("ix_engagement_snapshots_workspace_id", "engagement_snapshots", ["workspace_id"])
    op.create_table("branding_setups",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("logo_asset_id", sa.String(36)),
        sa.Column("reference_asset_id", sa.String(36)),
        sa.Column("public_context_confirmed", sa.Boolean(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id", "logo_asset_id"], ["workspace_assets.workspace_id", "workspace_assets.id"], name="fk_branding_logo"),
        sa.ForeignKeyConstraint(["workspace_id", "reference_asset_id"], ["workspace_assets.workspace_id", "workspace_assets.id"], name="fk_branding_reference"))
    if op.get_bind().dialect.name == "postgresql":
        for table in ("branding_setups", "engagement_snapshots"):
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO brandpilot_app")
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"CREATE POLICY workspace_isolation ON {table} USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), ''))")


def downgrade():
    op.drop_table("branding_setups")
    op.drop_table("engagement_snapshots")
