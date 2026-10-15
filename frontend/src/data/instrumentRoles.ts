import {
  anyDomesticOptionCode,
  domesticOptionSide,
  defaultContractCode,
  resolve,
} from './instruments'
import type { ProductKind } from '../lib/types'

/* 저장된 줄이 가리키는 종목 — **코드가 아니라 역할로** 붙잡습니다.
 *
 * 종목 코드는 마스터 판본마다 바뀝니다(9월물이 만기를 넘기면 어제의 코드가
 * 사라집니다). 적어 둔 코드는 언젠가 반드시 아무것도 안 가리키게 되고, 그 줄은
 * 눌러도 열 것이 없어집니다. 그래서 줄은 역할만 들고 다니고 **코드와 이름은
 * 그때그때 색인이 답합니다.**
 */

/** 줄이 붙잡는 역할. 코드가 아니라 「무엇의 자리인가」입니다. */
export type Role =
  | 'kospiFutures'
  | 'kospiCall'
  | 'usdFutures'
  | 'kosdaqFutures'
  | 'jpyFutures'
  | 'esFutures'
  | 'wtiFutures'
  | 'goldFutures'

/** 역할 하나가 가리키는 **품목**. 서버의 `ROLE_INSTRUMENTS` 와 같은 표입니다 —
 *  둘이 갈리면 같은 역할이 화면에서는 코스피, 서버에서는 코스닥이 됩니다.
 *
 *  **새 전략의 기본값을 제안할 때만 씁니다.** 담긴 줄은 품목을 직접 들고
 *  다니고, 옛 줄은 서버가 읽을 때 채워 줍니다. */
const ROLE_INSTRUMENTS: Record<Role, { productCode: string; productKind: ProductKind }> = {
  kospiFutures: { productCode: 'KOSPI', productKind: 'futures' },
  kospiCall: { productCode: 'KOSPI', productKind: 'option' },
  usdFutures: { productCode: 'USD', productKind: 'futures' },
  kosdaqFutures: { productCode: 'KOSDAQ150', productKind: 'futures' },
  jpyFutures: { productCode: 'JPY', productKind: 'futures' },
  esFutures: { productCode: 'ES', productKind: 'futures' },
  wtiFutures: { productCode: 'CL', productKind: 'futures' },
  goldFutures: { productCode: 'GC', productKind: 'futures' },
}

/** 그 역할이 가리키는 품목 한 벌. 새 전략을 만들 때 채워 넣는 기본값입니다. */
export function instrumentOfRole(role: Role): { productCode: string; productKind: ProductKind } {
  return { ...ROLE_INSTRUMENTS[role] }
}

/** 역할이 가리키는 종목 코드. 색인을 아직 못 받았거나 그 품목이 안 실려 있으면
 *  빈 문자열입니다 — **그 줄은 눌러도 열 것이 없어** 부르는 쪽이 누르는 자리에서
 *  빼고 `NO_CODE_REASON`(`lib/labels.ts`)으로 이유를 답니다. */
export function roleCode(role: Role): string {
  switch (role) {
    case 'kospiFutures':
      return defaultContractCode('domestic', 'KOSPI', 'futures') ?? ''
    case 'kospiCall':
      return anyDomesticOptionCode('KOSPI', 'call') ?? ''
    case 'usdFutures':
      return defaultContractCode('domestic', 'USD', 'futures') ?? ''
    case 'kosdaqFutures':
      return defaultContractCode('domestic', 'KOSDAQ150', 'futures') ?? ''
    case 'jpyFutures':
      return defaultContractCode('domestic', 'JPY', 'futures') ?? ''
    case 'esFutures':
      return defaultContractCode('overseas', 'ES', 'futures') ?? ''
    case 'wtiFutures':
      return defaultContractCode('overseas', 'CL', 'futures') ?? ''
    case 'goldFutures':
      return defaultContractCode('overseas', 'GC', 'futures') ?? ''
  }
}

/** 역할이 가리키는 종목의 이름. **색인이 지어 준 이름을 그대로 씁니다** —
 *  줄에 이름을 적어 두면 만기가 넘어갈 때 코드와 이름이 갈립니다.
 *  아직 못 고른 역할은 `fallback` 을 씁니다(자리는 지키고 값만 비는 상태). */
export function roleName(role: Role, fallback: string): string {
  const code = roleCode(role)
  const name = code && resolve(code)?.name
  if (!name) return fallback
  /* 옵션은 색인이 품목 이름까지만 답합니다(행사가는 대응표에 없고 체인을 열면
     따라옵니다). 콜인지 풋인지는 대응표에 있으므로 붙여 둡니다 — 「코스피200」
     한 줄로는 보유한 것이 콜인지 풋인지 읽을 수 없습니다. */
  const side = domesticOptionSide(code)
  if (!side) return name
  return `${name} ${side === 'call' ? '콜' : '풋'}`
}
