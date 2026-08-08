import { apiClient } from "./client";
import type {
  PresentationSnapshot,
  PresentationSnapshotCreateRequest,
  PresentationSnapshotCreateResult,
} from "../types/presentationSnapshot";

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
