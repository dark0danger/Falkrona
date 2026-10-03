"""Exact-version approval and local publication intent history."""

from alembic import op
import sqlalchemy as sa


revision = "0012_phase10_publication"
down_revision = "0011_phase9_feedback_learning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "publication_approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("design_version_id", sa.String(36), nullable=False),
        sa.Column("connection_id", sa.String(36)),
        sa.Column("destination_platform", sa.String(32), nullable=False),
        sa.Column("destination_account_id", sa.String(160), nullable=False),
        sa.Column("scheduled_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schedule_local", sa.String(32), nullable=False),
        sa.Column("schedule_fold", sa.Integer(), nullable=False),
        sa.Column("timezone_name", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source_snapshot", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("delivery_mode", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("approved_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["workspace_id", "design_version_id"],
                                ["design_versions.workspace_id", "design_versions.id"],
                                ondelete="CASCADE", name="fk_publication_workspace_design"),
        sa.ForeignKeyConstraint(["workspace_id", "connection_id"],
                                ["social_connections.workspace_id", "social_connections.id"],
                                name="fk_publication_workspace_connection"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_publication_approval_workspace_id"),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_publication_approval_request"),
        sa.UniqueConstraint("workspace_id", "design_version_id", "destination_platform",
                            "destination_account_id", "scheduled_at_utc", name="uq_publication_approval_target"),
    )
    op.create_index("ix_publication_approvals_workspace_id", "publication_approvals", ["workspace_id"])
    op.create_table(
        "publication_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("approval_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("remote_upload_id", sa.String(160)),
        sa.Column("remote_publish_id", sa.String(160)),
        sa.Column("last_error", sa.String(120)),
        sa.Column("exported_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id", "approval_id"],
                                ["publication_approvals.workspace_id", "publication_approvals.id"],
                                ondelete="CASCADE", name="fk_attempt_workspace_approval"),
        sa.UniqueConstraint("workspace_id", "approval_id", name="uq_publication_attempt_approval"),
    )
    op.create_index("ix_publication_attempts_workspace_id", "publication_attempts", ["workspace_id"])
    if op.get_bind().dialect.name == "postgresql":
        for table in ("publication_approvals", "publication_attempts"):
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO brandpilot_app")
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"CREATE POLICY workspace_isolation ON {table} "
                       "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')) "
                       "WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), ''))")


def downgrade() -> None:
    for table in ("publication_attempts", "publication_approvals"):
        if op.get_bind().dialect.name == "postgresql":
            op.execute(f"DROP POLICY IF EXISTS workspace_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.drop_index(f"ix_{table}_workspace_id", table_name=table)
        op.drop_table(table)
