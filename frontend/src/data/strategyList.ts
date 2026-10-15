/* 저장된 전략 한 줄의 모양.
 *
 * **여기 있는 것은 신원과 설정이고, 성과는 없습니다.** 성과 넷(순손익·승률·
 * 거래수·최대낙폭)은 줄에 적어 두지 않고 분석 자료에서 옵니다 — 적어 두면
 * 같은 이름 아래 다른 수가 서고, 어느 쪽이 맞는지 화면이 말할 수 없습니다.
 * 저장소에 보낼 때도 그 넷은 빼고 보냅니다(`data/strategyStore.ts`).
 *
 * 종목 이름은 적어 두지 않고 종목 마스터가 지어 준 이름을 씁니다. 적어 두면
 * 만기가 넘어갈 때 이름과 실제 종목이 갈립니다(`data/instrumentRoles.ts`).
 */
import type { Role } from './instrumentRoles'
import type { ProductKind } from '../lib/types'
import { frontContractOf, productOf, resolve } from './instruments'
import { useOverseasProductInfo } from './productInfo'
import type { Product } from '../lib/types'
import type { DraftSeed, SeedKind } from './strategyRules'
import type { RunMode, VerifyRun } from './strategyRuns'
import type { Environment } from './environment'

/** 전략 버전에 저장되는 상태. 색으로 가르지 않고 글자로 말합니다. 돌고 있는지는
 *  저장하지 않고 실행 목록에서 셉니다(`versionStatusOf`). */
export type StrategyStatus = '초안' | '보관'

/** 목록이 보이고 거르는 상태 — 저장된 상태에 실행 목록에서 센 둘을 더한 것입니다. */
export type VersionStatus = StrategyStatus | '실행 중' | '중지'

/** 그 버전이 지금 어떤지. **끝나지 않은 실행**(검증·계좌 모두)이 있으면 그 실행들이
 *  정합니다 — 전부 중지면 「중지」, 하나라도 중지가 아니면(확인 필요·대사 중 포함)
 *  「실행 중」입니다. 끝나지 않은 실행이 없으면 저장된 상태(초안·보관)입니다. */
export function versionStatusOf(row: Pick<StrategyVersion, 'id' | 'status'>, runs: readonly VerifyRun[]): VersionStatus {
  const mine = runs.filter((run) => run.version === row.id && run.state !== 'ended')
  if (mine.length === 0) return row.status
  return mine.every((run) => run.state === 'paused') ? '중지' : '실행 중'
}

/** 성과를 어느 장부에서 셌는지. 장부가 다른 숫자를 한 칸에 섞지 않습니다.
 *  낱말은 성과분석 화면이 쓰는 것을 그대로 가져옵니다 — 목록에서 한 장부로
 *  걸러 본 사람이 분석에서 같은 것을 찾을 때 이름을 스스로 잇지 않도록. */
export type RecordKind = '모의 계좌 거래' | '앱 시뮬레이션' | '실전 계좌 거래'

export const RECORD_KINDS: RecordKind[] = ['모의 계좌 거래', '앱 시뮬레이션', '실전 계좌 거래']

/** 기록 유형이 가리키는 실행 갈래. 목록의 기록 유형 칸이 갈래 배지로 섭니다. */
export const RECORD_MODE: Record<RecordKind, RunMode> = {
  '앱 시뮬레이션': 'paper',
  '모의 계좌 거래': 'sim',
  '실전 계좌 거래': 'real',
}

