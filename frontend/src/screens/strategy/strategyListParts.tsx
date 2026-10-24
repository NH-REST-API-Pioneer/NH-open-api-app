import { RECORD_KINDS, accountOf, currencyOf, recentOf, type StrategyVersion } from '../../data/strategyList'
import { instrumentOfRole } from '../../data/instrumentRoles'
import { NO_CONDITIONS } from '../../data/strategyStore'
import { Count, Num, currencyCode, currencyDigits, toneOf } from '../../lib/number'
import { RECORD_MODE, type RecordKind } from '../../data/strategyList'
import { RunKindBadge } from './runKind'

export const MARKETS = ['전체', '국내', '해외'] as const
export const STATUSES = ['전체', '실행 중', '중지', '초안', '보관'] as const
/* 기록 유형의 낱말은 성과분석 화면과 한 벌에서 나옵니다. 목록에서 한 장부로
 * 본 사람이 분석에서 같은 것을 고를 수 있어야 합니다.
 *
 * 이 필터는 줄을 거르면서 **성과 칸이 어느 장부의 값인지도 고릅니다**
 * (`recordShows`·`recentOf`). 한 버전이 앱 시뮬레이션과 모의 계좌 양쪽으로
 * 돌았을 수 있어, 줄의 기록 유형 칸만으로 거르면 다른 장부의 성과를 볼 길이
 * 없습니다. */
export const RECORDS = ['전체', ...RECORD_KINDS] as const

/** 필터 다섯의 기본값. 「초기화」가 돌아가는 값이고, 좁은 폭의 「필터 · N」이
 *  세는 기준입니다 — 두 자리가 따로 적으면 초기화한 뒤에도 N 이 남습니다. */
export const FILTER_DEFAULTS = {
  query: '',
  market: '전체' as (typeof MARKETS)[number],
  status: '전체' as (typeof STATUSES)[number],
  record: '전체' as (typeof RECORDS)[number],
  runningOnly: false,
}

/** 금액. 통화가 섞이므로 단위를 늘 붙입니다. */
export function Money({ value, currency, signed }: { value: number; currency: string; signed?: boolean }) {
  /* 통화를 모르면 단위 없는 수를 세우지 않습니다(`moneyIn` 과 같은 규칙). */
  if (currencyCode(currency) === '') return <>—</>
  if (currencyCode(currency) === 'KRW') {
    return (
      <>
        <Count value={value} signed={signed} />원
      </>
    )
  }
  return (
    <>
      <Num value={value} decimals={currencyDigits(currencyCode(currency)) ?? 2} signed={signed} /> {currencyCode(currency)}
    </>
  )
}

/* 손익만 방향색과 부호를 씁니다. 증거금 예산·최대 낙폭은 수준값이라 색이
   없습니다 — 예산에 초록·빨강이 붙으면 「많아서 좋다」로 읽히고, 낙폭은
   이미 크기가 곧 나쁨이라 부호를 붙일 자리가 없습니다. */
export function Pl({ value, currency }: { value: number; currency: string }) {
  return (
    <span className={toneOf(value) || undefined}>
      <Money value={value} currency={currency} signed />
    </span>
  )
}

/** 아직 값이 없는 칸. 「0」과 갈라야 하므로 빈 칸으로 두지 않습니다. */
export function Blank() {
  return <span className="dead">—</span>
}

/** 표의 최근 30일 두 칸(순손익·승률). **목록이 보는 기록 유형의 값**입니다
 *  (`recentOf`). 그 유형의 거래가 없으면 「—」이고 0 과 가릅니다. */
