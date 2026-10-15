import { kstClock } from '../../lib/kst'
import { moneyIn, toneOf } from '../../lib/number'
import type { VerifyRun } from '../../data/strategyRuns'

/* 실행 카드의 성과 한 줄과 일괄 조작의 대상 규칙 — 검증·진행 카드가 같은 것을 씁니다. */

/** 일괄 조작(중지·청산·종료)의 대상. **체크한 카드만**입니다 — 보는 카드는 클릭
 *  한 번에 바뀌는 상태라, 되돌릴 수 없는 청산·종료의 대상으로 삼지 않습니다.
 *  체크가 없으면 대상도 없고 단추가 잠깁니다. 대상 문장과 확인 창이 이 하나를
 *  씁니다. */
export function targetsOf(all: readonly VerifyRun[], checked: readonly string[]): VerifyRun[] {
  return all.filter((run) => checked.includes(run.id))
}

/** 대상이 없어 일괄 단추가 잠겼을 때의 안내. */
export const PICK_HINT = '카드를 체크해 대상을 고르세요'

/** 이름이 없는 전략의 이름. **id 를 이름 자리에 세우지 않습니다**(「draft-…」는
 *  사용자가 지은 값이 아니라 읽을 것이 없습니다). */
export const NAMELESS = '이름 없는 초안'

/** 목록에 없는(지운) 버전의 이름. 이름이 비어 있는 버전(「이름 없는 초안」)과
 *  다른 말입니다 — 그 버전은 아직 목록에 있습니다. */
export const DELETED = '지운 전략'

/** 실행 줄이 붙은 버전의 이름·버전. 목록을 아직 못 받았으면 둘 다 빈 글자(아직),
 *  받았는데 없으면 「지운 전략」, 있는데 이름이 비면 「이름 없는 초안」입니다. */
export function runNameOf(
  rows: readonly { id: string; name: string; version: string }[],
  versionId: string,
  ready: boolean,
): { name: string; version: string } {
  const row = rows.find((one) => one.id === versionId)
  if (row) return { name: row.name.trim() || NAMELESS, version: row.version }
  if (!ready) return { name: '', version: '' }
  return { name: DELETED, version: '' }
}

/** 대상 문장 — 「중지·청산 대상: 없음」·「… 2개」. */
export function targetLine(count: number): string {
  return `중지·청산 대상: ${count === 0 ? '없음' : `${count}개`}`
}

/** 카드의 성과 한 줄 — 「신호 n · 체결 n · 손익 · 마지막 HH:MM」.
 *
 *  **수는 서버가 센 값**입니다(화면이 이벤트·체결을 세면 목록이 잘릴 때 틀립니다).
 *  손익은 실현 + 평가이고, 둘 중 하나라도 모르면 손익 조각이 「—」입니다. 칸이 없는 옛
 *  서버면 그 조각은 「—」입니다. 끝난 실행에도 섭니다. */
export function RunStats({ run, currency }: { run: VerifyRun; currency: string }) {
  /* 칸이 없는 옛 서버(`undefined`)와 값을 모르는 서버(`null`)는 둘 다 「—」입니다.
     0 은 센 값이라 「0」으로 적습니다. */
  const count = (value: number | null | undefined) => (value == null ? '—' : value.toLocaleString('ko-KR'))
  const realized = run.realizedPl
  const open = run.openPl
  const total = realized != null && open != null ? realized + open : null
  const tone = total === null || total === 0 ? '' : toneOf(total)
  const money = total === null ? '—' : `${total > 0 ? '+' : ''}${moneyIn(total, currency)}`
  const title =
    realized === undefined
      ? undefined
      : `실현 ${realized === null ? '—' : moneyIn(realized, currency)} · 평가 ${open == null ? '—' : moneyIn(open, currency)}`
  const last = run.lastSignalAt ? kstClock(run.lastSignalAt) : '—'
  /* 조각마다 한 덩어리로 두고 **「·」 뒤에서만** 접습니다 — 「마 / 지막」처럼
     낱말 안에서 끊기거나 줄 머리에 「·」가 서지 않게, 「·」는 앞 조각 끝에
     붙입니다. */
  return (
    <span className="run-stats">
      <span className="run-stats-piece">신호 {count(run.signalCount)} ·</span>{' '}
      <span className="run-stats-piece">체결 {count(run.fillCount)} ·</span>{' '}
      <span className="run-stats-piece">
        <span className={tone || undefined} title={title}>
          {money}
        </span>{' '}
        ·
      </span>{' '}
      <span className="run-stats-piece">마지막 {last}</span>
    </span>
  )
}