export interface StrategyVersion {
  /** 표의 행 하나. 같은 전략의 다른 버전과 구별됩니다. */
  id: string
  /** 같은 전략끼리 묶는 값. 표에서 둘째 버전부터 들여씁니다. */
  groupId: string
  name: string
  /** 「v3」·「v4 초안」처럼 이름 아래 줄에 섭니다. */
  version: string
  market: 'domestic' | 'overseas'
  /** 이 전략이 거래하는 **품목**. 월물이 아니라 품목입니다 — 월물을 담으면
   *  만기가 넘어갈 때 그 전략이 없는 종목을 가리킵니다. */
  productCode: string
  productKind: ProductKind
  /** **특정 월물을 고른 줄에만** 있습니다. 비어 있으면 그때그때 근월입니다 —
   *  그 편이 만기를 넘겨도 살아 있습니다. */
  contractCode?: string
  /** 옛 줄이 종목을 붙잡던 방법. **새 줄은 안 씁니다** — 서버가 읽을 때 품목
   *  칸으로 옮겨 주므로 화면은 받은 그대로 씁니다. 새 전략의 기본값을 제안할
   *  때만 이 표를 봅니다(`data/instrumentRoles.ts`). */
  role: Role
  /** 마스터를 아직 못 받았을 때 종목 칸에 설 이름. */
  instrumentFallback: string
  status: StrategyStatus
  record: RecordKind
  /** 서버가 싣는 꼬리표. 지금 화면은 쓰지 않고, 저장된 값을 그대로 둡니다. */
  tags: string[]
  /** 최근 30일 순손익. **저장소가 주지 않습니다** — 분석 자료가 답하고, 그
   *  전략의 기록이 아직 없으면 `null` 이라 화면이 그 칸을 비웁니다. */
  pl: number | null
  currency: string
  winRate: number | null
  trades: number | null
  maxDrawdown: number | null
  /** 같은 최근 30일 성과를 기록 유형마다 갈라 센 것. 위의 넷은 이 버전 자신의
   *  기록 유형 쪽 값입니다. 그 유형의 거래가 없으면 `null` 입니다(0 과 다름). */
  performance?: { paper: RecentPerf | null; sim: RecentPerf | null; real?: RecentPerf | null }
  /** 상세의 지표 요약 한 줄. */
  summary: string
  account: string
  marginBudget: number
  /** 하루 손실 한도. 그 전략의 통화입니다. */
  dailyLoss: number
  orderQty: number
  /** 설정 화면이 이 버전을 처음 열 때 세울 조건의 갈래. 저장된 조건이 있으면
   *  그것이 먼저이고, 이 칸은 새로 만든 버전의 출발점입니다. */
  seed: SeedKind
}

/** 한 기록 유형의 최근 30일 성과 넷. 거래는 있는데 순손익을 셀 수 없으면(수수료를
 *  모름 등) 서버가 손익·승률·낙폭을 비워(`null`) 보내고 거래 수만 채웁니다. */
export interface RecentPerf {
  pl: number | null
  winRate: number | null
  trades: number
  maxDrawdown: number | null
}

/** 목록이 보는 기록 유형에 맞춘 성과 넷과 그 유형 글자.
 *
 *  - 「전체」: 그 버전 자신의 기록 유형 값(줄의 넷)입니다. 두 유형을 더하지
 *    않습니다 — 한 버전은 한 유형으로 돌고, 더한 수는 어느 장부의 것도 아닙니다.
 *  - 앱 시뮬레이션·모의 계좌 거래·실전 계좌 거래: 그 유형으로 센 값 하나만
 *    입니다. 서버가 그 유형의 값을 안 주면 비웁니다. */
export function recentOf(
  row: StrategyVersion,
  record: RecordKind | '전체',
): { pl: number | null; winRate: number | null; trades: number | null; maxDrawdown: number | null; record: string } {
  if (record === '전체') {
    return { pl: row.pl, winRate: row.winRate, trades: row.trades, maxDrawdown: row.maxDrawdown, record: row.record }
  }
  const split = row.performance?.[RECORD_MODE[record]]
  return split
    ? { ...split, record }
    : { pl: null, winRate: null, trades: null, maxDrawdown: null, record }
}

/** 목록의 기록 유형 필터에 그 줄이 서는지.
 *
 *  - 「전체」: 모든 줄입니다.
 *  - 그 밖: 그 유형의 기록이 있거나, 버전의 기록 유형이 그것인 줄입니다. 여러
 *    유형으로 돈 버전은 그 필터마다 섭니다. */
export function recordShows(row: StrategyVersion, record: RecordKind | '전체'): boolean {
  if (record === '전체' || row.record === record) return true
  return row.performance?.[RECORD_MODE[record]] != null
}

/** 목록 행이 설정 초안에 넘기는 것. */
export function draftSeedOf(row: StrategyVersion): DraftSeed {
  return {
    kind: row.seed,
    market: row.market,
    marginBudget: row.marginBudget,
    dailyLoss: row.dailyLoss,
    orderQty: row.orderQty,
  }
}

/** 그 줄이 가리키는 **품목**. 색인에 없으면 `null` 입니다 — 마스터를 아직 못
 *  받았거나 그 품목이 상장 폐지된 것이라, 둘 다 「지금은 못 찾는다」입니다. */
export function productOfVersion(row: InstrumentFields): Product | null {
  return productOf(row.market, row.productCode)
}

