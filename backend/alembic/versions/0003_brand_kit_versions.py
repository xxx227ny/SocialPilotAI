"""Add reusable BrandKit identities and immutable versions."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_brand_kit_versions"
down_revision: str | Sequence[str] | None = "0002_x2_presentation_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brand_kits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brand_kits_name", "brand_kits", ["name"])
    op.create_table(
        "brand_kit_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("brand_kit_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("brand_name", sa.String(length=200), nullable=False),
        sa.Column("positioning", sa.Text(), nullable=False),
        sa.Column("default_language", sa.String(length=100), nullable=False),
        sa.Column("brand_tone", sa.Text(), nullable=False),
        sa.Column("preferred_terms", sa.JSON(), nullable=False),
        sa.Column("forbidden_terms", sa.JSON(), nullable=False),
        sa.Column("target_regions", sa.JSON(), nullable=False),
        sa.Column("audience_guidelines", sa.JSON(), nullable=False),
        sa.Column("visual_guidelines", sa.JSON(), nullable=False),
        sa.Column("required_disclosures", sa.JSON(), nullable=False),
        sa.Column("claims_constraints", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["brand_kit_id"], ["brand_kits.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "version_number >= 1", name="ck_brand_kit_version_number_positive"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "brand_kit_id", "digest", name="uq_brand_kit_version_digest"
        ),
        sa.UniqueConstraint(
            "brand_kit_id", "version_number", name="uq_brand_kit_version_number"
        ),
    )
    op.create_index(
        "ix_brand_kit_versions_brand_kit_id",
        "brand_kit_versions",
        ["brand_kit_id"],
    )
    op.create_index(
        "ix_brand_kit_versions_digest", "brand_kit_versions", ["digest"]
    )
    with op.batch_alter_table("products") as batch_op:
        batch_op.add_column(
            sa.Column("brand_kit_version_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_products_brand_kit_version_id",
            "brand_kit_versions",
            ["brand_kit_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "ix_products_brand_kit_version_id", ["brand_kit_version_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_index("ix_products_brand_kit_version_id")
        batch_op.drop_constraint(
            "fk_products_brand_kit_version_id", type_="foreignkey"
        )
        batch_op.drop_column("brand_kit_version_id")
    op.drop_index("ix_brand_kit_versions_digest", table_name="brand_kit_versions")
    op.drop_index(
        "ix_brand_kit_versions_brand_kit_id", table_name="brand_kit_versions"
    )
    op.drop_table("brand_kit_versions")
    op.drop_index("ix_brand_kits_name", table_name="brand_kits")
    op.drop_table("brand_kits")
