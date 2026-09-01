from fastapi import APIRouter, HTTPException, Response, status

from app.api.auth_dependency import DbSession, ProductPrincipalDep, SettingsDep
from app.schemas.credentials import (
    DashScopeCredentialWrite,
    ProviderCredentialRead,
)
from app.services.provider_credential_service import ProviderCredentialService

router = APIRouter(prefix="/credentials")


@router.get("/dashscope", response_model=ProviderCredentialRead)
def get_dashscope_credential(
    principal: ProductPrincipalDep,
    settings: SettingsDep,
    db: DbSession,
) -> ProviderCredentialRead:
    credential = ProviderCredentialService(db, settings).get(principal.workspace_id)
    if credential is None:
        return ProviderCredentialRead(configured=False)
    return ProviderCredentialRead(
        configured=True,
        key_hint=credential.secret_hint,
        verified=credential.verified_at is not None,
        updated_at=credential.updated_at,
    )


@router.put("/dashscope", response_model=ProviderCredentialRead)
def set_dashscope_credential(
    payload: DashScopeCredentialWrite,
    principal: ProductPrincipalDep,
    settings: SettingsDep,
    db: DbSession,
) -> ProviderCredentialRead:
    try:
        credential = ProviderCredentialService(db, settings).set_dashscope_key(
            principal.workspace_id,
            payload.api_key.get_secret_value(),
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="API Key 格式无效。",
        ) from exc
    return ProviderCredentialRead(
        configured=True,
        key_hint=credential.secret_hint,
        verified=False,
        updated_at=credential.updated_at,
    )


@router.delete("/dashscope", status_code=status.HTTP_204_NO_CONTENT)
def delete_dashscope_credential(
    principal: ProductPrincipalDep,
    settings: SettingsDep,
    db: DbSession,
) -> Response:
    ProviderCredentialService(db, settings).delete_dashscope_key(
        principal.workspace_id
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
