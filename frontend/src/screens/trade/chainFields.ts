import type { ChainLeg } from '../../lib/types'

/* 옵션 체인의 열 정의와 열 묶음(프리셋).
 *
 * 열은 한글 이름이 아니라 키로 찾습니다. 명세의 한글 이름에는 서로 다른
 * 값이 같은 이름을 쓰는 자리가 있어, 이름으로 찾으면 한 값이 두 번 들어가고
 * 다른 값이 빠집니다.
 *
 * 열을 하나씩 켜고 끄는 방식은 쓰지 않습니다. 열이 열다섯이면 조합이
 * 삼만 가지가 넘고, 사용자가 망가진 조합으로 두고 나가면 다음에 열 때도
 * 망가진 화면입니다. 프리셋은 어느 것을 골라도 온전합니다.
 */

export interface FieldDef {
  label: string
  /** 이 열이 값을 잘리지 않고 담는 최소 폭(px). 실제로 재서 넣은 값입니다. */
  minWidth: number
  /** 소수 자릿수. 'price' 는 그 종목의 자릿수를 따릅니다. */
  decimals: number | 'price'
  /** 정수만 쓰는 값 */
  count?: boolean
  signed?: boolean
  /** 부호에 따라 색이 갈립니다 */
  toned?: boolean
  /** 매수·매도처럼 방향이 고정된 값 */
  fixedTone?: 'up' | 'down'
  suffix?: string
  /** 숫자 뒤에 비례 배경 바를 깔고, 넓은 화면에서 남는 폭을 이 열이 먹습니다 */
  bar?: boolean
  /** 그 줄의 값. **없는 칸은 `null`** 이고 화면은 그 자리를 비웁니다. */
  value: (leg: ChainLeg) => number | null
}

export const CHAIN_FIELDS = {
  last: { label: '현재가', minWidth: 60, decimals: 'price', value: (l) => l.last },
  prevClose: { label: '전일종가', minWidth: 68, decimals: 'price', value: (l) => l.prevClose },
  change: { label: '등락', minWidth: 60, decimals: 'price', signed: true, toned: true, value: (l) => l.change },
  volume: { label: '거래량', minWidth: 64, decimals: 0, count: true, bar: true, value: (l) => l.volume },
  oi: { label: '미결제', minWidth: 64, decimals: 0, count: true, bar: true, value: (l) => l.openInterest },
  // 미결제 증감은 방향 값이 아니므로 부호만 쓰고 색은 쓰지 않습니다.
  oiChange: { label: '미결제대비', minWidth: 78, decimals: 0, count: true, signed: true, value: (l) => l.oiChange },
  delta: { label: '델타', minWidth: 70, decimals: 4, signed: true, value: (l) => l.delta },
  gamma: { label: '감마', minWidth: 60, decimals: 4, value: (l) => l.gamma },
  theta: { label: '세타', minWidth: 70, decimals: 4, signed: true, value: (l) => l.theta },
  vega: { label: '베가', minWidth: 60, decimals: 4, value: (l) => l.vega },
  iv: { label: '변동성', minWidth: 60, decimals: 2, suffix: '%', value: (l) => l.iv },
  theo: { label: '이론가', minWidth: 60, decimals: 'price', value: (l) => l.theo },
  theoDiff: { label: '이론가대비', minWidth: 78, decimals: 'price', signed: true, value: (l) => l.theoDiff },
  disparity: { label: '괴리율', minWidth: 64, decimals: 2, signed: true, suffix: '%', value: (l) => l.disparity },
  bid: { label: '매수가', minWidth: 60, decimals: 'price', fixedTone: 'up', value: (l) => l.bid },
  ask: { label: '매도가', minWidth: 60, decimals: 'price', fixedTone: 'down', value: (l) => l.ask },
  // 수량에는 색을 쓰지 않습니다. 방향은 가격이 나르고, 어느 쪽인지는 열 이름이 말합니다.
  bidQty: { label: '매수수량', minWidth: 70, decimals: 0, count: true, value: (l) => l.bidQty },
  askQty: { label: '매도수량', minWidth: 70, decimals: 0, count: true, value: (l) => l.askQty },
} satisfies Record<string, FieldDef>

export type FieldKey = keyof typeof CHAIN_FIELDS

export interface Preset {
  id: string
  label: string
  /** 행사가 열에 가까운 쪽부터 적습니다. 콜 쪽은 이 순서를 뒤집어 그립니다. */
  fields: FieldKey[]
}

/* 국내 — 값이 가장 많습니다.
 * 변동성은 넷 중 둘에 넣었습니다. 옵션에서 가장 많이 읽는 값이라
 * 「그릭스」에만 가두지 않았습니다.
 *
 * 국내 「호가」는 가격만 와서 한쪽 2열입니다. 해외 「호가」는 잔량까지 와서
 * 4열입니다 — 이름이 같고 열 수가 다릅니다. */
export const DOMESTIC_PRESETS: Preset[] = [
  { id: 'quote', label: '시세', fields: ['change', 'last', 'oi', 'volume'] },
  { id: 'greeks', label: '그릭스', fields: ['last', 'iv', 'vega', 'theta', 'gamma', 'delta'] },
  { id: 'theo', label: '이론가', fields: ['last', 'iv', 'disparity', 'theoDiff', 'theo'] },
  { id: 'book', label: '호가', fields: ['ask', 'bid'] },
]

/* 해외 — 미결제·이론가·그릭스·변동성이 오지 않습니다. */
export const OVERSEAS_PRESETS: Preset[] = [
  { id: 'quote', label: '시세', fields: ['change', 'last', 'volume'] },
  { id: 'bid', label: '호가', fields: ['askQty', 'ask', 'bid', 'bidQty'] },
]

/* 국내 야간은 **전용 묶음 하나**입니다. 야간 답에는 전일종가·미결제만 값이 있어,
 * 주간 묶음을 그대로 세우면 현재가·등락·거래량 열이 통째로 비어 「못 받음」으로
 * 읽힙니다 — 통째로 비는 열은 만들지 않습니다. 고를 것이 하나라 고르개도 안
 * 섭니다. 야간 체결·호가 실시간이 붙는 날 열과 고르개가 돌아옵니다. */
export const NIGHT_PRESETS: Preset[] = [{ id: 'night', label: '야간', fields: ['prevClose', 'oi'] }]

/** 행사가 열의 최소 폭. 가로로 스크롤해도 이 열은 남습니다. 네 자리 행사가
 *  (`1102.5`)까지 잘리지 않는 폭입니다 — 서버가 주는 행사가는 품목마다 자릿수가
 *  달라 세 자리에 맞춘 폭이면 끝이 잘립니다. */
export const STRIKE_MIN_WIDTH = 68

/* 창이 넓어지면 미결제·거래량 열만 늘어나고 나머지는 고정입니다.
 *
 * 같은 행사가에서 실제로 비교하는 것은 현재가와 등락이라, 그 넷과 행사가를
 * 붙여 두어야 눈이 정렬하는 자리가 안 움직입니다. 남는 폭은 미결제·거래량의
 * 배경 막대가 먹습니다 — 넓힐수록 분포가 잘 보이므로 빈 배경이 아니라
 * 정보가 됩니다. 숫자는 오른쪽 정렬이고 막대만 왼쪽으로 자랍니다.
 *
 * 막대 열이 이 폭을 넘으면 멈추고 그 위는 표 바깥 여백입니다. */
export const BAR_COLUMN_MAX = 180

/* 표의 최소·최대 폭은 `OptionChain` 이 답을 보고 셉니다 — 값 열의 폭이 답에서 가장 긴
 * 값으로 정해지기 때문입니다. */
