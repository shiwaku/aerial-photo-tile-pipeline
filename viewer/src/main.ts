import maplibregl from 'maplibre-gl'
import { Protocol } from 'pmtiles'
import 'maplibre-gl/dist/maplibre-gl.css'

import { BASEMAPS, getBasemapStyle, type Basemap } from './basemap'
import { loadOrtho, LAYER_ID, SOURCE_ID, type Ortho } from './ortho'
import { applyThemeAttr, initialTheme, type Theme } from './theme'
import './style.css'

let theme: Theme = initialTheme()
let base: Basemap = 'pale'
applyThemeAttr(theme)

const isMobile = window.matchMedia('(max-width: 640px)').matches

const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T

// ---- データ読み込み --------------------------------------------------------
// TileJSON が無いと何も表示できないため、地図を作る前に読む。

let ortho: Ortho
try {
  ortho = await loadOrtho()
} catch (e) {
  const el = $('error')
  el.hidden = false
  el.textContent = e instanceof Error ? e.message : String(e)
  throw e
}

// PMTiles プロトコルは常に登録する。オルソが XYZ 配信でも、背景の
// 最適化ベクトルタイルが PMTiles で配信されているため必要になる。
maplibregl.addProtocol('pmtiles', new Protocol().tile)

const tj = ortho.tilejson
let orthoOn = true
let orthoOpacity = 1

// ---- 地図 ------------------------------------------------------------------

const map = new maplibregl.Map({
  container: 'map',
  style: await getBasemapStyle(base, theme),
  center: [tj.center?.[0] ?? 138.4, tj.center?.[1] ?? 35.0],
  zoom: tj.center?.[2] ?? tj.minzoom,
  minZoom: Math.max(0, tj.minzoom - 2),
  // 元データより細かく拡大しても情報は増えないが、圧縮ノイズの確認のため +2 まで許す
  maxZoom: tj.maxzoom + 2,
  maxPitch: 85,
  // 地図位置を URL の #ズーム/緯度/経度 に反映（共有・リロード時の位置維持）
  hash: true,
  attributionControl: false,
  // モバイルはGPU/メモリが限られるため保持タイル数と描画解像度を絞る。
  // 逼迫すると WebGL コンテキストが失われ地図がまるごと消えるため、その圧を下げる。
  maxTileCacheSize: isMobile ? 24 : undefined,
  pixelRatio: isMobile ? Math.min(window.devicePixelRatio || 1, 2) : undefined,
})

map.addControl(
  new maplibregl.NavigationControl({ showCompass: true, visualizePitch: true }),
  'top-right',
)
map.addControl(
  new maplibregl.GeolocateControl({
    positionOptions: { enableHighAccuracy: false },
    fitBoundsOptions: { maxZoom: 18 },
    trackUserLocation: true,
    showUserLocation: true,
  }),
  'top-right',
)
map.addControl(new maplibregl.FullscreenControl(), 'top-right')
map.addControl(new maplibregl.ScaleControl({ maxWidth: 200, unit: 'metric' }), 'bottom-left')
map.addControl(new maplibregl.AttributionControl({ compact: true }))

// ---- オルソ層の投入 --------------------------------------------------------
// 背景スタイルを差し替えると全レイヤーが消えるため、切替のたびに貼り直す。

function addOrthoLayer(): void {
  if (!map.getSource(SOURCE_ID)) map.addSource(SOURCE_ID, ortho.source)
  if (!map.getLayer(LAYER_ID)) {
    map.addLayer({
      id: LAYER_ID,
      type: 'raster',
      source: SOURCE_ID,
      layout: { visibility: orthoOn ? 'visible' : 'none' },
      paint: { 'raster-opacity': orthoOpacity },
    })
  }
}

// ラスタ同士の切替でも、白図（sources なし）との往復で diff 適用が破綻するため
// diff:false で作り直す。setStyle 直後は isStyleLoaded() が旧スタイルで true を
// 返して競合するので、idle を待ってから貼り直す。
async function reloadStyle(): Promise<void> {
  map.setStyle(await getBasemapStyle(base, theme), { diff: false })
  map.once('idle', addOrthoLayer)
}

// ---- テーマ切替 ------------------------------------------------------------
const themeBtn = $<HTMLButtonElement>('theme-btn')
const renderThemeBtn = (): void => {
  themeBtn.textContent = theme === 'dark' ? '☀️' : '🌙'
}
themeBtn.addEventListener('click', () => {
  theme = theme === 'dark' ? 'light' : 'dark'
  applyThemeAttr(theme)
  renderThemeBtn()
  void reloadStyle()
})

// ---- パネル開閉 ------------------------------------------------------------
const panel = $('panel')
const collapseBtn = $<HTMLButtonElement>('collapse-btn')
const renderCollapseBtn = (): void => {
  collapseBtn.textContent = panel.classList.contains('collapsed') ? '▾' : '▴'
}
collapseBtn.addEventListener('click', () => {
  panel.classList.toggle('collapsed')
  renderCollapseBtn()
})

// ---- オルソの表示・不透明度 ------------------------------------------------
const orthoToggle = $<HTMLInputElement>('ortho-toggle')
const opacityBox = $('ortho-opacity')
const opacityRange = $<HTMLInputElement>('opacity-range')
const opacityVal = $('opacity-val')

