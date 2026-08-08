import { apiClient } from "./client";
import type {
  PresentationSnapshot,
  PresentationSnapshotCreateRequest,
  PresentationSnapshotCreateResult,
} from "../types/presentationSnapshot";

const presentationSnapshotLoads = new Map<
  number,
  Promise<PresentationSnapshot>
>();

export async function createPresentationSnapshot(
  productId: number,
  data: PresentationSnapshotCreateRequest,
  signal?: AbortSignal,
): Promise<PresentationSnapshotCreateResult> {
  const response = await apiClient.post<PresentationSnapshotCreateResult>(
    `/products/${productId}/presentation-snapshots`,
    data,
    { signal },
  );
  return response.data;
}

export async function getPresentationSnapshot(
  snapshotId: number,
  signal?: AbortSignal,
): Promise<PresentationSnapshot> {
  const response = await apiClient.get<PresentationSnapshot>(
    `/presentation-snapshots/${snapshotId}`,
    { signal },
  );
  return response.data;
}

export function loadPresentationSnapshotOnce(
  snapshotId: number,
): Promise<PresentationSnapshot> {
  const existing = presentationSnapshotLoads.get(snapshotId);
  if (existing) return existing;
  const request = getPresentationSnapshot(snapshotId);
  presentationSnapshotLoads.set(snapshotId, request);
  return request;
}

export function getPresentationSnapshotArtifactContentUrl(
  snapshotId: number,
): string {
  const baseUrl = apiClient.defaults.baseURL?.replace(/\/$/, "") ?? "";
  return `${baseUrl}/presentation-snapshots/${snapshotId}/artifact/content`;
}

export async function listPresentationSnapshots(
  productId: number,
  signal?: AbortSignal,
): Promise<PresentationSnapshot[]> {
  const response = await apiClient.get<PresentationSnapshot[]>(
    `/products/${productId}/presentation-snapshots`,
    { signal },
  );
  return response.data;
}
