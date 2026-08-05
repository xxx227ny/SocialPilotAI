export interface UploadGuard {
  preflightReady: boolean;
  confirmed: boolean;
  uploadLocked: boolean;
  madeForKidsSelected: boolean;
  identityComplete: boolean;
}

export function canSubmitPrivateUpload(guard: UploadGuard): boolean {
  return (
    guard.preflightReady &&
    guard.confirmed &&
    !guard.uploadLocked &&
    guard.madeForKidsSelected &&
    guard.identityComplete
  );
}

export function shouldLoadSocialData(
  isPresentation: boolean,
  accountBindingEnabled: boolean,
  publishingEnabled: boolean,
): boolean {
  return (
    !isPresentation && (accountBindingEnabled || publishingEnabled)
  );
}

export function shouldLoadPublishTaskHistory(
  isPresentation: boolean,
): boolean {
  return !isPresentation;
}

export function invalidatedAuthorization() {
  return {
    preflightDigest: null,
    confirmed: false,
    result: null,
  } as const;
}
