"""Enforce compound workspace ownership for job steps."""

from alembic import op


revision = "0004_workspace_job_integrity"
down_revision = "0003_accounts_and_isolation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("job_steps") as batch:
        batch.create_foreign_key(
            "fk_job_steps_workspace_job",
            "jobs",
            ["workspace_id", "job_id"],
            ["workspace_id", "id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("job_steps") as batch:
        batch.drop_constraint("fk_job_steps_workspace_job", type_="foreignkey")
