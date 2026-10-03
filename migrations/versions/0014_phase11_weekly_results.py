"""Workspace-isolated weekly cycle reports and next-plan links."""
from alembic import op
import sqlalchemy as sa

revision = "0014_phase11_weekly_results"
down_revision = "0013_gemini_design_direction"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("weekly_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("next_plan_id", sa.String(36)),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "week_start", name="uq_weekly_report_period"),
        sa.ForeignKeyConstraint(["workspace_id", "next_plan_id"], ["weekly_plans.workspace_id", "weekly_plans.id"],
                                name="fk_report_workspace_plan"))
    op.create_index("ix_weekly_reports_workspace_id", "weekly_reports", ["workspace_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON weekly_reports TO brandpilot_app")
        op.execute("ALTER TABLE weekly_reports ENABLE ROW LEVEL SECURITY")
        op.execute("CREATE POLICY workspace_isolation ON weekly_reports USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), ''))")


def downgrade():
    op.drop_table("weekly_reports")
