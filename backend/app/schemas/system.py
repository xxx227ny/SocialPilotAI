from typing import Literal

from pydantic import BaseModel, ConfigDict


class SystemComponentRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready: bool
    message: str


class SystemReadinessRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: SystemComponentRead
    qwen: SystemComponentRead
    wanx: SystemComponentRead
    google_youtube: SystemComponentRead
    database: SystemComponentRead
    artifact_storage: SystemComponentRead
    provider_calls: Literal[0] = 0
    database_writes: Literal[0] = 0
    automatic_actions: Literal[False] = False
