import { useEffect, useRef } from 'react'
import { loadRunSnapshot, loadRuns, refreshConditions } from '../../data/strategyStore'
import type { useRunView } from './useRunView'

type ViewValues = ReturnType<typeof useRunView>

/** 받아 오기 — 목록(처음·환경이 바뀔 때), 보는 실행의 한 벌, 봉마다 조건 표. */
export function useRunLoads({
  environment,
  shown,
}: {
  environment: ViewValues['environment']
  shown: ViewValues['shown']
}) {
  /* 화면이 열릴 때 목록을 받아 옵니다. 그 뒤로는 허브가 보내 주는 것으로
     채웁니다 — 검증 화면과 같은 자리를 씁니다. */
  useEffect(() => {
    void loadRuns()
  }, [])
  /* 접속 환경이 바뀌면 목록을 다시 받습니다. **세울 수 있는 갈래(`accountModes`)는
     이 조회에만 실려 옵니다** — 안 받으면 환경을 바꾼 뒤에도 앞 환경의 갈래가
     남아, 확인 얼굴이 계속 「확인하는 중」에 머뭅니다. 처음 연 때는 위가 받습니다. */
  const seenGeneration = useRef(environment.generation)
  useEffect(() => {
    if (seenGeneration.current === environment.generation) return
    seenGeneration.current = environment.generation
    void loadRuns()
  }, [environment.generation])

  /* 보는 실행이 바뀌면 그 실행의 한 벌을 받습니다. 체결·이벤트는 목록 줄에
     없습니다. */
  useEffect(() => {
    void loadRunSnapshot(shown?.id ?? '')
  }, [shown?.id])

  /* 조건 표는 **허브 방송에 없습니다** — 보는 실행의 판정 봉이 바뀌면 그 실행의 표만
     한 번 다시 받습니다(봉당 한 번, 검증 탭과 같은 길). 받는 중이면 겹쳐 내지 않고
     다음 봉에 받습니다. */
  const conditionsFlying = useRef(false)
  const seenBar = useRef<{ id: string; bars: number | null } | null>(null)
  useEffect(() => {
    if (!shown) return
    const seen = seenBar.current
    seenBar.current = { id: shown.id, bars: shown.bars }
    if (!seen || seen.id !== shown.id || seen.bars === shown.bars) return
    if (conditionsFlying.current) return
    conditionsFlying.current = true
    void refreshConditions(shown.id).finally(() => {
      conditionsFlying.current = false
    })
  }, [shown?.id, shown?.bars])
}
