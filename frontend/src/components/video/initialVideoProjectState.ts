import type {
  InitialVideoProjectPreflight,
  InitialVideoProjectSource,
  InitialVideoProjectSourceRequest,
} from "../../types/video";

export function selectExactInitialVideoSource(
  productId: number,
  source: InitialVideoProjectSource,
): Pick<InitialVideoProjectSourceRequest, "strategy_id" | "copy_matrix_id"> | null {
  if (
    source.product_id !== productId ||
    source.strategy_id <= 0 ||
    source.copy_matrix_id <= 0
  ) {
    return null;
  }
  return {
    strategy_id: source.strategy_id,
    copy_matrix_id: source.copy_matrix_id,
  };
}

export function preflightMatchesInitialRequest(
  preflight: InitialVideoProjectPreflight | null,
  request: InitialVideoProjectSourceRequest | null,
): boolean {
  return Boolean(
    preflight &&
      request &&
      preflight.strategy_id === request.strategy_id &&
      preflight.copy_matrix_id === request.copy_matrix_id &&
      preflight.platform === request.platform &&
      preflight.duration_seconds === request.duration_seconds &&
      preflight.aspect_ratio === request.aspect_ratio,
  );
}

export function canExecuteInitialVideoProject({
  frontendGateEnabled,
  preflight,
  request,
  costConfirmed,
  executionLocked,
  resultPresent,
  now = Date.now(),
}: {
  frontendGateEnabled: boolean;
  preflight: InitialVideoProjectPreflight | null;
  request: InitialVideoProjectSourceRequest | null;
  costConfirmed: boolean;
  executionLocked: boolean;
  resultPresent: boolean;
  now?: number;
}): boolean {
  return Boolean(
    frontendGateEnabled &&
      preflight?.ready_for_execution &&
      preflightMatchesInitialRequest(preflight, request) &&
      Date.parse(preflight.expires_at) > now &&
      costConfirmed &&
      !executionLocked &&
      !resultPresent,
  );
}