export function RecentCells({ row, record }: { row: StrategyVersion; record: (typeof RECORDS)[number] }) {
  const seen = recentOf(row, record)
  return (
    <>
      <td>
        {seen.pl == null ? (
          <Blank />
        ) : (
          <>
            <Pl value={seen.pl} currency={row.currency} />
            {/* **이 수가 어느 장부의 것인지**를 값 옆에 답니다. 행마다
                갈리는 축이라 표 위에는 못 적고, 왼쪽 필터에만 있으면
                결과를 보는 사람은 그 축이 있는 줄도 모릅니다.
                값이 아니라 출처라 **갈래 배지**입니다 — 진행·검증 화면과 같은
                얼굴이라 어느 장부인지 한 번에 이어집니다. */}
            <span className="stg-record">
              {seen.record in RECORD_MODE ? (
                <RunKindBadge kind={RECORD_MODE[seen.record as RecordKind]} />
              ) : (
                seen.record
              )}
            </span>
          </>
        )}
      </td>
      <td>
        {seen.winRate == null ? (
          <>
            <Blank />
            {/* 거래는 있는데 손익을 셀 수 없는 갈래 — 거래 수를 붙여 거래가 없는
                갈래와 가릅니다. */}
            {seen.trades != null && seen.trades > 0 && <span className="stg-trades">({seen.trades}건)</span>}
          </>
        ) : (
          <>
            <span className="stg-win">{seen.winRate}%</span>
            <span className="stg-trades">({seen.trades}건)</span>
          </>
        )}
      </td>
    </>
  )
}

/** 버전 이름에서 상태 낱말을 뺍니다. **상태는 배지가 이미 말합니다** —
 *  「v1 초안」 옆에 「초안」 배지가 서면 한 줄이 같은 것을 두 번 말합니다.
 *  저장되는 값은 그대로이고 적는 모양만 다릅니다. */
export function versionOnly(version: string): string {
  return version.replace(/\s*초안$/, '')
}

/** 설정이 글자로 들고 있는 돈을 상세에 적습니다. 안 정했으면 「—」입니다 —
 *  0 은 정한 값이라 그대로 적습니다(저장은 검증이 막습니다). */
export function amount(value: string, currency: string) {
  const text = value.trim()
  if (text === '' || Number.isNaN(Number(text))) return <Blank />
  return <Money value={Number(text)} currency={currency} />
}

/** 설정이 글자로 들고 있는 수를 상세에 적습니다. */
export function count(value: string, unit: string) {
  const text = value.trim()
  if (text === '' || Number.isNaN(Number(text))) return <Blank />
  return `${Number(text).toLocaleString('ko-KR')}${unit}`
}

/** 목적격 토씨(을/를) — 끝 글자가 받침으로 끝나면 「을」. 숫자는 읽는 소리로
 *  가립니다(1·3·6·7·8·0 은 받침, 2·4·5·9 는 받침 없음). 「v2를」·「v1을」. */
export function objectMark(word: string): string {
  const last = word.trim().slice(-1)
  if (/[0-9]/.test(last)) return '136780'.includes(last) ? '을' : '를'
  const code = last.charCodeAt(0) - 0xac00
  if (code >= 0 && code < 11172) return code % 28 !== 0 ? '을' : '를'
  return '을'
}

/** 새 전략 한 줄 — 「새 전략」 단추가 설정 탭에 여는 초안입니다. 목록 탭과 설정 탭의
 *  빈 화면이 같은 것을 씁니다. */
export function blankDraft(name: string, version: string): StrategyVersion {
  return {
    id: `draft-${Date.now()}`,
    groupId: `draft-${Date.now()}`,
    name,
    version,
    market: 'domestic',
    /* 새 전략의 **기본값 제안**입니다. 역할 표가 남아 있는 것은 이 한 자리
       때문이고, 사용자는 설정에서 바로 바꿉니다. */
    ...instrumentOfRole('kospiFutures'),
    role: 'kospiFutures',
    instrumentFallback: '코스피200 선물',
    status: '초안',
    record: '모의 계좌 거래',
    tags: [],
    pl: null,
    /* 계좌·통화는 시장이 정합니다(`accountOf`·`currencyOf`) — 품목을 해외로
       바꾸면 설정 화면이 같은 함수로 갈아 끼웁니다. */
    currency: currencyOf('domestic', ''),
    winRate: null,
    trades: null,
    maxDrawdown: null,
    summary: NO_CONDITIONS,
    account: accountOf('domestic'),
    marginBudget: 0,
    /* 새 전략은 한도도 아직 안 정한 값(0)입니다 — 예산과 같은 자리입니다. */
    dailyLoss: 0,
    orderQty: 1,
    /* 새로 만든 전략은 **빈 조건·예산 0** 으로 열립니다 — 요약 한 줄이
       「조건을 아직 안 넣었습니다」인데 설정에 남의 조건이 차 있으면 둘 중
       하나는 거짓말입니다. */
    seed: 'empty',
  }
}
