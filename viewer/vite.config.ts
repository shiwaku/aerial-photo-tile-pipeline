import { defineConfig } from 'vite'

export default defineConfig(({ command }) => ({
  // GitHub Pages 配信時のサブパス。ローカルの scripts/serve.sh から配信する場合は
  // タイルと同じディレクトリに dist を置くため相対パスで解決させたい。
  // './' にすると index.html 内のアセット参照が相対になり、どちらでも動く。
  base: command === 'build' ? './' : '/',
  server: {
    port: 5173,
    strictPort: true,
    // WSL から /mnt/c（Windows 側）のファイルを見る構成では inotify イベントが
    // 届かず、書き換えても dev サーバが古い結果を返し続ける。ポーリングで検知する。
    watch: {
      usePolling: true,
      interval: 300,
    },
  },
  build: {
    target: 'es2022',
  },
  define: {
    __BUILD_TIME__: JSON.stringify(
      new Date().toISOString().replace('T', ' ').slice(0, 16) + ' UTC',
    ),
  },
}))
