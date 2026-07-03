"""Create auditable document chunk table.

Revision ID: 20260703_0002
Revises: 20260629_0001
Create Date: 2026-07-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260703_0002"
down_revision: str | None = "20260629_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("extraction_quality", sa.String(length=32), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section_heading", sa.String(length=512), nullable=True),
        sa.Column("is_suspicious", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "guardrail_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "chunk_ordinal",
            name="uq_document_chunks_document_ordinal",
        ),
    )
    op.create_index(
        "ix_document_chunks_document_id",
        "document_chunks",
        ["document_id"],
    )
    op.create_index(
        "ix_document_chunks_document_suspicious",
        "document_chunks",
        ["document_id", "is_suspicious"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_document_suspicious", table_name="document_chunks")
    op.drop_index("ix_document_chunks_document_id", table_name="document_chunks")
    op.drop_table("document_chunks")
