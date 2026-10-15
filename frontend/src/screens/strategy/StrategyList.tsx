import { useEffect, useMemo, useRef, useState } from 'react'

import {
  RECORD_KINDS,
  accountOf,
  currencyOf,
  instrumentNameOf,
  useStrategyCurrency,
  recentOf,
  recordShows,
  type StrategyVersion,
} from '../../data/strategyList'
import { instrumentOfRole } from '../../data/instrumentRoles'
import type { Aux } from '../../data/strategyRules'
import {
  NO_CONDITIONS,
  loadRuns,
  useStrategyState,
  type ListStatus,
  failLine,
  type SaveResult,
  type StoreNote,
} from '../../data/strategyStore'
import { Count, Num, currencyCode, currencyDigits, toneOf } from '../../lib/number'
import { RECORD_MODE, versionStatusOf, type RecordKind } from '../../data/strategyList'
import { RunKindBadge } from './runKind'
import { NAMELESS } from './runStats'
import { Modal } from '../../app/Modal'
import type { Environment } from '../../data/environment'

/* 전략 목록 — 필터 / 전략·버전 표 / 선택 상세의 3열.
 *
 * 표에 세우는 것은 전략이 아니라 **버전**입니다. 실행 중인 v3 과 편집 중인
 * v4 초안은 서로 다른 것이고, 한 줄로 합치면 어느 쪽 성과인지 읽을 수 없게
 * 됩니다. 같은 전략임은 둘째 줄부터 들여써서 나타냅니다.
 */

interface Props {
  rows: StrategyVersion[]
  /** 목록을 받아 온 상태. **받는 중과 못 받음은 얼굴이 다릅니다** — 앞은
   *  기다리면 되고 뒤는 아닙니다. 둘 다 「전략이 없다」와 다른 말입니다. */
  status: ListStatus
  /** 못 받았으면 그 까닭 한 줄. */
  failure: string | null
  /** 담아 둔 파일을 서버가 못 읽었거나 안 쓴 까닭. **「목록을 못 받았다」와
   *  다른 말입니다** — 그쪽은 서버에 못 닿은 것이고, 이쪽은 서버가 파일을 못
   *  읽은 것이라 다시 받아도 같습니다. 할 말이 없으면 `null`. */
  storeWhy: StoreNote | null
  onReload: () => void
  /** 고른 버전을 설정까지 베껴 사본으로 저장합니다(`duplicateVersion`). 저장이
   *  막히면 사본 줄은 목록에서 걷히고, 답의 한 줄이 돌아옵니다. */
  onDuplicate: (source: StrategyVersion, copy: StrategyVersion) => Promise<SaveResult>
  /** 그 버전을 보관합니다(`archiveVersion`). 서버가 받은 뒤에만 목록이 「보관」이 되고,
   *  막히면 답의 한 줄이 돌아옵니다. */
  onArchive: (id: string) => Promise<SaveResult>
  /** 새 버전을 **설정 탭의 초안으로** 엽니다. 목록에는 저장이 통과한 뒤에
   *  섭니다 — 목록에만 있고 서버에 없는 줄은 새로고침에 사라집니다. */
  onNewDraft: (row: StrategyVersion) => void
  /** 그 버전의 보조 설정. **상세의 예산·수량·손실 한도는 여기서 읽습니다** —
   *  고치는 자리가 설정이고, 줄에 적힌 값은 그 설정에서 나옵니다. 둘을 따로
   *  보면 상세와 설정이 다른 수를 말합니다. */
  auxOf: (id: string) => Aux
  /** 그 버전을 서버에서 지웁니다. 목록에서 빼는 것도 이쪽이 합니다. */
  onDelete: (id: string) => void
  selectedId: string | null
  onSelect: (id: string | null) => void
  onOpenSettings: () => void
  onOpenCheck: () => void
  onOpenRun: () => void
  /** 상태 칸의 「검증 중 n」·「거래 중 n」을 눌렀을 때 — 그 버전의 실행이 도는 탭을
   *  열고 그 버전의 첫 실행을 고릅니다. */
  onOpenRunsOf: (row: StrategyVersion, tab: 'verify' | 'run') => void
}

const MARKETS = ['전체', '국내', '해외'] as const
const STATUSES = ['전체', '실행 중', '중지', '초안', '보관'] as const
/* 기록 유형의 낱말은 성과분석 화면과 한 벌에서 나옵니다. 목록에서 한 장부로
 * 본 사람이 분석에서 같은 것을 고를 수 있어야 합니다.
 *
 * 이 필터는 줄을 거르면서 **성과 칸이 어느 장부의 값인지도 고릅니다**
 * (`recordShows`·`recentOf`). 한 버전이 앱 시뮬레이션과 모의 계좌 양쪽으로
 * 돌았을 수 있어, 줄의 기록 유형 칸만으로 거르면 다른 장부의 성과를 볼 길이
 * 없습니다. */
const RECORDS = ['전체', ...RECORD_KINDS] as const

/** 필터 다섯의 기본값. 「초기화」가 돌아가는 값이고, 좁은 폭의 「필터 · N」이
 *  세는 기준입니다 — 두 자리가 따로 적으면 초기화한 뒤에도 N 이 남습니다. */
