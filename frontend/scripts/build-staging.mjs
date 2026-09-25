// Staging intentionally exposes the completed YouTube account-binding and
// publishing flow. Keep these release inputs in one checked-in entrypoint so
// unrelated product builds cannot silently disable the tested integration.
process.env.SOCIALPILOT_SOCIAL_FEATURES = [
  "SOCIAL_ACCOUNT_BINDING",
  "YOUTUBE_PUBLISHING",
].join(",");

await import("./build-product.mjs");
