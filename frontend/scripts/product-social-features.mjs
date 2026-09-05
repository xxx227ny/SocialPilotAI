export const socialFeatures = [
  "SOCIAL_ACCOUNT_BINDING", "INSTAGRAM_ACCOUNT_BINDING",
  "TIKTOK_ACCOUNT_BINDING", "PINTEREST_ACCOUNT_BINDING",
  "YOUTUBE_PUBLISHING", "INSTAGRAM_PUBLISHING", "TIKTOK_PUBLISHING",
];

// Explicit release input, separate from local VITE_* development overrides.
export function productSocialOverrides(value = "") {
  const selected = value.split(",").map((item) => item.trim()).filter(Boolean);
  for (const name of selected) {
    if (!socialFeatures.includes(name)) throw new Error(`Unknown social feature: ${name}`);
  }
  return Object.fromEntries(selected.map((name) => [`VITE_ENABLE_${name}`, "true"]));
}
