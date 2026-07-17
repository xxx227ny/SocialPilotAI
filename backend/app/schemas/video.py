from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VideoProjectRequest(BaseModel):
    platform: str = Field(default="TikTok", min_length=1, max_length=100)
    duration_seconds: int = Field(default=30, gt=0, le=180)
    aspect_ratio: str = Field(default="9:16", min_length=1, max_length=20)

    @field_validator("platform", "aspect_ratio")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("video request fields cannot be empty")
        return cleaned


class VideoSceneSchema(BaseModel):
    sequence: int = Field(gt=0)
    duration_seconds: int = Field(gt=0)
    shot_type: str = Field(min_length=1)
    visual_description: str = Field(min_length=1)
    action: str = Field(min_length=1)
    narration: str = Field(min_length=1)

    @field_validator("shot_type", "visual_description", "action", "narration")
    @classmethod
    def clean_scene_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("scene text fields cannot be empty")
        return cleaned


class VideoPlanSchema(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    concept: str = Field(min_length=1)
    platform: str = Field(min_length=1, max_length=100)
    duration_seconds: int = Field(gt=0, le=180)
    aspect_ratio: str = Field(min_length=1, max_length=20)
    scenes: list[VideoSceneSchema] = Field(min_length=1)
    cta: str = Field(min_length=1)

    @field_validator("title", "concept", "platform", "aspect_ratio", "cta")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("video plan fields cannot be empty")
        return cleaned

    @model_validator(mode="after")
    def validate_scene_timeline(self) -> "VideoPlanSchema":
        sequences = [scene.sequence for scene in self.scenes]
        if len(sequences) != len(set(sequences)):
            raise ValueError("scene sequences cannot contain duplicates")
        scene_duration = sum(scene.duration_seconds for scene in self.scenes)
        if scene_duration != self.duration_seconds:
            raise ValueError("scene durations must equal duration_seconds")
        return self


class VideoProjectSchema(VideoPlanSchema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    marketing_strategy_id: int
    copy_matrix_id: int
    status: str
    created_at: datetime
    updated_at: datetime
