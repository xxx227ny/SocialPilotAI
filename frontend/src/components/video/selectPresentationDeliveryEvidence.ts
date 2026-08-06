interface DeliveryEvidenceTask {
  product_id: number;
  artifact_id: number;
  status: string;
  privacy_status: string;
}

export function selectPresentationDeliveryEvidence<T extends DeliveryEvidenceTask>(
  tasks: T[],
  productId: number,
  artifactId: number,
): T[] {
  return tasks.filter(
    (task) =>
      task.product_id === productId &&
      task.artifact_id === artifactId &&
      task.status === "SUCCEEDED" &&
      task.privacy_status === "private",
  );
}
