"""Allow social publish tasks to pin the completed 15-second video."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0034_publish_final_video_artifacts"
down_revision: str | Sequence[str] | None = "0033_workspace_product_numbers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("publish_tasks") as batch:
        batch.add_column(
            sa.Column("final_video_artifact_id", sa.Integer(), nullable=True)
        )
        batch.create_foreign_key(
            "fk_publish_tasks_final_video_artifact_id",
            "video_composition_enhancement_artifacts",
            ["final_video_artifact_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index(
            "ix_publish_tasks_final_video_artifact_id",
            ["final_video_artifact_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("publish_tasks") as batch:
        batch.drop_index("ix_publish_tasks_final_video_artifact_id")
        batch.drop_constraint(
            "fk_publish_tasks_final_video_artifact_id", type_="foreignkey"
        )
        batch.drop_column("final_video_artifact_id")
