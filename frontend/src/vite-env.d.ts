/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_ADAPTER?: "http" | "mock";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
