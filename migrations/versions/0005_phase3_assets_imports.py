"""Add safe assets, imports, products, onboarding, and brand profiles."""

from alembic import op
import sqlalchemy as sa


revision = "0005_phase3_assets_imports"
down_revision = "0004_workspace_job_integrity"
branch_labels = None
depends_on = None


def _workspace_table(name: str, *items) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(length=36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        *items,
    )
    op.create_index(f"ix_{name}_workspace_id", name, ["workspace_id"])


def upgrade() -> None:
    with op.batch_alter_table("workspace_assets") as batch:
        batch.add_column(sa.Column("asset_type", sa.String(length=24), nullable=False, server_default="file"))
        batch.add_column(sa.Column("status", sa.String(length=24), nullable=False, server_default="ready"))
        batch.add_column(sa.Column("source", sa.String(length=80), nullable=False, server_default="upload"))
        batch.add_column(sa.Column("width", sa.Integer()))
        batch.add_column(sa.Column("height", sa.Integer()))
        batch.add_column(sa.Column("orientation", sa.String(length=24)))
        batch.add_column(sa.Column("extracted_text", sa.Text()))
        batch.add_column(sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"))

    _workspace_table(
        "import_jobs",
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("source_name", sa.String(length=255)),
        sa.Column("source_url", sa.String(length=2048)),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("preview", sa.JSON(), nullable=False),
        sa.Column("checkpoint", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=80)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("workspace_id", "dedupe_key", name="uq_import_workspace_dedupe"),
    )
    _workspace_table(
        "products",
        sa.Column("sku", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("price", sa.String(length=64)),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("availability", sa.String(length=80)),
        sa.Column("source_ref", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "sku", name="uq_product_workspace_sku"),
    )
    _workspace_table(
        "brand_profile_versions",
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("workspace_id", "version", name="uq_brand_profile_workspace_version"),
    )
    _workspace_table(
        "onboarding_interviews",
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("confirmed_answers", sa.JSON(), nullable=False),
        sa.Column("asked_keys", sa.JSON(), nullable=False),
        sa.Column("contradictions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _workspace_table(
        "onboarding_turns",
        sa.Column("interview_id", sa.String(length=36), sa.ForeignKey("onboarding_interviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_key", sa.String(length=80), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("interview_id", "question_key", name="uq_onboarding_interview_question"),
    )
    op.create_index("ix_onboarding_turns_interview_id", "onboarding_turns", ["interview_id"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
            "TO brandpilot_app"
        )
        for table in (
            "workspace_assets",
            "import_jobs",
            "products",
            "brand_profile_versions",
            "onboarding_interviews",
            "onboarding_turns",
        ):
            op.execute(f'DROP POLICY IF EXISTS workspace_isolation ON "{table}"')
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(
                f'CREATE POLICY workspace_isolation ON "{table}" '
                "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')) "
                "WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), ''))"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in (
            "workspace_assets",
            "import_jobs",
            "products",
            "brand_profile_versions",
            "onboarding_interviews",
            "onboarding_turns",
        ):
            op.execute(f'DROP POLICY IF EXISTS workspace_isolation ON "{table}"')
            op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.drop_index("ix_onboarding_turns_interview_id", table_name="onboarding_turns")
    for table in (
        "onboarding_turns",
        "onboarding_interviews",
        "brand_profile_versions",
        "products",
        "import_jobs",
    ):
        op.drop_table(table)
    with op.batch_alter_table("workspace_assets") as batch:
        for column in (
            "metadata",
            "extracted_text",
            "orientation",
            "height",
            "width",
            "source",
            "status",
            "asset_type",
        ):
            batch.drop_column(column)
