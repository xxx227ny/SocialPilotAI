/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ENABLE_STRATEGY_EXECUTION?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
