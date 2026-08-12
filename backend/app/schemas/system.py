from typing import Literal

from pydantic import BaseModel, ConfigDict


class SystemComponentRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready: bool
    message: str


class DatabaseSystemComponentRead(SystemComponentRead):
    revision_status: Literal["head", "upgrade_required", "unavailable"]
    revision: str | None = None


class ExecutionWorkerSystemComponentRead(SystemComponentRead):
    status: Literal["healthy", "not_running", "stale"]


class SystemReadinessRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: SystemComponentRead
    qwen: SystemComponentRead
    wanx: SystemComponentRead
    google_youtube: SystemComponentRead
    meta_instagram: SystemComponentRead
    instagram_publishing: SystemComponentRead
    database: DatabaseSystemComponentRead
    artifact_storage: SystemComponentRead
    execution_worker: ExecutionWorkerSystemComponentRead
    provider_calls: Literal[0] = 0
    database_writes: Literal[0] = 0
    automatic_actions: Literal[False] = False
