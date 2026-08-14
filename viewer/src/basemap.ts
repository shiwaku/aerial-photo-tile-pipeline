import type { RasterLayerSpecification, StyleSpecification } from 'maplibre-gl'
import type { Theme } from './theme'

/**
 * 背景地図。
 *
 * 参照実装（dm-converter）は地理院の最適化ベクトルタイルのスタイル JSON を同梱し、
 * 色を明度反転してダーク化している。こちらはオルソ画像が主役で背景はその下に
 * ほぼ隠れるため、680KB のスタイル JSON を持つ価値が薄い。ラスタタイルを使い、
 * ダークは paint プロパティで落とす方式にした。
 *
 * ラスタなので「色を反転した夜間スタイル」にはならない。あくまで減光である。
 */
export type Basemap = 'pale' | 'std' | 'photo' | 'blank'

export const BASEMAPS: { key: Basemap; label: string }[] = [
  { key: 'pale', label: '淡色' },
  { key: 'std', label: '標準' },
  { key: 'photo', label: '写真' },
  { key: 'blank', label: '白図' },
]

const GSI_ATTRIBUTION =
  '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noopener">地理院タイル</a>'

interface TileDef {
  url: string
  maxzoom: number
}

const TILES: Record<Exclude<Basemap, 'blank'>, TileDef> = {
  pale: { url: 'https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png', maxzoom: 18 },
  std: { url: 'https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png', maxzoom: 18 },
  photo: {
    url: 'https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg',
    maxzoom: 18,
  },
}

/**
 * ダークテーマでの背景の落とし方。
 * オルソ画像より背景が明るいと目が背景に引っ張られるため、明度と彩度を下げる。
 * 写真背景は元から暗いので落としすぎないようにしている。
 */
function darkPaint(base: Basemap): RasterLayerSpecification['paint'] {
  if (base === 'photo') return { 'raster-brightness-max': 0.7, 'raster-saturation': -0.3 }
  return { 'raster-brightness-max': 0.45, 'raster-saturation': -0.6, 'raster-contrast': -0.1 }
}

export function getBasemapStyle(base: Basemap, theme: Theme): StyleSpecification {
  const background: StyleSpecification['layers'][number] = {
    id: 'bg',
    type: 'background',
    paint: { 'background-color': theme === 'dark' ? '#14161a' : '#ffffff' },
  }

  if (base === 'blank') {
    return { version: 8, sources: {}, layers: [background] }
  }

  const def = TILES[base]
  return {
    version: 8,
    sources: {
      basemap: {
        type: 'raster',
        tiles: [def.url],
        tileSize: 256,
        maxzoom: def.maxzoom,
        attribution: GSI_ATTRIBUTION,
      },
    },
    layers: [
      background,
      {
        id: 'basemap',
        type: 'raster',
        source: 'basemap',
        paint: theme === 'dark' ? darkPaint(base) : {},
      },
    ],
  }
}
