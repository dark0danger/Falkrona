"""Immutable creative scenes and private rendered artifacts."""

from alembic import op
import sqlalchemy as sa


revision = "0010_phase8_creative_studio"
down_revision = "0009_phase7_weekly_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("weekly_plans") as batch:
        batch.create_unique_constraint("uq_weekly_plan_workspace_id", ["workspace_id", "id"])
    op.create_table(
        "design_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("plan_id", sa.String(36), nullable=False),
        sa.Column("item_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.String(36)),
        sa.Column("scene", sa.JSON(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("factual_refs", sa.JSON(), nullable=False),
        sa.Column("needs_fact_review", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id", "plan_id"], ["weekly_plans.workspace_id", "weekly_plans.id"],
                                ondelete="CASCADE", name="fk_design_workspace_plan"),
        sa.UniqueConstraint("workspace_id", "plan_id", "item_id", "revision", name="uq_design_item_revision"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_design_workspace_id"),
    )
    op.create_index("ix_design_versions_workspace_id", "design_versions", ["workspace_id"])
    op.create_table(
        "render_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("design_version_id", sa.String(36), nullable=False),
        sa.Column("slide_id", sa.String(36), nullable=False),
        sa.Column("preset", sa.String(32), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id", "design_version_id"],
                                ["design_versions.workspace_id", "design_versions.id"],
                                ondelete="CASCADE", name="fk_render_workspace_design"),
        sa.UniqueConstraint("workspace_id", "design_version_id", "slide_id", "preset", name="uq_render_variant"),
    )
    op.create_index("ix_render_artifacts_workspace_id", "render_artifacts", ["workspace_id"])
    if op.get_bind().dialect.name == "postgresql":
        for table in ("design_versions", "render_artifacts"):
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO brandpilot_app")
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY workspace_isolation ON {table} "
                "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')) "
                "WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), ''))"
            )


def downgrade() -> None:
    for table in ("render_artifacts", "design_versions"):
        if op.get_bind().dialect.name == "postgresql":
            op.execute(f"DROP POLICY IF EXISTS workspace_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.drop_index(f"ix_{table}_workspace_id", table_name=table)
        op.drop_table(table)
    with op.batch_alter_table("weekly_plans") as batch:
        batch.drop_constraint("uq_weekly_plan_workspace_id", type_="unique")
