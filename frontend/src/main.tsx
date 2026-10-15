import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// 토큰과 기본 스타일이 먼저 실려야 화면별 스타일이 그 위에 얹힙니다.
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
