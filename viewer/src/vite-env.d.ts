/// <reference types="vite/client" />

/** vite.config.ts の define で埋め込まれるビルド時刻。 */
declare const __BUILD_TIME__: string

interface ImportMetaEnv {
  /**
   * TileJSON（tiles.json）の場所。未指定なら配信元の相対パスを順に探す。
   * 本番配信やタイルを別ホストに置く場合に指定する。
   *   VITE_TILEJSON_URL=http://localhost:8080/tiles.json npm run dev
   */
  readonly VITE_TILEJSON_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
