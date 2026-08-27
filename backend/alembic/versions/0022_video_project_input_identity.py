"""Allow one immutable ScriptVersion to produce multiple exact visual projects."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022_video_project_input_identity"
down_revision: str | Sequence[str] | None = "0021_product_video_production_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("video_projects") as batch_op:
        batch_op.drop_constraint(
            "uq_video_projects_source_script_version", type_="unique"
        )
        batch_op.add_column(sa.Column("source_input_digest", sa.String(64)))
        batch_op.create_unique_constraint(
            "uq_video_projects_source_input_digest", ["source_input_digest"]
        )
        batch_op.create_index(
            "ix_video_projects_source_input_digest", ["source_input_digest"]
        )


def downgrade() -> None:
    with op.batch_alter_table("video_projects") as batch_op:
        batch_op.drop_index("ix_video_projects_source_input_digest")
        batch_op.drop_constraint(
            "uq_video_projects_source_input_digest", type_="unique"
        )
        batch_op.drop_column("source_input_digest")
        batch_op.create_unique_constraint(
            "uq_video_projects_source_script_version", ["source_script_version_id"]
        )
