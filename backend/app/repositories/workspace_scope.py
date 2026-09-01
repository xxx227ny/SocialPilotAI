from __future__ import annotations

from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.execution.workspace_context import current_execution_workspace_id
from app.models import Product, VideoProject, VideoRenderTask


def current_workspace_id(session: Session) -> int | None:
    value = session.info.get("workspace_id")
    if value is None:
        value = current_execution_workspace_id()
    return int(value) if value is not None else None


def scope_to_owned_products(
    statement: Select[Any], entity: type, session: Session
) -> Select[Any]:
    workspace_id = current_workspace_id(session)
    if workspace_id is None:
        return statement
    owned_products = select(Product.id).where(Product.workspace_id == workspace_id)
    return statement.where(entity.product_id.in_(owned_products))


def owned_video_project_ids(session: Session) -> Select[Any] | None:
    workspace_id = current_workspace_id(session)
    if workspace_id is None:
        return None
    return (
        select(VideoProject.id)
        .join(Product)
        .where(Product.workspace_id == workspace_id)
    )


def scope_to_owned_video_projects(
    statement: Select[Any], entity: type, session: Session
) -> Select[Any]:
    owned = owned_video_project_ids(session)
    if owned is None:
        return statement
    return statement.where(entity.video_project_id.in_(owned))


def owned_video_render_task_ids(session: Session) -> Select[Any] | None:
    projects = owned_video_project_ids(session)
    if projects is None:
        return None
    return select(VideoRenderTask.id).where(
        VideoRenderTask.video_project_id.in_(projects)
    )


def scope_to_owned_video_render_tasks(
    statement: Select[Any], entity: type, session: Session
) -> Select[Any]:
    owned = owned_video_render_task_ids(session)
    if owned is None:
        return statement
    return statement.where(entity.video_render_task_id.in_(owned))
