export type SnapshotPresentationRoute =
  | { kind: "legacy" }
  | { kind: "invalid"; message: string }
  | { kind: "snapshot"; snapshotId: number };

export function parseSnapshotPresentationRoute(
  search: string,
): SnapshotPresentationRoute {
  const params = new URLSearchParams(search);
  if (params.get("mode") !== "presentation" || !params.has("snapshot_id")) {
    return { kind: "legacy" };
  }
  const raw = params.get("snapshot_id") ?? "";
  if (!/^[1-9]\d*$/.test(raw)) {
    return {
      kind: "invalid",
      message: "Snapshot ID 无效，无法进入只读演示。",
    };
  }
  const snapshotId = Number(raw);
  if (!Number.isSafeInteger(snapshotId)) {
    return {
      kind: "invalid",
      message: "Snapshot ID 超出安全范围，无法进入只读演示。",
    };
  }
  return { kind: "snapshot", snapshotId };
}

export function snapshotPresentationUrl(snapshotId: number): string {
  return `/?mode=presentation&snapshot_id=${snapshotId}`;
}
