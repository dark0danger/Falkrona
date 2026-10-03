"""Add durable, workspace-scoped Hermes run accounting."""

from alembic import op
import sqlalchemy as sa


revision = "0006_phase4_hermes_runs"
down_revision = "0005_phase3_assets_imports"
branch_labels = None
depends_on = None


def _workspace_table(name: str, *columns, constraints=()) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        *columns,
        *constraints,
    )
    op.create_index(f"ix_{name}_workspace_id", name, ["workspace_id"])


def upgrade() -> None:
    _workspace_table(
        "agent_runs",
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("hermes_run_id", sa.String(length=160)),
        sa.Column("prompt_classification", sa.JSON(), nullable=False),
        sa.Column("redacted_prompt", sa.Text(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("checkpoint", sa.JSON(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        constraints=(
            sa.UniqueConstraint("workspace_id", "id", name="uq_agent_runs_workspace_id_id"),
            sa.UniqueConstraint("workspace_id", "dedupe_key", name="uq_agent_runs_workspace_dedupe"),
            sa.UniqueConstraint("workspace_id", "job_id", name="uq_agent_runs_workspace_job"),
            sa.ForeignKeyConstraint(["workspace_id", "job_id"], ["jobs.workspace_id", "jobs.id"], ondelete="CASCADE", name="fk_agent_runs_workspace_job"),
        ),
    )
    _workspace_table(
        "budget_reservations",
        sa.Column("agent_run_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("max_model_calls", sa.Integer(), nullable=False),
        sa.Column("used_model_calls", sa.Integer(), nullable=False),
        sa.Column("max_input_tokens", sa.Integer(), nullable=False),
        sa.Column("used_input_tokens", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("used_output_tokens", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint("workspace_id", "agent_run_id", name="uq_budget_workspace_run"),
            sa.ForeignKeyConstraint(["workspace_id", "agent_run_id"], ["agent_runs.workspace_id", "agent_runs.id"], ondelete="CASCADE", name="fk_budget_workspace_agent_run"),
        ),
    )
    _workspace_table(
        "usage_ledger",
        sa.Column("agent_run_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(sa.ForeignKeyConstraint(["workspace_id", "agent_run_id"], ["agent_runs.workspace_id", "agent_runs.id"], ondelete="CASCADE", name="fk_usage_workspace_agent_run"),),
    )
    op.create_index("ix_usage_ledger_agent_run_id", "usage_ledger", ["agent_run_id"])
    _workspace_table(
        "agent_tool_calls",
        sa.Column("agent_run_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("input_digest", sa.String(length=64), nullable=False),
        sa.Column("result_ref", sa.String(length=500)),
        sa.Column("error_code", sa.String(length=80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint("agent_run_id", "sequence", name="uq_agent_tool_calls_run_sequence"),
            sa.ForeignKeyConstraint(["workspace_id", "agent_run_id"], ["agent_runs.workspace_id", "agent_runs.id"], ondelete="CASCADE", name="fk_tool_calls_workspace_agent_run"),
        ),
    )
    op.create_index("ix_agent_tool_calls_agent_run_id", "agent_tool_calls", ["agent_run_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO brandpilot_app")
        for table in ("agent_runs", "budget_reservations", "usage_ledger", "agent_tool_calls"):
            op.execute(f'DROP POLICY IF EXISTS workspace_isolation ON "{table}"')
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'CREATE POLICY workspace_isolation ON "{table}" USING (workspace_id = NULLIF(current_setting(\'app.workspace_id\', true), \'\')) WITH CHECK (workspace_id = NULLIF(current_setting(\'app.workspace_id\', true), \'\'))')


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("agent_tool_calls", "usage_ledger", "budget_reservations", "agent_runs"):
            op.execute(f'DROP POLICY IF EXISTS workspace_isolation ON "{table}"')
            op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.drop_index("ix_agent_tool_calls_agent_run_id", table_name="agent_tool_calls")
    op.drop_table("agent_tool_calls")
    op.drop_index("ix_usage_ledger_agent_run_id", table_name="usage_ledger")
    op.drop_table("usage_ledger")
    op.drop_table("budget_reservations")
    op.drop_table("agent_runs")
