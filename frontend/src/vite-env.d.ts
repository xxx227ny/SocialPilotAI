/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ENABLE_SOCIAL_ACCOUNT_BINDING?: string;
  readonly VITE_ENABLE_YOUTUBE_PUBLISHING?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

interface ImportMetaEnv {
  readonly VITE_ENABLE_STRATEGY_EXECUTION?: string;
  readonly VITE_ENABLE_COPY_EXECUTION?: string;
  readonly VITE_ENABLE_V2_COPY_EXECUTION?: string;
  readonly VITE_ENABLE_V2_VIDEO_PROJECT_EXECUTION?: string;
  readonly VITE_ENABLE_VIDEO_RENDER_EXECUTION?: string;
  readonly VITE_ENABLE_GROWTH_EXECUTION?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
