/** 홈 관심종목 — 칸 여섯과 그 칸에 담기는 것의 신원.
 *
 *  **담는 것은 종목 코드뿐입니다.** 이름·자릿수는 마스터가 정하는 값이라 담아
 *  두면 상장이 바뀔 때 옛 이름이 새 이름인 척합니다. 열 때마다 색인에서 풉니다.
 *
 *  **담을 수 있는 것은 실제로 조회할 수 있는 계약**입니다. 품목명이나 행사가를
 *  아직 안 고른 옵션 자리는 시세를 부를 코드가 아니라서 담지 않습니다 — 담으면
 *  칸은 서는데 값은 영영 안 옵니다.
 */
import {
  defaultContractCode,
  needsLeg,
  resolve,
  spreadShortName,
  type Market,
} from './instruments'

/* 관심종목 여섯 칸.
 *
 * 칸 수가 상한입니다 — 「몇 개까지」를 따로 정하지 않고 자리가 정합니다.
 * 첫 칸이 큰 타일이고 나머지 다섯이 목록입니다. */
export const WATCH_SLOTS = 6

/** 관심종목 한 칸의 **신원**입니다. 값(현재가·전일대비)은 여기 없습니다 —
 *  조회가 채우고 실시간이 덮습니다(`data/quotes.ts`). 신원과 값을 한
 *  덩어리로 두면 값이 없을 때 칸도 함께 사라져, 「무엇을 담아 뒀는지」까지
 *  잃습니다. */
export interface Tile {
  code: string
  name: string
  market: Market
  /** 소수 자릿수. 값을 그리는 자리가 씁니다 — **색인이 정합니다.** 품목 안에서
   *  종목마다 갈려 색인이 품목 줄에 안 실은 경우만 둘째 자리로 둡니다(주문
   *  화면과 같은 값). */
  decimals: number
}

/** 담긴 코드를 칸으로 풉니다. **색인에 없는 코드는 `null`** — 색인을 아직 못
 *  받았을 때도 같으니, 둘을 갈라야 하는 자리는 마스터 상태를 함께 봅니다. */
export function tileOf(code: string): Tile | null {
  const item = resolve(code)
  if (!item || !item.contract) return null
  return {
    code,
    /* 스프레드 이름은 **타일 폭에 맞춘 짧은 꼴**입니다 — 두 만기를 다 적으면
       한 줄에 안 들어가 이름이 잘리는데, 하필 잘리는 자리가 만기입니다. */
    name:
      item.contract.kind === 'spread' && item.contract.legs
        ? spreadShortName(item.product.name, item.contract.legs)
        : item.name,
    market: item.market,
    decimals: item.product.decimals ?? 2,
  }
}

/** 이 코드를 홈에 담을 수 있는지. 없으면 그 까닭을 답합니다.
 *
 *  **담을 수 있는 것은 시세를 부를 수 있는 계약뿐입니다** — 만기가 정해진 선물,
 *  행사가까지 정해진 옵션, 다리 만기가 실려 온 스프레드. 행사가를 아직 안 고른
 *  옵션 자리(`needsLeg`)는 부를 코드가 아니라서 못 담습니다. */
export function watchable(code: string): { ok: true } | { ok: false; reason: string } {
  const item = resolve(code)
  if (!item || !item.contract) return { ok: false, reason: '종목 목록에 없음' }
  /* 까닭은 줄 오른쪽 끝에 서는 한 마디라 짧게 — **무엇이 모자란지만** 말합니다.
     「담을 수 없음」이라 적지 않습니다: 행사가까지 정해진 옵션 코드는 코드로
     담기므로 거짓이고, 「주문 화면에서 고르세요」는 거기서 골라도 여기 담기지
     않으니 못 지킬 약속입니다. */
  /* 스프레드는 시세가 옵니다. 못 담는 것은 **타일에 적을 이름을 못 지을 때**뿐
     입니다 — 타일 이름이 두 다리의 만기라, 그 두 칸이 안 오면 지을 재료가
     없습니다. 까닭은 모자란 것을 그대로 적습니다. */
  if (item.kind === 'spread' && !item.contract.legs) {
    return { ok: false, reason: '다리 만기가 없어 타일 이름을 못 짓습니다' }
  }
  if (needsLeg(code)) return { ok: false, reason: '행사가가 필요합니다' }
  return { ok: true }
}

/** 처음 채워 두는 다섯과 빈 칸 하나. 사용자가 빼고 넣으면 그 목록이 남습니다.
 *
 *  **코드를 적어 두지 않고 품목으로 잡습니다** — 종목 코드는 마스터 판본마다 바뀌어서
 *  적어 둔 값은 만기가 지나면 아무것도 안 가리킵니다. 품목의 어느 월물을 쓸지는
 *  색인이 답합니다(주력이 있으면 주력, 없으면 가장 가까운 만기). 여섯째를 비워
 *  두는 것은 「여기에 담을 수 있다」를 빈 칸 하나로 보여 주기 위해서입니다.
 *  품목이 색인에 없으면 그 칸만 빕니다.
 *
 *  **색인이 도착한 뒤에 불러야 값이 있습니다** — 그전에는 빈 목록입니다. */
const DEFAULT_PRODUCTS: { market: Market; product: string }[] = [
  { market: 'domestic', product: 'USD' },
  { market: 'overseas', product: 'GC' },
  { market: 'domestic', product: 'KOSPI' },
  { market: 'domestic', product: 'KOSDAQ150' },
  { market: 'domestic', product: 'JPY' },
]

export function defaultWatch(): string[] {
  return DEFAULT_PRODUCTS.map(
    (item) => defaultContractCode(item.market, item.product, 'futures') ?? '',
  )
    .filter((code) => code !== '' && tileOf(code) !== null)
    .slice(0, WATCH_SLOTS)
}
