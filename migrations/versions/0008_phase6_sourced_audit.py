"""Add workspace-isolated source observations for deterministic audits."""

from alembic import op
import sqlalchemy as sa


revision = "0008_phase6_sourced_audit"
down_revision = "0007_phase5_social_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("social_posts") as batch:
        batch.create_unique_constraint("uq_social_posts_workspace_id_id", ["workspace_id", "id"])
    op.create_table(
        "metric_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("post_id", sa.String(36), nullable=False),
        sa.Column("metric", sa.String(24), nullable=False),
        sa.Column("traffic", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("value", sa.Integer()),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_ref", sa.String(200), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["workspace_id", "post_id"], ["social_posts.workspace_id", "social_posts.id"], name="fk_metric_observation_post"),
    )
    op.create_index("ix_metric_observations_workspace_id", "metric_observations", ["workspace_id"])
    op.create_table(
        "audit_comments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("post_id", sa.String(36), nullable=False),
        sa.Column("redacted_text", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.String(200), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["workspace_id", "post_id"], ["social_posts.workspace_id", "social_posts.id"], name="fk_audit_comment_post"),
        sa.UniqueConstraint("workspace_id", "source_ref", name="uq_audit_comment_source"),
    )
    op.create_index("ix_audit_comments_workspace_id", "audit_comments", ["workspace_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO brandpilot_app")
        for table in ("metric_observations", "audit_comments"):
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(
                f'CREATE POLICY workspace_isolation ON "{table}" '
                "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')) "
                "WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), ''))"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("audit_comments", "metric_observations"):
            op.execute(f'DROP POLICY IF EXISTS workspace_isolation ON "{table}"')
            op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.drop_index("ix_audit_comments_workspace_id", table_name="audit_comments")
    op.drop_table("audit_comments")
    op.drop_index("ix_metric_observations_workspace_id", table_name="metric_observations")
    op.drop_table("metric_observations")
    with op.batch_alter_table("social_posts") as batch:
        batch.drop_constraint("uq_social_posts_workspace_id_id", type_="unique")