const FILTER_DEFAULTS = {
  query: '',
  market: '전체' as (typeof MARKETS)[number],
  status: '전체' as (typeof STATUSES)[number],
  record: '전체' as (typeof RECORDS)[number],
  runningOnly: false,
}

/** 금액. 통화가 섞이므로 단위를 늘 붙입니다. */
function Money({ value, currency, signed }: { value: number; currency: string; signed?: boolean }) {
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
function Pl({ value, currency }: { value: number; currency: string }) {
  return (
    <span className={toneOf(value) || undefined}>
      <Money value={value} currency={currency} signed />
    </span>
  )
}

/** 아직 값이 없는 칸. 「0」과 갈라야 하므로 빈 칸으로 두지 않습니다. */
function Blank() {
  return <span className="dead">—</span>
}

/** 표의 최근 30일 두 칸(순손익·승률). **목록이 보는 기록 유형의 값**입니다
 *  (`recentOf`). 그 유형의 거래가 없으면 「—」이고 0 과 가릅니다. */
function RecentCells({ row, record }: { row: StrategyVersion; record: (typeof RECORDS)[number] }) {
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
function versionOnly(version: string): string {
  return version.replace(/\s*초안$/, '')
}

/** 설정이 글자로 들고 있는 돈을 상세에 적습니다. 안 정했으면 「—」입니다 —
 *  0 은 정한 값이라 그대로 적습니다(저장은 검증이 막습니다). */
function amount(value: string, currency: string) {
  const text = value.trim()
  if (text === '' || Number.isNaN(Number(text))) return <Blank />
  return <Money value={Number(text)} currency={currency} />
}

/** 설정이 글자로 들고 있는 수를 상세에 적습니다. */
function count(value: string, unit: string) {
  const text = value.trim()
  if (text === '' || Number.isNaN(Number(text))) return <Blank />
  return `${Number(text).toLocaleString('ko-KR')}${unit}`
}

/** 목적격 토씨(을/를) — 끝 글자가 받침으로 끝나면 「을」. 숫자는 읽는 소리로
 *  가립니다(1·3·6·7·8·0 은 받침, 2·4·5·9 는 받침 없음). 「v2를」·「v1을」. */
function objectMark(word: string): string {
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

export function StrategyList({
  rows,
  status: listStatus,
  failure,
  storeWhy,
  onReload,
  onDuplicate,
  onArchive,
  onNewDraft,
  auxOf,
  onDelete,
  selectedId,
  onSelect,
  onOpenSettings,
  onOpenCheck,
  onOpenRun,
  onOpenRunsOf,
}: Props) {
  const [query, setQuery] = useState(FILTER_DEFAULTS.query)
  const [market, setMarket] = useState<(typeof MARKETS)[number]>(FILTER_DEFAULTS.market)
  const [status, setStatus] = useState<(typeof STATUSES)[number]>(FILTER_DEFAULTS.status)
  const [record, setRecord] = useState<(typeof RECORDS)[number]>(FILTER_DEFAULTS.record)
  const [runningOnly, setRunningOnly] = useState(FILTER_DEFAULTS.runningOnly)

  /* 기본값과 다른 필터의 수. 검색어는 공백만이면 거르지 않으므로 기본값으로 봅니다. */
  const filtersOn = [
    query.trim() !== FILTER_DEFAULTS.query,
    market !== FILTER_DEFAULTS.market,
    status !== FILTER_DEFAULTS.status,
    record !== FILTER_DEFAULTS.record,
    runningOnly !== FILTER_DEFAULTS.runningOnly,
  ].filter(Boolean).length

  /* 좁은 폭의 필터 상자. 필터 열이 설 자리가 없으면(`strategy.css` 의 `stg`
     컨테이너 문턱) 목록 머리의 「필터」 단추가 이 상자를 엽니다. 칸은 필터 열과
     같은 것이고(`filterFields`), 값도 위의 다섯 그대로입니다. */
  const [filterOpen, setFilterOpen] = useState(false)
  const filterWrapRef = useRef<HTMLSpanElement>(null)
  const filterButtonRef = useRef<HTMLButtonElement>(null)
  const filterFirstRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  /* 닫으면 초점을 단추로 돌려놓습니다 — 상자 안에 있던 초점이 사라진 칸에
     남으면 키보드로는 어디 있는지 모릅니다. */
  const closeFilter = () => {
    setFilterOpen(false)
    filterButtonRef.current?.focus()
  }

  useEffect(() => {
    if (!filterOpen) return
    filterFirstRef.current?.focus()
    /* 바깥은 **단추와 상자를 함께** 뺀 자리입니다 — 단추를 바깥으로 치면 열린 채
       단추를 누를 때 닫혔다가 곧바로 다시 열립니다. */
    const onDown = (event: MouseEvent) => {
      if (!filterWrapRef.current?.contains(event.target as Node)) closeFilter()
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        closeFilter()
      }
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey, true)
    }
  }, [filterOpen])

  /* 넓어져 필터 열이 다시 서면 단추가 사라지므로 상자도 닫습니다. 문턱 수는
     스타일 한 자리에만 있어, 여기서는 단추가 보이는지로 압니다. 좁아질 때는
     상자를 저절로 열지 않습니다. */
  useEffect(() => {
    const box = listRef.current
    if (!box) return
    const watch = new ResizeObserver(() => {
      const button = filterButtonRef.current
      if (button && getComputedStyle(button).display === 'none') setFilterOpen(false)
    })
    watch.observe(box)
    return () => watch.disconnect()
  }, [])

  /* 실행 목록은 검증·진행과 한 벌입니다. 상태 필터와 「실행 중만 보기」가 이것으로
     셉니다(`versionStatusOf`) — 돌고 있는지는 저장된 상태에 없습니다. */
  const store = useStrategyState()
  const verify = store.verify

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return rows.filter((row) => {
      if (needle && !row.name.toLowerCase().includes(needle)) return false
      if (market !== '전체' && row.market !== (market === '국내' ? 'domestic' : 'overseas')) return false
      if (status !== '전체' && versionStatusOf(row, verify.runs) !== status) return false
      if (!recordShows(row, record)) return false
      if (runningOnly && versionStatusOf(row, verify.runs) !== '실행 중') return false
      return true
    })
  }, [rows, query, market, status, record, runningOnly, verify.runs])

  /* 고른 줄이 걸러져 사라지면 상세가 표에 없는 것을 말하게 됩니다. 화면에
     서 있는 것 중 첫 줄로 옮깁니다 — 목록과 상세가 늘 같은 것을 가리킵니다. */
  useEffect(() => {
    if (shown.length === 0) {
      if (selectedId !== null) onSelect(null)
      return
    }
    if (!shown.some((row) => row.id === selectedId)) onSelect(shown[0].id)
  }, [shown, selectedId, onSelect])

  const selected = shown.find((row) => row.id === selectedId) ?? null
  /* 상세 금액의 통화. 해외인데 담긴 코드가 없으면 품목정보의 통화입니다. */
  const selectedCurrency = useStrategyCurrency(selected)
  /* 상세의 최근 성과도 표와 같은 기록 유형의 값입니다. */
  const recent = selected ? recentOf(selected, record) : null
  /* 상세 「연결 계좌」는 **그 버전의 끝나지 않은 계좌 실행이 붙은 계좌**입니다.
     실행 목록은 검증·진행과 한 벌이라 저장소에서 읽고, 아직 안 받았으면 이 화면이
     열릴 때 한 번 받습니다. */
  /* 어느 버전이든 저장하는 중이면 복제를 잠급니다 — 빨리 두 번 누르면 사본이 둘
     저장되고, 같은 밀리초면 사본의 id 가 겹칩니다. */
  const saving = store.saving !== null
  useEffect(() => {
    if (verify.status !== 'ready') void loadRuns()
    // 열릴 때 한 번만 — 그 뒤로는 허브가 채웁니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  /* 그 버전의 끝나지 않은 실행 수 — 종이(검증 중)와 계좌(거래 중)는 **중지를 뺀**
     수이고, 중지는 따로 셉니다(갈래를 안 가림). 계좌 실행 가운데 실전이 있는지와,
     중지 실행이 계좌 쪽에 있는지도 함께 냅니다. 상태 칸 배지와 삭제 잠금이 이 하나를
     씁니다 — 삭제는 중지까지 포함한 끝나지 않은 실행 전부(`total`)로 막습니다. */
  const liveOf = (versionId: string) => {
    const mine = verify.runs.filter((run) => run.version === versionId && run.state !== 'ended')
    const going = mine.filter((run) => run.state !== 'paused')
    const paused = mine.filter((run) => run.state === 'paused')
    const isAccount = (run: { mode: string }) => run.mode === 'sim' || run.mode === 'real'
    const account = going.filter(isAccount)
    return {
      paper: going.filter((run) => run.mode === 'paper').length,
      account: account.length,
      real: account.some((run) => run.mode === 'real'),
      paused: paused.length,
      pausedAccount: paused.some(isAccount),
      total: mine.length,
    }
  }
  /* 이름이 비어 있는 전략은 **「이름 없는 초안 · 종목」**으로 섭니다 — id 를 이름
     자리에 세우지 않습니다. */
  const nameText = (row: StrategyVersion) => row.name.trim() || `${NAMELESS} · ${instrumentNameOf(row)}`
  const accountEnvironments = (versionId: string): Environment[] => {
    const seen = new Set<Environment>()
    for (const run of verify.runs) {
      if (run.version !== versionId || run.state === 'ended') continue
      if (run.mode !== 'sim' && run.mode !== 'real') continue
      seen.add(run.environment === 'real' || (run.environment == null && run.mode === 'real') ? 'real' : 'paper')
    }
    return (['paper', 'real'] as const).filter((one) => seen.has(one))
  }

  function resetFilters() {
    setQuery(FILTER_DEFAULTS.query)
    setMarket(FILTER_DEFAULTS.market)
    setStatus(FILTER_DEFAULTS.status)
    setRecord(FILTER_DEFAULTS.record)
    setRunningOnly(FILTER_DEFAULTS.runningOnly)
  }

  /* 운영 이력이 있는 버전은 지우지 않고 보관합니다. 지워 버리면 그 버전이
     낸 체결이 어느 규칙에서 나온 것인지 되짚을 수 없습니다. */
  const canDelete = selected !== null && selected.trades === null

  /* 이미 보관한 줄은 다시 보관할 것이 없습니다 — 누르면 아무 일도 안 나는
     단추가 됩니다. */
  const archived = selected !== null && selected.status === '보관'

  /* 지금 막혀 있는 이유. 단추를 누를 수 없게만 두면 왜 안 되는지 알 길이
     없어, 못 누르는 단추와 이유를 늘 함께 답니다.
     **이유는 그 단추의 것만 답니다** — 「보관」이 막힌 이유와 「삭제」가 막힌
     이유는 다른 말입니다. 둘이 함께 설 때는 앞에 단추 이름을 붙여 어느
     단추의 답인지 가립니다. 하나면 이름 없이 그 이유만 섭니다. */
  /* 복제가 막힌 까닭. 다른 단추의 이유와 같은 줄에 섭니다 — 사본 줄은 이미
     걷혔으므로, 이 말이 없으면 누른 일이 없던 일처럼 보입니다. 그 원본을 고르고
     있는 동안만 섭니다. */
  const [copyFail, setCopyFail] = useState<{ id: string; text: string } | null>(null)
  const copyWhy = copyFail !== null && selected !== null && copyFail.id === selected.id ? copyFail.text : null
  /* 보관이 막힌 까닭. 복제와 같은 자리·같은 꼴입니다 — 상태는 서버가 받은 뒤에만
     바뀌므로, 이 말이 없으면 누른 일이 없던 일처럼 보입니다. */
  const [archiveFail, setArchiveFail] = useState<{ id: string; text: string } | null>(null)
  const archiveWhy =
    archiveFail !== null && selected !== null && archiveFail.id === selected.id ? archiveFail.text : null

  const reasons = !selected
    ? [{ id: 'stg-why-pick', name: '', text: '고른 전략이 없습니다' }]
    : [
        ...(copyWhy !== null
          ? [{ id: 'stg-why-copy', name: '', text: failLine('복제하지 못했습니다', copyWhy), fail: true }]
          : []),
        ...(archiveWhy !== null
          ? [{ id: 'stg-why-archive-fail', name: '', text: failLine('보관하지 못했습니다', archiveWhy), fail: true }]
          : []),
        /* 저장하는 동안 잠기는 단추는 복제·보관 둘이라 이름을 달지 않습니다. */
        ...(saving ? [{ id: 'stg-why-saving', name: '', text: '저장하는 중입니다' }] : []),
        ...(archived ? [{ id: 'stg-why-archive', name: '보관', text: '이미 보관한 버전입니다' }] : []),
        ...(canDelete
          ? []
          : [
              {
                id: 'stg-why-delete',
                name: '삭제',
                text: '거래 이력이 있는 버전은 삭제 대신 보관으로 둡니다',
              },
            ]),
      ]
  const named = reasons.length > 1

  /* 새로 만드는 것은 늘 초안입니다. 거래 성과를 가진 채로 태어나는 버전은
     없습니다 — 초안의 성과 칸이 「—」인 것도 그 때문입니다.
     첫 전략은 베낄 것이 없으므로 빈 자리에서 시작합니다. */

  function addNew() {
    /* **목록에 바로 세우지 않습니다.** 새 전략은 한도도 조건도 비어 있어 아직
       저장되지 않는 값이고, 목록에 세워 두면 새로고침 한 번에 사라집니다.
       설정 탭이 초안으로 열리고, 저장이 통과하면 그때 목록에 섭니다. */
    onNewDraft(blankDraft('새 전략', 'v1 초안'))
    resetFilters()
  }

  /* 그린 값(`saving`)은 다음 그림까지 옛 값이라, 한 번에 몰려 온 두 번째 누름은
     이것이 막습니다. */
  const duplicating = useRef(false)

  async function duplicate() {
    if (!selected || saving || duplicating.current) return
    duplicating.current = true
    const copy: StrategyVersion = {
      ...selected,
      id: `draft-${Date.now()}`,
      groupId: `draft-${Date.now()}`,
      name: `${selected.name} 사본`,
      version: 'v1 초안',
      status: '초안',
      pl: null,
      winRate: null,
      trades: null,
      maxDrawdown: null,
    }
    setCopyFail(null)
    try {
      const result = await onDuplicate(selected, copy)
      if (!result.ok) setCopyFail({ id: selected.id, text: result.message })
    } finally {
      duplicating.current = false
    }
  }

  const archiving = useRef(false)

  async function archive() {
    if (!selected || saving || archiving.current) return
    archiving.current = true
    setArchiveFail(null)
    try {
      const result = await onArchive(selected.id)
      if (!result.ok) setArchiveFail({ id: selected.id, text: result.message })
    } finally {
      archiving.current = false
    }
  }

  /* 삭제는 **확인 창을 한 번 지납니다** — 버전 하나를 지우는 것이고 되돌릴 수
     없습니다. 지우는 것은 서버가 합니다 — 목록에서 빼는 것도 그 답을 받은
     뒤입니다. 먼저 빼 두면 서버가 못 지웠을 때 화면에만 없는 전략이 생깁니다. */
  const [deleting, setDeleting] = useState(false)
  function remove() {
    if (!selected || !canDelete) return
    setDeleting(true)
  }
  function confirmRemove() {
    if (!selected || !canDelete || liveOf(selected.id).total > 0) return
    setDeleting(false)
    onDelete(selected.id)
  }

  /* 표에서 같은 전략의 둘째 버전부터 들여씁니다. 걸러진 뒤의 차례로 보므로,
     앞 버전이 필터에 걸려 빠지면 남은 줄이 맨 위 줄이 됩니다. */
  const isSub = (index: number) =>
    index > 0 && shown[index - 1].groupId === shown[index].groupId

  function table() {
    /* 받는 중·못 받음·없음은 **서로 다른 얼굴**입니다. 셋을 한 문장으로 묶으면
       만들어 둔 전략이 안 온 것인지 원래 없는 것인지 화면이 말하지 못합니다. */
    if (listStatus === 'loading') {
      return (
        <div className="notice">
          <p className="notice-title">저장해 둔 전략을 받는 중입니다</p>
        </div>
      )
    }
    if (listStatus === 'failed') {
      return (
        <div className="notice">
          <p className="notice-title">{failure ?? '목록을 받지 못했습니다'}</p>
          <p className="notice-reason">만들어 둔 전략은 서버에 그대로 있습니다</p>
          <button type="button" className="btn btn-quiet notice-action" onClick={onReload}>
            다시 받기
          </button>
        </div>
      )
    }
    if (rows.length === 0) {
      return (
        <div className="notice">
          {/* **「없다」고 단언하지 않습니다.** 담아 둔 파일을 못 읽었거나 안
              쓴 때는 없는 것이 아니라 못 세운 것이라, 이 자리가 그 까닭을
              말합니다. 표 위에 따로 한 줄을 두지 않습니다 — 한 화면이 같은
              사실을 두 번 말하게 됩니다.

              제목에만 경고색을 씁니다. 목록을 못 받은 것은 기다리면 되지만,
              파일을 못 읽은 것은 사람이 손을 써야 끝납니다. 덩어리를 통째로
              물들이면 화면 전체가 위험해 보입니다.

              「다시 받기」는 두지 않습니다 — 다시 받아도 같은 답이 옵니다. */}
          {storeWhy ? (
            <>
              <p className="notice-title is-warn">{storeWhy.title}</p>
              {storeWhy.reason && <p className="notice-reason">{storeWhy.reason}</p>}
            </>
          ) : (
            <>
              <p className="notice-title">저장된 전략이 없습니다</p>
              <p className="notice-reason">새 전략을 만들면 여기에 섭니다</p>
            </>
          )}
          {/* 채운 단추는 한 화면에 하나입니다 — 머리줄의 「새 전략」이 이미
              채운 단추라, 같은 일을 하는 이 단추는 한 급 낮춰 그립니다. */}
          <button type="button" className="btn btn-quiet notice-action" onClick={addNew}>
            새 전략
          </button>
        </div>
      )
    }
    if (shown.length === 0) {
      return (
        <div className="notice">
          <p className="notice-title">조건에 맞는 전략이 없습니다</p>
          <p className="notice-reason">저장된 전략은 {rows.length}개입니다</p>
          <button type="button" className="btn btn-quiet notice-action" onClick={resetFilters}>
            필터 초기화
          </button>
        </div>
      )
    }
    return (
      <div className="table-scroll">
        <table className="data-table rows-stacked stg-table">
          {/* 값 열은 폭을 못 박고 남는 폭은 전략 이름이 먹습니다 — 이름이
              길어져도 성과 칸이 밀리지 않습니다. */}
          <colgroup>
            <col className="stg-col-name" />
            <col className="stg-col-inst" />
            <col className="stg-col-status" />
            <col className="stg-col-pl" />
            <col className="stg-col-win" />
          </colgroup>
          <thead>
            <tr>
              <th scope="col" className="col-text">
                전략 · 버전
              </th>
              <th scope="col" className="col-text">
                시장 · 종목
              </th>
              <th scope="col" className="col-text">
                상태
              </th>
              <th scope="col">최근 순손익</th>
              <th scope="col">승률</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((row, index) => (
              <tr
                key={row.id}
                className="row-click"
                aria-selected={row.id === selectedId}
                onClick={() => onSelect(row.id)}
              >
                <td className={`col-text${isSub(index) ? ' stg-sub' : ''}`} title={nameText(row)}>
                  <span className={`stg-name${row.name.trim() ? '' : ' is-nameless'}`}>{nameText(row)}</span>
                  <span className="stg-version">{versionOnly(row.version)}</span>
                </td>
                <td className="col-text" title={instrumentNameOf(row)}>
                  <span className="stg-inst">{instrumentNameOf(row)}</span>
                  {/* 시장은 미결제 표의 시장 배지와 같은 꼴입니다 — 원·달러 금액이
                      한 표에 섞이므로 줄마다 어느 시장인지가 먼저 읽혀야 합니다. */}
                  <span className="badge stg-market-badge">{row.market === 'domestic' ? '국내' : '해외'}</span>
                </td>
                <td className="col-text stg-status">
                  <span className="badge">{row.status}</span>
                  {/* 그 버전이 지금 돌고 있는지 — 누르면 그 탭에서 그 실행을 엽니다. */}
                  {(() => {
                    const live = liveOf(row.id)
                    return (
                      <>
                        {live.paper > 0 && (
                          <button
                            type="button"
                            className="badge stg-run-badge"
                            onClick={(event) => {
                              event.stopPropagation()
                              onOpenRunsOf(row, 'verify')
                            }}
                          >
                            검증 중 {live.paper}
                          </button>
                        )}
                        {live.account > 0 && (
                          <button
                            type="button"
                            className={`badge stg-run-badge${live.real ? ' run-kind run-kind-real' : ''}`}
                            onClick={(event) => {
                              event.stopPropagation()
                              onOpenRunsOf(row, 'run')
                            }}
                          >
                            거래 중 {live.account}
                          </button>
                        )}
                        {/* 멈춘 실행 — 끝나지 않았지만 새 진입을 내지 않습니다. 정상 흐름이라
                            경고색이 아니라 기본 배지입니다. 누르면 멈춘 실행이 있는 탭을
                            엽니다(계좌 실행이 있으면 진행 탭). */}
                        {live.paused > 0 && (
                          <button
                            type="button"
                            className="badge stg-run-badge"
                            onClick={(event) => {
                              event.stopPropagation()
                              onOpenRunsOf(row, live.pausedAccount ? 'run' : 'verify')
                            }}
                          >
                            중지 {live.paused}
                          </button>
                        )}
                      </>
                    )
                  })()}
                </td>
                <RecentCells row={row} record={record} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  function detail() {
    if (!selected) {
      return (
        <div className="notice">
          <p className="notice-title">고른 전략이 없습니다</p>
          <p className="notice-reason">표에서 한 줄을 고르면 여기에 섭니다</p>
        </div>
      )
    }
    return (
      <>
        {/* **이름과 버전이 먼저 붙습니다.** 둘은 「무엇을 보고 있나」 한 덩이라,
            사이에 단추가 끼면 버전이 단추에 딸린 값처럼 읽힙니다. */}
        <div className="stg-detail-head">
          <h2 className={`stg-detail-name${selected.name.trim() ? '' : ' is-nameless'}`}>{nameText(selected)}</h2>
          <span className="badge">{selected.status}</span>
        </div>
        <p className="stg-detail-version">{versionOnly(selected.version)}</p>
        {/* **이름·종목을 고치는 자리는 설정 하나**입니다. 목록은 고르는
            자리라 여기서도 고쳐지면 잘못 눌러 이름이 바뀝니다 — 어디로
            가야 하는지만 알려 주고 보냅니다. 이름 덩이 아래에 섭니다. */}
        <button type="button" className="btn btn-quiet stg-detail-edit" onClick={onOpenSettings}>
          설정에서 고치기
        </button>
        <p className="stg-detail-summary">{selected.summary}</p>

        <h3 className="stg-detail-title">실행 정보</h3>
        <dl className="stg-sheet">
          <div className="stg-sheet-row">
            <dt>시장 · 종목</dt>
            <dd>{instrumentNameOf(selected)}</dd>
          </div>
          <div className="stg-sheet-row">
            <dt>연결 계좌</dt>
            {/* 그 버전이 **지금 계좌 실행으로 붙어 있는 계좌**입니다(실행이 세운 환경,
                모의 다음 실전). 접속 환경으로 채우지 않습니다 — 모의로만 돈 전략에
                「실전」이 서면 실전 계좌로 거래한 것으로 읽힙니다. 끝나지 않은 계좌
                실행이 없으면 「—」입니다. */}
            <dd>
              {(() => {
                const envs = accountEnvironments(selected.id)
                /* 묶음 사이는 쉼표입니다 — 「모의 · 국내 · 실전 · 국내」는 가운뎃점이 안팎에
                   같아 네 항목으로 읽힙니다. */
                return envs.length === 0 ? '—' : envs.map((one) => accountOf(selected.market, one)).join(', ')
              })()}
            </dd>
          </div>
          {/* 셋 다 **설정에서 고치는 값**이라 설정에서 읽습니다. 아직 안 정했으면
              「—」입니다 — 0 으로 적으면 「한도 없음」으로 읽히는데 그것과 「안
              정했다」는 다른 말입니다. */}
          <div className="stg-sheet-row">
            <dt>증거금 예산</dt>
            <dd>{amount(auxOf(selected.id).marginBudget, selectedCurrency)}</dd>
          </div>
          <div className="stg-sheet-row">
            <dt>하루 손실</dt>
            <dd>{amount(auxOf(selected.id).dailyLoss, selectedCurrency)}</dd>
          </div>
          <div className="stg-sheet-row">
            <dt>주문</dt>
            <dd>{count(auxOf(selected.id).perOrder, '계약')}</dd>
          </div>
        </dl>

        <h3 className="stg-detail-title">
          최근 성과 <span className="stg-detail-range">(최근 30일)</span>
        </h3>
        <dl className="stg-sheet">
          <div className="stg-sheet-row">
            <dt>순손익</dt>
            <dd>
              {recent?.pl == null ? <Blank /> : <Pl value={recent.pl} currency={selectedCurrency} />}
            </dd>
          </div>
          <div className="stg-sheet-row">
            <dt>승률</dt>
            <dd>{recent?.winRate == null ? <Blank /> : `${recent.winRate}% (${recent.trades}건)`}</dd>
          </div>
          <div className="stg-sheet-row">
            <dt>최대 낙폭</dt>
            <dd>
              {recent?.maxDrawdown == null ? (
                <Blank />
              ) : (
                <Money value={recent.maxDrawdown} currency={selectedCurrency} />
              )}
            </dd>
          </div>
        </dl>

        {/* 셋 다 화면을 옮기는 일이라 채운 단추는 쓰지 않습니다 — 채움은
            되돌릴 수 없는 동작의 것이고, 화면 이동은 되돌아오면 그만입니다.
            다만 셋 중 하나만 초록입니다. 고른 전략으로 이어서 할 일은 설정을
            여는 것이고, 검증·진행은 그 다음에 가는 자리입니다. 셋을 다 초록으로
            두면 어디로 가야 할지를 화면이 말하지 않게 됩니다. */}
        <div className="stg-detail-actions">
          <button type="button" className="btn btn-outline" onClick={onOpenSettings}>
            전략 설정 열기
          </button>
          <button type="button" className="btn btn-quiet" onClick={onOpenCheck}>
            검증 화면으로
          </button>
          <button type="button" className="btn btn-quiet" onClick={onOpenRun}>
            진행 화면으로
          </button>
        </div>
      </>
    )
  }

  /* 필터 칸 한 벌. 넓은 폭의 필터 열과 좁은 폭의 필터 상자가 **같은 칸**을
     세웁니다 — 따로 적으면 한쪽에만 칸이 늘거나 차례가 갈립니다. `first` 는
     상자를 열 때 초점을 줄 첫 칸입니다. */
  function filterFields(first?: React.Ref<HTMLInputElement>) {
    return (
      <>
        <label className="stg-field">
          <span className="stg-field-label">전략명 검색</span>
          <input
            ref={first}
            className="control stg-text"
            type="search"
            value={query}
            placeholder="전략명"
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>

        <label className="stg-field">
          <span className="stg-field-label">시장</span>
          <select className="control" value={market} onChange={(e) => setMarket(e.target.value as typeof market)}>
            {MARKETS.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>

        <label className="stg-field">
          <span className="stg-field-label">상태</span>
          <select className="control" value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
            {STATUSES.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>

        <label className="stg-field">
          <span className="stg-field-label">기록 유형</span>
          <select className="control" value={record} onChange={(e) => setRecord(e.target.value as typeof record)}>
            {RECORDS.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>

        <label className="stg-check">
          <input
            type="checkbox"
            checked={runningOnly}
            onChange={(event) => setRunningOnly(event.target.checked)}
          />
          실행 중만 보기
        </label>

        <button type="button" className="btn btn-quiet stg-reset" onClick={resetFilters}>
          초기화
        </button>
      </>
    )
  }

  return (
    <div className="stg-list" ref={listRef}>
      <aside className="card stg-filter" aria-label="필터">
        <h2 className="stg-card-title">필터</h2>
        {filterFields()}
      </aside>

      <section className="card stg-main" aria-label="전략 목록">
        <div className="stg-main-head">
          <div className="stg-main-titles">
            <h2 className="stg-card-title">
              전략 목록 <span className="stg-count">전체 {rows.length}개</span>
            </h2>
            {/* 어느 범위의 성과인지를 표 위에 한 번 적습니다. **기록 유형은
                행마다 다르므로 여기에 못 박지 않습니다** — 한 장부 이름을
                적어 두면 다른 장부에서 센 줄이 그 말 아래 섭니다.
                필터로 한 유형을 골랐을 때만 그 말을 붙입니다 — 그때는 모든
                줄의 성과가 그 유형으로 센 값입니다. */}
            <p className="stg-range">최근 30일{record === '전체' ? '' : ` · ${record}`}</p>
          </div>
          {/* 좁은 폭에서만 서는 필터 단추와 그 상자. 넓은 폭에서는 필터 열이 늘
              보이므로 단추가 없습니다(`strategy.css` 의 `stg` 컨테이너 문턱). */}
          <span className="stg-filter-pop" ref={filterWrapRef}>
            <button
              ref={filterButtonRef}
              type="button"
              className="btn btn-quiet stg-filter-toggle"
              aria-expanded={filterOpen}
              aria-controls="stg-filter-box"
              onClick={() => (filterOpen ? closeFilter() : setFilterOpen(true))}
            >
              {filtersOn > 0 ? `필터 · ${filtersOn}` : '필터'}
            </button>
            {filterOpen && (
              <div id="stg-filter-box" className="stg-filter-box" role="group" aria-label="필터">
                {filterFields(filterFirstRef)}
              </div>
            )}
          </span>
          <div className="stg-main-actions">
            <button type="button" className="btn btn-primary" onClick={addNew}>
              새 전략
            </button>
            {/* 고른 줄에 하는 일이라 고른 것이 없으면 할 일이 없습니다.
                누르게 두고 아무 일도 안 하면 눌린 것인지조차 알 수 없습니다. */}
            <button
              type="button"
              className="btn btn-quiet"
              aria-disabled={!selected || saving}
              aria-describedby={!selected ? 'stg-why-pick' : saving ? 'stg-why-saving' : undefined}
              onClick={() => !saving && void duplicate()}
            >
              복제
            </button>
            <button
              type="button"
              className="btn btn-quiet"
              aria-disabled={!selected || archived || saving}
              aria-describedby={
                !selected ? 'stg-why-pick' : archived ? 'stg-why-archive' : saving ? 'stg-why-saving' : undefined
              }
              onClick={() => !archived && !saving && void archive()}
            >
              보관
            </button>
            <button
              type="button"
              className="btn btn-quiet"
              aria-disabled={!canDelete}
              aria-describedby={!selected ? 'stg-why-pick' : canDelete ? undefined : 'stg-why-delete'}
              onClick={remove}
            >
              삭제
            </button>
          </div>
        </div>
        {/* 이유가 없을 때도 자리를 비워 둡니다. 줄이 생겼다 없어지면 고르는
            줄을 바꿀 때마다 표가 한 줄만큼 오르내려, 눈이 보던 행을 놓칩니다. */}
        {deleting && selected && (() => {
          const live = liveOf(selected.id)
          const last = rows.filter((one) => one.groupId === selected.groupId).length === 1
          return (
            <Modal
              label="전략 삭제"
              onClose={() => setDeleting(false)}
              head={<span className="modal-title">전략 삭제</span>}
              /* 답을 받아야 하는 창이라 바깥을 눌러도 안 닫힙니다. Esc 는 그만두기입니다. */
              dismissable={false}
              closable={false}
            >
              <p className="stg-delete-lead">
                {nameText(selected)} {versionOnly(selected.version)}
                {objectMark(versionOnly(selected.version))} 지웁니다
              </p>
              <dl className="run-confirm">
                <div className="run-confirm-row">
                  <dt>거래 기록</dt>
                  <dd>{(selected.trades ?? 0).toLocaleString('ko-KR')}건</dd>
                </div>
              </dl>
              {/* 지우는 것은 그 버전과 설정뿐이고 거래 기록 파일은 서버가 건드리지
                  않습니다. 그 전략의 마지막 버전이면 목록에서 전략이 사라지는 것도 먼저
                  말합니다. */}
              {last && <p className="stg-delete-note">마지막 버전이라 전략이 목록에서 사라집니다</p>}
              <p className="stg-delete-note">기록은 분석에 남습니다</p>
              {live.total > 0 && (
                <p className="stg-delete-warn">끝나지 않은 실행 {live.total}개가 있어 지울 수 없습니다 — 먼저 종료하세요</p>
              )}
              <div className="run-confirm-acts">
                <button type="button" className="btn btn-quiet" onClick={() => setDeleting(false)}>
                  그만두기
                </button>
                <button
                  type="button"
                  className="btn btn-heavy"
                  aria-disabled={live.total > 0}
                  onClick={confirmRemove}
                >
                  삭제
                </button>
              </div>
            </Modal>
          )
        })()}
        <p className="stg-why">
          {reasons.map((reason, index) => (
            /* 방금 누른 일이 서버에 막힌 글만 오류색입니다 — 나머지는 「지금 못 누르는
               까닭」이라 흐린 글자입니다. */
            <span key={reason.id} id={reason.id} className={'fail' in reason && reason.fail ? 'stg-why-fail' : undefined}>
              {index > 0 && <span aria-hidden="true"> · </span>}
              {named && reason.name ? `${reason.name} — ` : ''}
              {reason.text}
            </span>
          ))}
        </p>

        {/* 담아 둔 파일을 못 읽었는데 **줄이 일부라도 서 있으면** 표 바로 위에
            한 줄로 말합니다. 목록이 통째로 비면 표 자리의 블록이 대신 말하므로
            이 줄은 서지 않습니다 — 값이 선 자리에 블록을 세우면 서 있는 줄을
            가리고, 빈 자리에 줄과 블록을 함께 세우면 같은 말을 두 번 합니다.
            빈 자리에서만 참인 이유(「목록이 비어 있어도」)는 이 줄에 싣지
            않습니다. 둘을 마침표로 잇는 것은 이유 안에 이미 줄표가 있을 수
            있어서입니다. */}
        {storeWhy && rows.length > 0 && (
          <p className="stg-store-why">
            {storeWhy.reason && !storeWhy.emptyOnly
              ? `${storeWhy.title}. ${storeWhy.reason}`
              : storeWhy.title}
          </p>
        )}

        {table()}
      </section>

      <aside className="card stg-detail" aria-label="선택 상세">
        {detail()}
      </aside>
    </div>
  )
}
