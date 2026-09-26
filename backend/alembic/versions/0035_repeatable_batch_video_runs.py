"""Allow explicit new batch video runs for identical frozen inputs."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0035_repeatable_batch_video_runs"
down_revision: str | Sequence[str] | None = "0034_publish_final_video_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("batch_video_jobs", recreate="always") as batch:
        batch.drop_constraint("uq_batch_video_jobs_digest", type_="unique")
    op.create_index(
        "ix_batch_video_jobs_request_digest",
        "batch_video_jobs",
        ["request_digest"],
        unique=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    duplicate = connection.execute(
        sa.text(
            "SELECT request_digest FROM batch_video_jobs "
            "GROUP BY request_digest HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot restore the unique batch request digest while repeated runs exist"
        )
    op.drop_index(
        "ix_batch_video_jobs_request_digest", table_name="batch_video_jobs"
    )
    with op.batch_alter_table("batch_video_jobs", recreate="always") as batch:
        batch.create_unique_constraint(
            "uq_batch_video_jobs_digest", ["request_digest"]
        )
