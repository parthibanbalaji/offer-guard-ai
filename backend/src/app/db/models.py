"""SQLAlchemy ORM models for OfferGuard persistence."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base metadata for OfferGuard relational models."""


class DocumentUploadStatus(StrEnum):
    """Storage lifecycle for the original uploaded document."""

    PENDING = "pending"
    STORED = "stored"
    FAILED = "failed"


class ReviewJobStatus(StrEnum):
    """Processing lifecycle for a document review job."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Document(Base):
    """Original uploaded offer document stored outside Postgres."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "upload_status in ('pending', 'stored', 'failed')",
            name="ck_documents_upload_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(127), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    original_storage_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    upload_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DocumentUploadStatus.PENDING.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    review_jobs: Mapped[list["ReviewJob"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class ReviewJob(Base):
    """Durable queued work item for reviewing an uploaded document."""

    __tablename__ = "review_jobs"
    __table_args__ = (
        CheckConstraint(
            "status in ('queued', 'processing', 'completed', 'failed')",
            name="ck_review_jobs_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    document_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ReviewJobStatus.QUEUED.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    document: Mapped[Document] = relationship(back_populates="review_jobs")