/** 그 줄이 지금 거래할 **종목 코드**. 월물을 골라 둔 줄은 그 월물이고, 아니면
 *  「근월 자동」이 푸는 월물입니다(`frontContractOf` — 만기 당일은 건너뜁니다).
 *
 *  **푸는 자리는 화면입니다.** 서버에는 품목만 담기고, 실행을 세울 때 화면이
 *  이 코드를 보냅니다 — 서버가 또 풀면 색인 판본이 둘이 됩니다. */
export function codeOfVersion(row: InstrumentFields): string {
  if (row.contractCode) return row.contractCode
  const product = productOfVersion(row)
  return product ? (frontContractOf(product, row.productKind)?.code ?? '') : ''
}

/** 그 시장의 계좌 이름. 전략이 붙는 계좌는 **접속 환경과 시장이 정합니다** —
 *  계좌 실행은 접속 환경의 계좌(모의·실전)로 서고, 해외 전략에 「· 국내」가 서면
 *  어느 계좌의 한도·기록인지 거꾸로 읽힙니다. 환경을 안 주면 모의입니다(담아
 *  두는 값). */
export function accountOf(market: 'domestic' | 'overseas', environment: Environment = 'paper'): string {
  return `${environment === 'real' ? '실전' : '모의'} · ${market === 'overseas' ? '해외' : '국내'}`
}

/** 그 시장에서 전략이 쓰는 통화. 국내는 원이고, 해외는 **담긴 통화 코드**(세
 *  글자 대문자)입니다. 해외에 코드가 없으면 빈 글자(모름)입니다 — 원을 지어
 *  두면 달러 금액이 원으로 읽힙니다. 해외 품목의 통화는 품목정보(`currency`)가
 *  답하므로, 모를 때는 부르는 쪽이 그 값으로 채웁니다. */
export function currencyOf(market: string, stored: string | null | undefined): string {
  if (market !== 'overseas') return '원'
  return stored && /^[A-Z]{3}$/.test(stored) ? stored : ''
}

/** 담긴 줄의 계좌·통화를 **그 시장에 맞춰 읽습니다.** 품목을 해외로 바꿔도 계좌·
 *  통화가 국내 것으로 남은 옛 줄이 있어, 받을 때 여기서 한 번 바로잡습니다 —
 *  저장소 파일은 안 고치고, 다음에 그 버전을 저장할 때 바로잡힌 값이 담깁니다.
 *  역할(`role`)은 옛 줄 호환 칸이라 건드리지 않습니다. */
export function withMarketMeta<T extends Pick<StrategyVersion, 'market' | 'account' | 'currency'>>(row: T): T {
  return { ...row, account: accountOf(row.market), currency: currencyOf(row.market, row.currency) }
}

/** 전략이 쓰는 통화를 읽고, 해외인데 담긴 코드가 없으면 **품목정보의 통화**로
 *  채웁니다(그 전략이 지금 거래할 종목으로 묻습니다). 그래도 모르면 빈 글자입니다. */
export function useStrategyCurrency(
  row: (InstrumentFields & Pick<StrategyVersion, 'currency'>) | null,
): string {
  const stored = row ? currencyOf(row.market, row.currency) : ''
  const code = row && row.market === 'overseas' && stored === '' ? codeOfVersion(row) : ''
  const info = useOverseasProductInfo(code)
  if (!row) return ''
  return stored || currencyOf('overseas', info.row?.currency)
}

/** 종목 칸을 읽는 데 필요한 것만. 줄 전체를 받으면 「새 전략」 씨앗처럼 아직
 *  줄이 아닌 값에는 못 씁니다. */
export type InstrumentFields = Pick<
  StrategyVersion,
  'market' | 'productCode' | 'productKind' | 'contractCode'
>

/** 표의 종목 칸에 설 이름. **마스터가 지어 준 이름을 그대로** 씁니다.
 *
 *  월물을 골라 둔 줄은 그 월물의 이름이고, 「근월 자동」인 줄은 품목 이름에
 *  그 말을 붙입니다 — 어느 월물로 도는지는 그때그때 달라지므로 이름에 못
 *  박으면 다음 달에 거짓이 됩니다. 색인에 없으면 담아 둔 이름입니다. */
export function instrumentNameOf(row: StrategyVersion): string {
  const product = productOfVersion(row)
  if (!product) return row.instrumentFallback
  if (row.contractCode) return resolve(row.contractCode)?.name ?? row.instrumentFallback
  return `${product.name} · 근월 자동`
}
