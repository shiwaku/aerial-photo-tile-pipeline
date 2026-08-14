import type { RasterSourceSpecification } from 'maplibre-gl'

/**
 * パイプラインが出力した TileJSON（tiles.json）を読み、オルソ画像のソース定義を組む。
 *
 * 出力形態が 2 系統あり、置き場所も参照方法も違う。
 *   TILE_OUTPUT="dir"     … output/<id>/tiles/tiles.json  + tiles/{z}/{x}/{y}.webp
 *   TILE_OUTPUT="pmtiles" … output/<id>/tiles.json        + pmtiles://<id>.pmtiles/{z}/{x}/{y}
 * どちらで生成されたかは tiles[0] の形で判別できるため、設定を持たずに両対応にする。
 */

export const SOURCE_ID = 'ortho'
export const LAYER_ID = 'ortho'

export interface TileJson {
  name?: string
  format?: string
  tiles: string[]
  bounds?: [number, number, number, number]
  center?: [number, number, number]
  minzoom: number
  maxzoom: number
  attribution?: string
}

export interface Ortho {
  tilejson: TileJson
  source: RasterSourceSpecification
  /** PMTiles 経由なら true。UI 表示と、プロトコル登録の要否判定に使う。 */
  isPmtiles: boolean
  /** 読み込みに成功した tiles.json の絶対 URL。相対タイル URL の解決基準になる。 */
  baseUrl: string
}

/** 探索順。PMTiles は作業ディレクトリ直下、XYZ は tiles/ の下に置かれる。 */
const CANDIDATES = ['tiles.json', 'tiles/tiles.json']

const PMTILES_PREFIX = 'pmtiles://'
/** PMTiles の TileJSON は `pmtiles://<archive>/{z}/{x}/{y}` 形式で書かれる。 */
const XYZ_SUFFIX = '/{z}/{x}/{y}'

async function fetchJson(url: string): Promise<TileJson | null> {
  try {
    // 同じポートでデータセットを切り替えると、ブラウザが前の tiles.json を
    // キャッシュから返し、存在しない PMTiles を要求して 404 になる。
    // メタデータは常に取り直す（数百バイトなので毎回取っても問題ない）。
    const res = await fetch(url, { cache: 'no-store' })
    if (!res.ok) return null
    return (await res.json()) as TileJson
  } catch {
    return null
  }
}

/**
 * タイル URL を絶対 URL に直す。
 *
 * `{z}` などのプレースホルダは URL としては不正なので、そのまま new URL() に通せない。
 * プレースホルダ部分を切り離してから解決する。
 */
function absolutize(tileUrl: string, baseUrl: string): string {
  if (tileUrl.startsWith(PMTILES_PREFIX)) {
    const rest = tileUrl.slice(PMTILES_PREFIX.length)
    const archive = rest.endsWith(XYZ_SUFFIX) ? rest.slice(0, -XYZ_SUFFIX.length) : rest
    return `${PMTILES_PREFIX}${new URL(archive, baseUrl).href}${XYZ_SUFFIX}`
  }
  // {z}/{x}/{y}.webp のようなテンプレート。プレースホルダを一旦伏せて解決する
  const marker = '__TILE_PLACEHOLDER__'
  const masked = tileUrl.replace(/\{[a-z]\}/g, marker)
  const resolved = new URL(masked, baseUrl).href
  const parts = resolved.split(marker)
  const originals = tileUrl.match(/\{[a-z]\}/g) ?? []
  return parts.reduce((acc, part, i) => acc + part + (originals[i] ?? ''), '')
}

export async function loadOrtho(): Promise<Ortho> {
  const override = import.meta.env.VITE_TILEJSON_URL
  const candidates = override ? [override] : CANDIDATES

  for (const candidate of candidates) {
    const url = new URL(candidate, location.href).href
    const tj = await fetchJson(url)
    if (!tj || !Array.isArray(tj.tiles) || tj.tiles.length === 0) continue

    const declared = tj.tiles[0]
    const isPmtiles = declared.startsWith(PMTILES_PREFIX)
    const tiles = tj.tiles.map((t) => absolutize(t, url))

    const source: RasterSourceSpecification = {
      type: 'raster',
      tiles,
      tileSize: 256,
      minzoom: tj.minzoom,
      maxzoom: tj.maxzoom,
      attribution: tj.attribution ?? '',
    }
    // bounds があれば範囲外のタイルを要求しない（無駄な 404 を避ける）
    if (tj.bounds) source.bounds = tj.bounds

    return { tilejson: tj, source, isPmtiles, baseUrl: url }
  }

  throw new Error(
    `TileJSON を読み込めません。探索した場所: ${candidates.join(' , ')}\n` +
      'パイプラインの Step 5（05_make_tilejson.sh）を実行し、' +
      'scripts/serve.sh で配信しているか確認してください。',
  )
}
