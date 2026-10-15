/* 글씨 크기 — 데스크톱 앱 창의 배율로 화면 전체를 키우거나 줄입니다.
 *
 * 배율은 앱 창 안 웹뷰의 배율(브라우저의 Ctrl + / − 와 같은 것)입니다. 화면 전체가
 * 함께 커지고 마우스 좌표도 그대로 맞습니다. 데스크톱 앱이 화면에 열어 둔 함수
 * (`window.pywebview.api.set_zoom`·`get_zoom`)로 바꾸고 읽습니다.
 *
 * **브라우저에서는 바꾸지 않습니다** — 브라우저의 배율은 사용자가 Ctrl + / − 로 직접
 * 고릅니다. 고른 값은 데스크톱 앱이 이 컴퓨터에 기억하고, 다음에 앱을 켜면 창이 뜨는
 * 대로 그 값을 다시 겁니다. 화면은 기억하지 않고, 서버에도 보내지 않습니다.
 */

export interface ZoomStep {
  value: number
  label: string
}

/** 네 단. 「보통」이 1 입니다. 데스크톱(`desktop/notify.py` 의 `ZOOM_STEPS`)과 같은 값입니다. */
export const ZOOM_STEPS: readonly ZoomStep[] = [
  { value: 0.9, label: '작게' },
  { value: 1, label: '보통' },
  { value: 1.1, label: '크게' },
  { value: 1.2, label: '더 크게' },
]

export const DEFAULT_ZOOM = 1

/** 그 배율이 네 단 가운데 몇째인지. 네 단 밖이면 -1 입니다(Ctrl + 휠로 바꾼 값 등). */
export function stepIndex(value: number): number {
  return ZOOM_STEPS.findIndex((step) => Math.abs(step.value - value) < 1e-6)
}

/** 데스크톱 앱이 화면에 열어 둔 배율 함수. 브라우저이거나 아직 준비 전이면 없습니다. */
interface ZoomBridge {
  set_zoom: (factor: number) => Promise<boolean>
  get_zoom: () => Promise<number | null>
}

export function zoomBridge(): ZoomBridge | null {
  const api = (window as unknown as { pywebview?: { api?: Partial<ZoomBridge> } }).pywebview?.api
  return api && typeof api.set_zoom === 'function' && typeof api.get_zoom === 'function'
    ? (api as ZoomBridge)
    : null
}

/** 데스크톱 앱 안인지. 앱이 아직 함수를 열기 전이어도 앱 안이면 참입니다. */
export function inDesktop(): boolean {
  return (window as unknown as { pywebview?: unknown }).pywebview !== undefined
}
