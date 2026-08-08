from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PresentationSnapshotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marketing_brief_id: int | None = Field(default=None, ge=1)
    marketing_strategy_id: int | None = Field(default=None, ge=1)
    copy_matrix_id: int | None = Field(default=None, ge=1)
    video_project_id: int | None = Field(default=None, ge=1)
    render_task_id: int | None = Field(default=None, ge=1)
    artifact_id: int | None = Field(default=None, ge=1)
    publish_task_id: int | None = Field(default=None, ge=1)
    campaign_ids: list[int] = Field(default_factory=list)

    @field_validator("campaign_ids")
    @classmethod
    def validate_campaign_ids(cls, value: list[int]) -> list[int]:
        if any(campaign_id < 1 for campaign_id in value):
            raise ValueError("Campaign IDs must be positive")
        if len(value) != len(set(value)):
            raise ValueError("Campaign IDs must be unique")
        return value


class PresentationSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: int
    schema_version: int
    digest: str
    product_id: int
    marketing_brief_id: int | None
    marketing_strategy_id: int | None
    copy_matrix_id: int | None
    video_project_id: int | None
    render_task_id: int | None
    artifact_id: int | None
    publish_task_id: int | None
    campaign_ids: list[int]
    missing_sections: list[str]
    snapshot_payload: dict[str, object]
    artifact_sha256: str | None
    artifact_snapshot_path: str | None
    created_at: datetime


class PresentationSnapshotCreateRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot: PresentationSnapshotRead
    reused: bool
    provider_calls: Literal[0] = 0
