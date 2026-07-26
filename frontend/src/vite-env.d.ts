/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ENABLE_STRATEGY_EXECUTION?: string;
  readonly VITE_ENABLE_COPY_EXECUTION?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
