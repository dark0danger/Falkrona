"""Add versioned, workspace-isolated weekly strategy plans."""

from alembic import op
import sqlalchemy as sa


revision = "0009_phase7_weekly_plans"
down_revision = "0008_phase6_sourced_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weekly_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("strategy", sa.JSON(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("workspace_id", "week_start", "revision", name="uq_weekly_plan_revision"),
    )
    op.create_index("ix_weekly_plans_workspace_id", "weekly_plans", ["workspace_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON weekly_plans TO brandpilot_app")
        op.execute("ALTER TABLE weekly_plans ENABLE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY workspace_isolation ON weekly_plans "
            "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')) "
            "WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), ''))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS workspace_isolation ON weekly_plans")
        op.execute("ALTER TABLE weekly_plans DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_weekly_plans_workspace_id", table_name="weekly_plans")
    op.drop_table("weekly_plans")
