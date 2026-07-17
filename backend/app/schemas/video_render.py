from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VideoRenderTaskCreate(BaseModel):
    scene_sequence: int = Field(gt=0)
    resolution: str = Field(default="720P", min_length=1, max_length=50)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("resolution", "idempotency_key")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("render task fields cannot be empty")
        return cleaned


class VideoRenderTaskSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    video_project_id: int
    scene_sequence: int
    status: str
    provider_name: str | None
    provider_task_id: str | None
    render_prompt: str
    duration_seconds: int
    aspect_ratio: str
    resolution: str
    idempotency_key: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    external_call: Literal[False] = False
