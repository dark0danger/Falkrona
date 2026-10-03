"""Add accounts, sessions, workspace ownership, encryption, and RLS."""

from alembic import op
import sqlalchemy as sa


revision = "0003_accounts_and_isolation"
down_revision = "0002_durable_foundation"
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
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("language", sa.String(length=12), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("data_mode", sa.String(length=24), nullable=False),
        sa.Column("selected_provider", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "workspace_memberships",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(length=36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "workspace_id", "user_id", name="uq_membership_workspace_user"
        ),
    )
    op.create_index(
        "ix_workspace_memberships_workspace_id",
        "workspace_memberships",
        ["workspace_id"],
    )
    op.create_index(
        "ix_workspace_memberships_user_id", "workspace_memberships", ["user_id"]
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("csrf_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_table(
        "auth_attempts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("bucket", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_auth_attempt_bucket_created", "auth_attempts", ["bucket", "created_at"]
    )
    _workspace_table(
        "credential_records",
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_credentials_workspace_id_id"
        ),
    )
    _workspace_table(
        "workspace_assets",
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "id", name="uq_assets_workspace_id_id"),
        sa.UniqueConstraint(
            "workspace_id", "storage_key", name="uq_assets_storage_key"
        ),
    )
    _workspace_table(
        "audit_events",
        sa.Column(
            "actor_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=100), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("workspace_id", sa.String(length=36)))
        batch.add_column(sa.Column("created_by_user_id", sa.String(length=36)))
        batch.create_foreign_key(
            "fk_jobs_workspace", "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_foreign_key(
            "fk_jobs_created_by",
            "users",
            ["created_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_unique_constraint(
            "uq_jobs_workspace_id_id", ["workspace_id", "id"]
        )
    op.create_index("ix_jobs_workspace_id", "jobs", ["workspace_id"])
    with op.batch_alter_table("job_steps") as batch:
        batch.add_column(sa.Column("workspace_id", sa.String(length=36)))
    op.create_index("ix_job_steps_workspace_id", "job_steps", ["workspace_id"])
    with op.batch_alter_table("outbox_events") as batch:
        batch.add_column(sa.Column("workspace_id", sa.String(length=36)))
        batch.create_foreign_key(
            "fk_outbox_workspace",
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_index("ix_outbox_events_workspace_id", "outbox_events", ["workspace_id"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DO $$ BEGIN CREATE ROLE brandpilot_app NOLOGIN NOBYPASSRLS; "
            "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
        )
        op.execute("GRANT brandpilot_app TO CURRENT_USER")
        op.execute("GRANT USAGE ON SCHEMA public TO brandpilot_app")
        op.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
            "TO brandpilot_app"
        )
        for table in (
            "jobs",
            "job_steps",
            "outbox_events",
            "credential_records",
            "workspace_assets",
            "audit_events",
        ):
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(
                f'CREATE POLICY workspace_isolation ON "{table}" '
                "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')) "
                "WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), ''))"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in (
            "jobs",
            "job_steps",
            "outbox_events",
            "credential_records",
            "workspace_assets",
            "audit_events",
        ):
            op.execute(f'DROP POLICY IF EXISTS workspace_isolation ON "{table}"')
            op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.drop_index("ix_outbox_events_workspace_id", table_name="outbox_events")
    with op.batch_alter_table("outbox_events") as batch:
        batch.drop_constraint("fk_outbox_workspace", type_="foreignkey")
        batch.drop_column("workspace_id")
    op.drop_index("ix_job_steps_workspace_id", table_name="job_steps")
    with op.batch_alter_table("job_steps") as batch:
        batch.drop_column("workspace_id")
    op.drop_index("ix_jobs_workspace_id", table_name="jobs")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_constraint("uq_jobs_workspace_id_id", type_="unique")
        batch.drop_constraint("fk_jobs_created_by", type_="foreignkey")
        batch.drop_constraint("fk_jobs_workspace", type_="foreignkey")
        batch.drop_column("created_by_user_id")
        batch.drop_column("workspace_id")
    for table in (
        "audit_events",
        "workspace_assets",
        "credential_records",
        "auth_attempts",
        "sessions",
        "workspace_memberships",
        "workspaces",
        "users",
    ):
        op.drop_table(table)
