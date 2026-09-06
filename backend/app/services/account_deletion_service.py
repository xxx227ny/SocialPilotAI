"""Transactional personal-account erasure for the SQLite product deployment."""

from __future__ import annotations

import secrets

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.db.base import Base
from app.models import Membership, User, Workspace
from app.services.demo_auth_service import hash_password, verify_password


def delete_personal_account(db: Session, *, user_id: int, password: str) -> bool:
    """Caller owns commit/rollback. Never follow references into another workspace.

    Keep anonymous root tombstones to prevent SQLite reusing account/workspace IDs.
    All descendant records (including credentials and sessions) are removed. Managed
    files and administrator backups are not recursively erased by an HTTP request.
    """
    if db.get_bind().dialect.name != "sqlite":
        raise AppError("当前数据库暂不支持自助注销，请联系管理员。", 503)
    user = db.get(User, user_id)
    if user is None or user.status != "ACTIVE":
        raise AppError("账号已失效，请重新登录。", 401)
    if not verify_password(password, user.password_hash):
        return False
    memberships = list(
        db.scalars(select(Membership).where(Membership.user_id == user_id))
    )
    if len(memberships) != 1 or memberships[0].role != "OWNER":
        raise AppError(
            "仅支持独立个人工作区注销；请先联系管理员处理团队成员关系。", 409
        )
    workspace_id = memberships[0].workspace_id
    workspace = db.get(Workspace, workspace_id)
    members = list(
        db.scalars(select(Membership.id).where(Membership.workspace_id == workspace_id))
    )
    if workspace is None or workspace.workspace_type != "PERSONAL" or len(members) != 1:
        raise AppError("该工作区包含团队成员，不能直接注销。", 409)

    tables = Base.metadata.tables
    owned: dict[str, set[int]] = {"users": {user_id}, "workspaces": {workspace_id}}
    # Fixed-point closure also covers cyclic immutable script/video references;
    # database CASCADE alone is insufficient (many edges intentionally RESTRICT).
    changed = True
    while changed:
        changed = False
        for name, table in tables.items():
            primary_key = next(iter(table.primary_key.columns))
            # Snapshot rows deliberately lack FKs to keep historical reads stable.
            # They must still be erased with their product on account deletion.
            if "product_id" in table.c and owned.get("products"):
                for chunk in _chunks(owned["products"]):
                    found_products = set(
                        db.scalars(
                            select(primary_key).where(table.c.product_id.in_(chunk))
                        )
                    )
                    if found_products - owned.get(name, set()):
                        owned.setdefault(name, set()).update(found_products)
                        changed = True
            for fk in table.foreign_keys:
                parent_ids = owned.get(fk.column.table.name, set())
                if not parent_ids or fk.column.name != "id":
                    continue
                found: set[int] = set()
                for chunk in _chunks(parent_ids):
                    found.update(
                        db.scalars(select(primary_key).where(fk.parent.in_(chunk)))
                    )
                new = found - owned.get(name, set())
                if new:
                    owned.setdefault(name, set()).update(new)
                    changed = True

    # Batch orchestration parents have no workspace column. Delete them only when
    # every variant belongs to this closure; never erase a shared legacy batch.
    variants = tables["batch_video_variants"]
    batch_ids: set[int] = set()
    for chunk in _chunks(owned.get("batch_video_variants", set())):
        batch_ids.update(
            db.scalars(
                select(variants.c.batch_video_job_id).where(variants.c.id.in_(chunk))
            )
        )
    for batch_id in batch_ids:
        all_ids = set(
            db.scalars(
                select(variants.c.id).where(variants.c.batch_video_job_id == batch_id)
            )
        )
        if not all_ids.issubset(owned.get("batch_video_variants", set())):
            raise AppError("存在跨工作区共享任务，请联系管理员处理后再注销。", 409)
    if batch_ids:
        owned["batch_video_jobs"] = batch_ids

    busy = {
        "QUEUED",
        "WAITING",
        "RUNNING",
        "PAUSED",
        "SUBMIT_UNKNOWN",
        "SUBMITTED",
        "PROCESSING",
        "UPLOADING",
    }
    for name, ids in owned.items():
        table = tables[name]
        primary_key = next(iter(table.primary_key.columns))
        for chunk in _chunks(ids):
            if "workspace_id" in table.c:
                outsiders = db.scalar(
                    select(primary_key)
                    .where(
                        primary_key.in_(chunk),
                        table.c.workspace_id.is_not(None),
                        table.c.workspace_id != workspace_id,
                    )
                    .limit(1)
                )
                if outsiders is not None:
                    raise AppError(
                        "检测到跨工作区数据关联，请联系管理员处理后再注销。", 409
                    )
            if "product_id" in table.c:
                outsider = db.scalar(
                    select(primary_key)
                    .where(
                        primary_key.in_(chunk),
                        table.c.product_id.is_not(None),
                        table.c.product_id.not_in(owned.get("products", set())),
                    )
                    .limit(1)
                )
                if outsider is not None:
                    raise AppError("存在其他商品共享的数据，不能直接注销。", 409)
            if (
                "status" in table.c
                and db.scalar(
                    select(primary_key)
                    .where(primary_key.in_(chunk), table.c.status.in_(busy))
                    .limit(1)
                )
                is not None
            ):
                raise AppError(
                    "还有未结束或结果待确认的任务，请先等待完成或取消任务，再注销账号。",
                    409,
                )

    db.connection().exec_driver_sql("PRAGMA defer_foreign_keys = ON")
    for name, ids in owned.items():
        if name in {"users", "workspaces"}:
            continue
        table = tables[name]
        primary_key = next(iter(table.primary_key.columns))
        for chunk in _chunks(ids):
            db.execute(table.delete().where(primary_key.in_(chunk)))
    nonce = secrets.token_hex(24)
    db.execute(
        update(User)
        .where(User.id == user_id)
        .values(
            email=f"deleted-{nonce}@invalid.example",
            password_hash=hash_password(secrets.token_urlsafe(48)),
            status="DELETED",
            email_verified_at=None,
        )
    )
    db.execute(
        update(Workspace)
        .where(Workspace.id == workspace_id)
        .values(name="已注销工作区", status="DELETED")
    )
    db.flush()
    return True


def _chunks(values: set[int]):
    ordered = sorted(values)
    for offset in range(0, len(ordered), 400):
        yield ordered[offset : offset + 400]
