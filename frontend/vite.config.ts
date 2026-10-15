import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 개발 모드에서 /api 요청을 백엔드(uvicorn)로 전달
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // 실시간(`/api/stream`)은 웹소켓이라 규약을 바꿔 잇는 단계가 따로
        // 필요합니다. 이것이 없으면 조회는 되는데 실시간만 안 붙고, 화면에는
        // 「값이 안 흐른다」로만 보여 원인이 개발 서버에 있다는 것을 알기
        // 어렵습니다. 배포 모드는 같은 서버가 직접 받으므로 해당 없습니다.
        ws: true,
      },
    },
  },
  build: {
    // 백엔드가 그대로 서빙할 수 있도록 backend/static 으로 직접 빌드합니다.
    outDir: '../backend/static',
    // Vite의 emptyOutDir는 비-ASCII 경로에서 Node를 크래시시키므로 사용하지 않습니다.
    // 대신 prebuild 단계의 scripts/clean-outdir.mjs 가 디렉터리를 비웁니다.
    emptyOutDir: false,
  },
})
