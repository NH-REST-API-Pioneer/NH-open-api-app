/**
 * 빌드 산출 디렉터리(backend/static)를 비웁니다.
 *
 * Vite의 `emptyOutDir` 는 내부적으로 동기 `fs.rmSync({ recursive: true })` 를 사용하는데,
 * 경로에 한글 등 비-ASCII 문자가 포함되어 있으면 Windows에서 Node가
 * STATUS_STACK_BUFFER_OVERRUN(0xC0000409)으로 크래시합니다.
 * 동일 조건에서 비동기 `fs.promises.rm` 은 정상 동작하므로 이쪽으로 직접 정리합니다.
 */
import { rm } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const outDir = path.resolve(here, '..', '..', 'backend', 'static')

await rm(outDir, { recursive: true, force: true })
