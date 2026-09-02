from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.auth_dependency import DbSession, ProductPrincipalDep, SettingsDep
from app.schemas.credentials import (
    DashScopeCredentialWrite,
    ProviderCredentialRead,
    ProviderCredentialVerificationRead,
)
from app.services.provider_credential_service import ProviderCredentialService
from app.services.provider_credential_verifier import (
    DashScopeCredentialVerifier,
)

router = APIRouter(prefix="/credentials")


def get_dashscope_credential_verifier() -> DashScopeCredentialVerifier:
    return DashScopeCredentialVerifier()


DashScopeVerifierDep = Annotated[
    DashScopeCredentialVerifier,
    Depends(get_dashscope_credential_verifier),
]


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
        region=credential.provider_region,
        provider_workspace_id=credential.provider_workspace_ref,
        verified=credential.verified_at is not None,
        verified_at=credential.verified_at,
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
            region=payload.region,
            provider_workspace_id=payload.provider_workspace_id,
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
        region=credential.provider_region,
        provider_workspace_id=credential.provider_workspace_ref,
        verified=False,
        verified_at=None,
        updated_at=credential.updated_at,
    )


@router.post(
    "/dashscope/verify",
    response_model=ProviderCredentialVerificationRead,
)
def verify_dashscope_credential(
    principal: ProductPrincipalDep,
    settings: SettingsDep,
    db: DbSession,
    verifier: DashScopeVerifierDep,
) -> ProviderCredentialVerificationRead:
    service = ProviderCredentialService(db, settings)
    credential = service.get(principal.workspace_id)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="请先保存 API Key，再进行验证。",
        )
    runtime = service.read_dashscope_runtime(principal.workspace_id)
    if runtime is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="请先保存 API Key，再进行验证。",
        )
    result = verifier.verify(
        runtime.api_key,
        models_endpoint=runtime.models_endpoint,
    )
    credential = service.set_dashscope_verified(
        principal.workspace_id,
        verified=result.verified,
    )
    db.commit()
    assert credential is not None
    return ProviderCredentialVerificationRead(
        status=result.status,
        verified=result.verified,
        key_hint=credential.secret_hint,
        region=credential.provider_region,
        provider_workspace_id=credential.provider_workspace_ref,
        verified_at=credential.verified_at,
        message=result.message,
    )


@router.delete("/dashscope", status_code=status.HTTP_204_NO_CONTENT)
def delete_dashscope_credential(
    principal: ProductPrincipalDep,
    settings: SettingsDep,
    db: DbSession,
) -> Response:
    ProviderCredentialService(db, settings).delete_dashscope_key(principal.workspace_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
