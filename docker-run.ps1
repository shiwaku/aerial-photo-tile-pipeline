# Docker イメージでパイプラインを実行する Windows（PowerShell）用のラッパー。
# docker-run.sh と同じ使い方。Windows PowerShell 5.1 と PowerShell 7 の両方で動く。
#
# Usage: .\docker-run.ps1 config\<name>.conf [--from N] [--to N]
#        .\docker-run.ps1 ./scripts/<step>.sh config/<name>.conf ...   # 個別ステップ
#        .\docker-run.ps1 selftest                                       # オープンデータで動作確認
#
# 作業フォルダ（既定はカレントディレクトリ）の data\ output\ config\ をコンテナの
# /work 以下にマウントする。設定ファイルのパスはこの作業フォルダからの相対で書く。
#
# 環境変数:
#   PROJECT_DIR  作業フォルダ（既定: カレントディレクトリ）
#   IMAGE        使うイメージ（既定: 手元で build した aerial-tile-pipeline。無ければ GHCR の公開イメージ）
#
# 実行がブロックされる場合は次のように起動する:
#   powershell -ExecutionPolicy Bypass -File .\docker-run.ps1 selftest
#
# このファイルは BOM 付き UTF-8・CRLF で保存すること（5.1 が日本語を正しく読むため）。

# $ErrorActionPreference は Stop にしない。5.1 では外部コマンドの標準エラーを
# リダイレクトしただけで例外になるため、失敗は終了コードで見る

function Fail([string]$msg) {
  [Console]::Error.WriteLine("ERROR: $msg")
  exit 1
}

$projectDir = if ($env:PROJECT_DIR) { $env:PROJECT_DIR } else { (Get-Location).Path }
$projectDir = (Resolve-Path -LiteralPath $projectDir -ErrorAction Stop).Path
$localImage = 'aerial-tile-pipeline'
$publicImage = 'ghcr.io/shiwaku/aerial-photo-tile-pipeline:latest'

if ($args.Count -lt 1) { Fail "使い方: .\docker-run.ps1 config\<name>.conf [--from N] [--to N]" }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Fail "docker が見つかりません" }
# 手元にイメージがあれば $true、無ければ $false を返す。Docker に接続できないなど、
# 「無い」以外の理由で確かめられないときは止める。どんな失敗でも「無い」とみなすと、
# Docker の一時的な不調で、気付かないうちに古い公開イメージで動くことがある
function Test-Image([string]$name) {
  $err = (& docker image inspect $name 2>&1 | Out-String)
  if ($LASTEXITCODE -eq 0) { return $true }
  if ($err -match 'No such image') { return $false }
  Fail "イメージ $name を確かめられません（Docker Desktop が起動しているか確認してください）: $($err.Trim())"
}

if ($env:IMAGE) {
  $image = $env:IMAGE
} elseif (Test-Image $localImage) {
  $image = $localImage
  [Console]::Error.WriteLine("手元でビルドしたイメージ $image を使います")
} else {
  $image = $publicImage
  [Console]::Error.WriteLine("公開イメージ $image を使います")
}
# レジストリを含まない名前は手元にあるはずなので、無ければ build を促す（含む名前は docker run が取得する）
if ($image -notlike '*/*') {
  if (-not (Test-Image $image)) {
    Fail "イメージ $image がありません。リポジトリで docker build -t $image . を実行してください"
  }
}

# コンテナの中は Linux なので、パスの区切りを / に直す
$rest = @($args | ForEach-Object { "$_" -replace '\\', '/' })
$first = $rest[0]
if ($first -like '*.conf') {
  $confPath = Join-Path $projectDir $first
  if (-not (Test-Path -LiteralPath $confPath -PathType Leaf)) { Fail "設定ファイルが見つかりません: $confPath" }
  $cmd = @('./scripts/run_pipeline.sh') + $rest
} elseif ($first -eq 'selftest') {
  $cmd = @('./scripts/selftest.sh') + @($rest | Select-Object -Skip 1)
} else {
  $cmd = $rest
}

foreach ($d in 'data', 'output', 'config') {
  New-Item -ItemType Directory -Force -Path (Join-Path $projectDir $d) | Out-Null
}

$dockerArgs = @(
  'run', '--rm',
  '-e', 'HOME=/tmp',
  '-e', "HOST_PROJECT_DIR=$projectDir",
  '-v', "$(Join-Path $projectDir 'data'):/work/data",
  '-v', "$(Join-Path $projectDir 'output'):/work/output",
  '-v', "$(Join-Path $projectDir 'config'):/work/config:ro",
  $image
) + $cmd

# 長時間ジョブの途中でスリープしないよう、実行中だけ抑止する（Windows のみ）
$onWindows = [System.Environment]::OSVersion.Platform -eq 'Win32NT'
if ($onWindows -and -not ('AerialTile.Power' -as [type])) {
  Add-Type -Namespace AerialTile -Name Power -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll")]
public static extern uint SetThreadExecutionState(uint esFlags);
'@
}
# ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x00000001)
if ($onWindows) { [void][AerialTile.Power]::SetThreadExecutionState([uint32]2147483649) }
try {
  & docker @dockerArgs
  $code = $LASTEXITCODE
} finally {
  if ($onWindows) { [void][AerialTile.Power]::SetThreadExecutionState([uint32]2147483648) }
}
exit $code
