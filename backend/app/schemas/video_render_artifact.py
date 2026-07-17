from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VideoRenderArtifactCreate(BaseModel):
    provider_output_url: str | None = Field(default=None, max_length=2000)
    storage_path: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, object] = Field(default_factory=dict)
    expires_at: datetime | None = None

    @field_validator("provider_output_url", "storage_path")
    @classmethod
    def clean_optional_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def require_result_location(self) -> "VideoRenderArtifactCreate":
        if self.provider_output_url is None and self.storage_path is None:
            raise ValueError(
                "provider_output_url or storage_path must be provided"
            )
        return self


class VideoRenderArtifactSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    video_render_task_id: int
    provider_output_url: str | None
    storage_path: str | None
    metadata: dict[str, object] = Field(validation_alias="artifact_metadata")
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
