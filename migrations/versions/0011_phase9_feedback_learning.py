"""Scoped creative feedback and reversible preference history."""

from alembic import op
import sqlalchemy as sa


revision = "0011_phase9_feedback_learning"
down_revision = "0010_phase8_creative_studio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "design_feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("design_version_id", sa.String(36), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("interpretation", sa.Text(), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("scope", sa.String(24), nullable=False),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id", "design_version_id"],
                                ["design_versions.workspace_id", "design_versions.id"],
                                ondelete="CASCADE", name="fk_feedback_workspace_design"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_design_feedback_workspace_id"),
    )
    op.create_index("ix_design_feedback_workspace_id", "design_feedback", ["workspace_id"])
    op.create_table(
        "learned_preferences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("feedback_id", sa.String(36), nullable=False),
        sa.Column("scope", sa.String(24), nullable=False),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("supersedes_id", sa.String(36)),
        sa.Column("approved_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id", "feedback_id"],
                                ["design_feedback.workspace_id", "design_feedback.id"],
                                ondelete="CASCADE", name="fk_preference_workspace_feedback"),
        sa.UniqueConstraint("workspace_id", "scope", "scope_key", "category", "version",
                            name="uq_preference_scope_version"),
    )
    op.create_index("ix_learned_preferences_workspace_id", "learned_preferences", ["workspace_id"])
    if op.get_bind().dialect.name == "postgresql":
        for table in ("design_feedback", "learned_preferences"):
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO brandpilot_app")
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"CREATE POLICY workspace_isolation ON {table} "
                       "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')) "
                       "WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), ''))")


def downgrade() -> None:
    for table in ("learned_preferences", "design_feedback"):
        if op.get_bind().dialect.name == "postgresql":
            op.execute(f"DROP POLICY IF EXISTS workspace_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.drop_index(f"ix_{table}_workspace_id", table_name=table)
        op.drop_table(table)
