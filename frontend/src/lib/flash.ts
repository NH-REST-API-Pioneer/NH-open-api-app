/** 값이 바뀐 자리를 아주 잠깐 비추는 훅.
 *
 *  실시간이 붙으면 같은 자리의 숫자가 소리 없이 갈립니다. 화면을 보고 있어도
 *  **무엇이 바뀌었는지는 안 보입니다** — 자릿수가 같으면 글자 모양까지 그대로라
 *  눈이 변화를 못 잡습니다. 그래서 바뀐 칸만 한 번 비추고 곧 걷습니다.
 *
 *  **아주 짧게 비춥니다.** 길게 두면 다음 값이 오는 동안에도 남아, 화면이
 *  줄곧 깜빡이는 판이 됩니다. 값이 자주 움직이는 종목일수록 그렇습니다.
 *
 *  **오르내림이 곧 뜻인 자리에만 씁니다** — 헤더의 현재가와 호가 사다리의 가격
 *  칸입니다. 잔량처럼 늘고 주는 것이 오르내림이 아닌 자리에 상승색을 입히면
 *  다른 뜻이 됩니다.
 */
import { useEffect, useRef, useState } from 'react'

/** 비추는 시간(ms).
 *
 *  **이 값을 늘리지 마세요.** 깜빡임이 방향색을 쓰는데, 바로 옆의 전일대비와
 *  호가 잔량 막대도 같은 두 색을 씁니다. 지금 셋이 안 부딪히는 것은 깜빡임이
 *  **잠깐 서는 사건**이고 나머지는 **늘 서 있는 상태**이기 때문입니다. 이 값을
 *  키워 깜빡임이 상태처럼 보이기 시작하면 같은 자리에서 두 가지 뜻의 색이
 *  겹칩니다 — 「직전 값보다」와 「어제보다」는 다른 말입니다. */
export const FLASH_MS = 100

/** 값이 움직인 쪽. */
export type FlashWay = 'up' | 'down'

/** 숫자가 바뀌면 그 방향으로 잠깐.
 *
 *  `of` 는 이 숫자가 **누구의 값인가**입니다. 종목을 바꾸면 같은 자리에 다른
 *  종목의 값이 서는데, 그것은 값이 움직인 것이 아니라 보는 대상이 바뀐
 *  것입니다. 견줄 것이 아니라 안 비춥니다.
 *
 *  값이 없으면(`null`) 비추지 않습니다 — 못 받았거나 아직 안 받은 자리라,
 *  값이 사라진 것과 값이 움직인 것은 다릅니다.
 */
export function useFlash(value: number | null, of = ''): FlashWay | null {
  const held = useRef({ value, of })
  const [way, setWay] = useState<FlashWay | null>(null)

  useEffect(() => {
    const before = held.current
    held.current = { value, of }
    if (before.of !== of) return
    if (before.value === null || value === null || before.value === value) return

    setWay(value > before.value ? 'up' : 'down')
    const timer = window.setTimeout(() => setWay(null), FLASH_MS)
    return () => window.clearTimeout(timer)
  }, [value, of])

  return way
}
