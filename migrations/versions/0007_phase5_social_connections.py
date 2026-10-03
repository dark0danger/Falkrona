"""Add one-use social authorization transactions and scoped connections."""

from alembic import op
import sqlalchemy as sa


revision = "0007_phase5_social_connections"
down_revision = "0006_phase4_hermes_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("browser_hash", sa.String(64), nullable=False),
        sa.Column("requested_scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_oauth_transactions_workspace_id", "oauth_transactions", ["workspace_id"])
    op.create_table(
        "social_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("authorized_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_id", sa.String(160)),
        sa.Column("account_name", sa.String(255)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("granted_scopes", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("user_credential_id", sa.String(36)),
        sa.Column("account_credential_id", sa.String(36)),
        sa.Column("token_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "id", name="uq_social_connections_workspace_id_id"),
        sa.UniqueConstraint("workspace_id", "provider", "account_id", name="uq_social_connection_account"),
        sa.ForeignKeyConstraint(["workspace_id", "user_credential_id"], ["credential_records.workspace_id", "credential_records.id"], name="fk_social_user_credential"),
        sa.ForeignKeyConstraint(["workspace_id", "account_credential_id"], ["credential_records.workspace_id", "credential_records.id"], name="fk_social_account_credential"),
    )
    op.create_index("ix_social_connections_workspace_id", "social_connections", ["workspace_id"])
    op.create_table(
        "social_posts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(160), nullable=False),
        sa.Column("source_id", sa.String(200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("source_url", sa.String(2048)),
        sa.Column("provenance", sa.String(32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "provider", "account_id", "source_id", name="uq_social_post_source"),
    )
    op.create_index("ix_social_posts_workspace_id", "social_posts", ["workspace_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO brandpilot_app")
        for table in ("oauth_transactions", "social_connections", "social_posts"):
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(
                f'CREATE POLICY workspace_isolation ON "{table}" '
                "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')) "
                "WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), ''))"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("social_posts", "social_connections", "oauth_transactions"):
            op.execute(f'DROP POLICY IF EXISTS workspace_isolation ON "{table}"')
            op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.drop_index("ix_social_posts_workspace_id", table_name="social_posts")
    op.drop_table("social_posts")
    op.drop_index("ix_social_connections_workspace_id", table_name="social_connections")
    op.drop_table("social_connections")
    op.drop_index("ix_oauth_transactions_workspace_id", table_name="oauth_transactions")
    op.drop_table("oauth_transactions")
