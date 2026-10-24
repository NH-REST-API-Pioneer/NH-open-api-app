import { useCallback, useState } from 'react'

/* 사용자가 고른 것을 브라우저에 남깁니다.
 *
 * 남기는 것은 「무엇을 어떻게 볼지」이지 값이 아닙니다. 값은 화면을 나갔다
 * 오면 낡은 것이라, 돌아왔을 때 옛 값이 새 값인 척하면 그게 더 나쁩니다.
 *
 * 저장소는 브라우저 설정에 따라 막혀 있을 수 있어 읽기와 쓰기를 모두 감쌉니다.
 * 막혀 있으면 값이 남지 않을 뿐 화면은 그대로 동작합니다.
 *
 * 인증 정보(App Key·Secret·계좌번호)에는 쓰지 마세요. 여기 넣은 것은 앱을
 * 껐다 켜도 남고 브라우저 개발자 도구에서 그대로 보입니다. 그 값들은 사용자
 * 홈의 설정 파일에만 두고, 화면에는 가린 표시만 내려옵니다.
 */
export function useStoredState<T>(key: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key)
      return raw === null ? initial : (JSON.parse(raw) as T)
    } catch {
      return initial
    }
  })

  const store = useCallback(
    (next: T) => {
      setValue(next)
      try {
        localStorage.setItem(key, JSON.stringify(next))
      } catch {
        // 저장이 막혀 있어도 이번 세션 동안은 값이 유지됩니다.
      }
    },
    [key],
  )

  return [value, store]
}
