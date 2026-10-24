import { useSyncExternalStore } from 'react'
import { kstClock } from '../lib/kst'

/* 마지막으로 시세가 도착한 시각.
 *
 * 머리의 「마지막 시세 HH:MM」이 이 값입니다. **시세 값이 실제로 온 때만** 찍습니다
 * — 실시간 방송(현재가·호가·체결)과 시세 조회의 답(현재가·호가·만기 목록·체인).
 * 연결 확인·종목 마스터·계좌·전략의 답은 시세가 아니라서 찍지 않습니다. 그것들로
 * 찍으면 시세가 멈춰도 시각이 계속 새로 서서, 멈춘 것을 알아볼 단서가 사라집니다.
 *
 * 연결이 끊긴 동안에는 아무도 이 함수를 부르지 않으므로 시각이 그대로 멈춥니다.
 */

interface LastQuote {
  /** `HH:MM`. 아직 한 번도 안 왔으면 빈 글자. */
  label: string
  /** 마지막으로 도착한 순간(ms). 멈춤 판정에 씁니다. */
  at: number | null
}

let last: LastQuote = { label: '', at: null }
/** `last.label` 을 지은 분(1970 년부터 센 분). 한국시간은 UTC 와 분 단위로 어긋나지
 *  않아, 이 번호가 같으면 한국시각 `HH:MM` 도 같습니다. */
let lastMinute: number | null = null
const listeners = new Set<() => void>()

/** 시세가 도착했다고 적습니다. 방송은 1초에 여러 번 오므로, 분이 바뀌지 않았으면
 *  순간만 고쳐 두고 화면에는 알리지 않습니다 — 보이는 글자가 그대로라서입니다.
 *  글자(한국시각)도 분이 바뀔 때만 짓습니다. */
export function noteQuoteArrival(): void {
  const now = Date.now()
  const minute = Math.floor(now / 60_000)
  if (minute === lastMinute) {
    last.at = now
    return
  }
  lastMinute = minute
  last = { label: kstClock(now), at: now }
  for (const listener of listeners) listener()
}

/** 마지막 시세가 도착한 순간(ms). 아직 없으면 `null`. */
export function lastQuoteAt(): number | null {
  return last.at
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** 머리에 세울 `HH:MM`. 아직 한 번도 안 왔으면 빈 글자입니다. */
export function useLastQuoteLabel(): string {
  return useSyncExternalStore(subscribe, () => last.label, () => '')
}