orthoToggle.addEventListener('change', () => {
  orthoOn = orthoToggle.checked
  opacityBox.toggleAttribute('hidden', !orthoOn)
  if (map.getLayer(LAYER_ID)) {
    map.setLayoutProperty(LAYER_ID, 'visibility', orthoOn ? 'visible' : 'none')
  }
})

opacityRange.addEventListener('input', () => {
  orthoOpacity = Number(opacityRange.value)
  opacityVal.textContent = `${Math.round(orthoOpacity * 100)}%`
  if (map.getLayer(LAYER_ID)) map.setPaintProperty(LAYER_ID, 'raster-opacity', orthoOpacity)
})

// ---- 整備範囲へのフィット --------------------------------------------------
const fitBtn = $<HTMLButtonElement>('fit-btn')
const fitBounds = (animate: boolean): void => {
  if (!tj.bounds) return
  map.fitBounds(tj.bounds, { padding: 24, animate })
}
fitBtn.addEventListener('click', () => fitBounds(true))
fitBtn.disabled = !tj.bounds

// ---- 背景地図スイッチャー（右下） ------------------------------------------
class BasemapControl implements maplibregl.IControl {
  private el!: HTMLElement
  onAdd(): HTMLElement {
    this.el = document.createElement('div')
    this.el.className = 'maplibregl-ctrl basemap-switch'
    for (const { key, label } of BASEMAPS) {
      const btn = document.createElement('button')
      btn.type = 'button'
      btn.textContent = label
      btn.dataset.base = key
      btn.setAttribute('aria-selected', String(key === base))
      btn.addEventListener('click', () => setBase(key))
      this.el.append(btn)
    }
    return this.el
  }
  onRemove(): void {
    this.el.remove()
  }
  sync(): void {
    for (const btn of this.el.querySelectorAll<HTMLButtonElement>('button')) {
      btn.setAttribute('aria-selected', String(btn.dataset.base === base))
    }
  }
}
const basemapCtrl = new BasemapControl()
map.addControl(basemapCtrl, 'bottom-right')

function setBase(next: Basemap): void {
  if (next === base) return
  base = next
  basemapCtrl.sync()
  void reloadStyle()
}

// ---- ズームレベル表示 ------------------------------------------------------
// 最大ZL を超えると引き伸ばし表示になる。GSD より細かい情報は増えないため明示する。
const zoomBadge = $('zoom-badge')
const zoomNote = $('zoom-note')
const renderZoom = (): void => {
  const z = map.getZoom()
  zoomBadge.textContent = `Z${z.toFixed(1)}`
  zoomNote.textContent =
    z > tj.maxzoom + 0.5
      ? `最大ZL（Z${tj.maxzoom}）を超えています。引き伸ばし表示のため情報は増えません`
      : `このデータの収録範囲は Z${tj.minzoom}–Z${tj.maxzoom}`
}
map.on('zoom', renderZoom)

// ---- データ情報 ------------------------------------------------------------
function renderMeta(): void {
  const rows: [string, string][] = [
    ['配信形態', ortho.isPmtiles ? 'PMTiles（単一ファイル）' : 'XYZ ディレクトリ'],
    ['タイル形式', (tj.format ?? '-').toUpperCase()],
    ['ズーム範囲', `Z${tj.minzoom} – Z${tj.maxzoom}`],
  ]
  if (tj.bounds) {
    const [w, s, e, n] = tj.bounds
    rows.push(['範囲（西南）', `${w.toFixed(5)}, ${s.toFixed(5)}`])
    rows.push(['範囲（東北）', `${e.toFixed(5)}, ${n.toFixed(5)}`])
  }
  $('meta').innerHTML = rows
    .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`)
    .join('')
}

// ---- 初期化 ----------------------------------------------------------------
if (tj.name) {
  document.title = `${tj.name} | オルソ画像ビューワ`
  $('title').textContent = tj.name
}
$('attribution').innerHTML = tj.attribution ?? ''
$('build-ver').textContent = `build: ${__BUILD_TIME__}`
renderThemeBtn()
renderMeta()
renderZoom()
if (isMobile) panel.classList.add('collapsed')
renderCollapseBtn()

map.on('load', () => {
  addOrthoLayer()
  // hash（#z/lat/lng）が無い初回だけ整備範囲に合わせる。
  // hash がある場合はその位置を尊重する（共有リンクを壊さない）。
  if (!location.hash) fitBounds(false)
})

// WebGL コンテキスト消失からの復帰。iOS Safari 等ではメモリ逼迫時に GL コンテキストが
// 失われ、レイヤーがまるごと消えて戻らないことがある。復帰時に貼り直して自動回復する。
const canvas = map.getCanvas()
canvas.addEventListener(
  'webglcontextlost',
  (ev) => {
    // preventDefault しないと自動復帰イベントが発火しない
    ev.preventDefault()
  },
  false,
)
canvas.addEventListener(
  'webglcontextrestored',
  () => {
    if (map.isStyleLoaded()) addOrthoLayer()
    else map.once('idle', addOrthoLayer)
  },
  false,
)

// デバッグ/外部連携用にマップを公開
;(window as unknown as { __map: maplibregl.Map }).__map = map

// PWA: Service Worker 登録（本番のみ。dev では HMR を妨げないよう無効）
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register(`${import.meta.env.BASE_URL}sw.js`).catch(() => {})
  })
  let refreshing = false
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (refreshing) return
    refreshing = true
    window.location.reload()
  })
}
