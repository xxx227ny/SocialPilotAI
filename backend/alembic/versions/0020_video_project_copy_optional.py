"""Allow script-backed video projects without a platform copy matrix."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020_video_project_copy_optional"
down_revision: str | Sequence[str] | None = "0019_growth_replan_resolutions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("video_projects", recreate="always") as batch_op:
        batch_op.alter_column(
            "copy_matrix_id",
            existing_type=sa.Integer(),
            nullable=True,
        )


def downgrade() -> None:
    connection = op.get_bind()
    missing_copy_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM video_projects WHERE copy_matrix_id IS NULL")
    ).scalar_one()
    if missing_copy_count:
        raise RuntimeError(
            "Cannot downgrade while script-backed video projects lack CopyMatrix"
        )
    with op.batch_alter_table("video_projects", recreate="always") as batch_op:
        batch_op.alter_column(
            "copy_matrix_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
