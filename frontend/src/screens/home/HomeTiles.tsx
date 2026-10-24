import { Num, fracWidth } from '../../lib/number'
import { Spark } from '../../lib/Spark'
import { kstClock, kstMinutes } from '../../lib/kst'
import { useBars, usePrice } from '../../data/quotes'
import { useSession } from '../../data/session'
import type { Tile } from '../../data/homeWatch'

/* 기준 종목 하나만 큰 타일입니다. 스파크라인이 길수록·높을수록 형태가
 * 읽히므로, 홈에서 세로로 늘어나는 것은 이 하나뿐입니다. */
/** 여러 시각 중 **가장 최근**. 둘 다 오늘 안에서 이미 지난 시각이라는 것을
 *  써서 「지금으로부터 얼마나 지났나」로 견줍니다 — 국내 야간장은 자정을 넘겨
 *  이어지므로 글자로 견주면 00:10 이 23:55 보다 최근이라고 나옵니다. */
export function latest(times: string[]): string {
  if (times.length === 0) return ''
  /* 줄의 시각은 한국시간이라 지금도 한국시간으로 셉니다. */
  const nowMinutes = kstMinutes(Date.now())
  const ago = (text: string) => {
    const [hour, minute] = text.split(':').map(Number)
    return (nowMinutes - (hour * 60 + minute) + 1440) % 1440
  }
  return times.reduce((best, one) => (ago(one) < ago(best) ? one : best))
}

/* 타일 한 칸이 지금 무엇을 보일 수 있는가.
 *
 * **다섯 갈래를 가릅니다.** 값이 없는 까닭마다 사용자가 할 일이 다릅니다 —
 * 받는 중이면 기다리고, 못 받았으면 다시 받고, 거절이면 눌러도 같은 답이며,
 * 「받았는데 값이 아직 없다」는 그 종목에 오늘 거래가 없다는 뜻이고,
 * **아직 안 물어본 자리**는 앱이 그 시장을 조회하지 않는 자리입니다.
 * 다섯을 한 얼굴로 두면 사용자가 될 때까지 새로고침을 누릅니다.
 *
 * 값 갈래를 가르는 칸은 **현재가 하나**입니다. 전일대비·등락률은 시세가 있어도
 * 안 올 수 있는 칸이라 그때는 그 칸만 「—」로 섭니다 — 셋을 다 요구하면 멀쩡히
 * 그릴 수 있는 타일이 「거래 없음」으로 섭니다. */
type TileFace =
  | { kind: 'values'; last: number; change: number | null; changePct: number | null }
  | { kind: 'loading' }
  | { kind: 'failed'; retry: boolean }
  | { kind: 'empty' }

function useTileFace(tile: Tile): TileFace {
  /* 두 시장 다 부릅니다 — 어느 길로 갈지는 시세 저장소가 종목으로 정합니다
     (`data/quotes.ts`). 국내는 세션도 같이 묻습니다 — 야간이면 현재가가 야간
     조회로 나가야 하고, 그 판단은 세션 답이 합니다. 해외는 길이 하나라 안 묻습니다. */
  useSession('domestic', tile.market === 'domestic' ? tile.code : '')
  const entry = usePrice(tile.code)

  /* **값이 있으면 값이 먼저입니다.** 다시 받다 실패해도 앞서 받은 값은 틀린 값이
     아니라 낡은 값이고, 낡았다는 사실은 카드 위 한 줄이 말합니다. 값을 「못 받음」
     으로 갈아 끼우면 새로고침 한 번에 멀쩡한 값이 사라집니다. */
  const price = entry.price
  if (price && price.last !== null) {
    return { kind: 'values', last: price.last, change: price.change, changePct: price.changePct }
  }
  if (entry.failure) return { kind: 'failed', retry: entry.failure === 'retry' }
  return entry.status === 'ready' ? { kind: 'empty' } : { kind: 'loading' }
}

/** 값이 안 서는 칸에 서는 한 마디. **까닭마다 다릅니다** — 「없음」 하나로
 *  뭉치면 기다릴 자리와 다시 받을 자리가 같은 얼굴이 됩니다. */
function faceWord(face: TileFace): string {
  if (face.kind === 'loading') return '받는 중'
  if (face.kind === 'failed') return face.retry ? '못 받음' : '받지 못했습니다'
  return '거래 없음'
}

export function LeadTile({ tile }: { tile: Tile }) {
  const price = fracWidth(tile.decimals)
  const face = useTileFace(tile)
  /* 곡선은 **큰 타일에만** 있습니다. 작은 줄에서 56×24 곡선이 주는 것은
     오르내림 모양 하나인데, 그것은 바로 옆 숫자와 등락률이 이미 말합니다.
     큰 타일은 원래 더 보여 주는 자리라 값 하나를 더 부를 만합니다. */
  const bars = useBars(face.kind === 'values' ? tile.code : '')

  return (
    <>
      <span className="tile-name">
        {tile.name}
        {/* 이 누름이 화면을 나간다는 표시입니다. 오른쪽 화살표는 「다른 곳으로」,
            작은 줄의 위쪽 화살표는 「여기 안에서」를 뜻합니다. */}
        <span className="tile-hint" aria-hidden="true">
          주문으로 →
        </span>
      </span>
      {face.kind === 'values' ? (
        <>
          <span className="tile-price" style={price}>
            <Num value={face.last} decimals={tile.decimals} />
          </span>
          {/* 안 온 칸은 빈 채입니다 — 0 으로 적으면 「안 움직였다」가 되고, 「—」는 이
              시장에 원래 없는 값의 말입니다. */}
          <span className="tile-change">
            <span style={price}>
              {face.change !== null && <Num value={face.change} decimals={tile.decimals} signed toned />}
            </span>
            <span style={fracWidth(2, 1)}>
              {face.changePct !== null && (
                <Num value={face.changePct} decimals={2} signed toned suffix="%" />
              )}
            </span>
          </span>
        </>
      ) : (
        /* 값이 없으면 **까닭만** 그 자리에 섭니다. 숫자 자리를 뼈대나 「—」로
           채우지 않습니다 — 뼈대는 「곧 온다」는 말이고, 「—」는 「이 종목엔
           원래 없는 값」이라는 말입니다. */
        <span className="tile-word">{faceWord(face)}</span>
      )}
      {/* 선은 이름·값 아래에 카드 폭을 다 씁니다. 흐름이 형태로 읽히려면 길게
          깔려야 합니다 — 짧게 자르면 같은 자료가 잔물결이 됩니다.
          **값이 없으면 선 자리도 없습니다.** 자리만 잡아 두면 회색 블록이
          「곧 온다」로 읽히는데, 조회가 아직 없는 자리에는 안 옵니다. */}
      {face.kind === 'values' && (
      <Spark
        points={bars ? bars.map((bar) => bar.close) : null}
        loaded={bars !== null}
        stretch
        width={1120}
        height={160}
        /* 기준선은 **전일 종가**입니다 — 이 타일이 적는 현재가와 전일대비에서
           셉니다. 봉의 끝 값으로 짓지 않습니다(오늘 봉이 없거나 늦게 올 수 있고,
           그러면 기준이 어제가 아니게 됩니다). 전일대비가 안 온 종목은 모릅니다. */
        base={
          face.kind === 'values' && face.change !== null && Number.isFinite(face.last - face.change)
            ? face.last - face.change
            : null
        }
        times={bars ? bars.map((bar) => barTime(bar.timestamp)) : undefined}
        decimals={tile.decimals}
      />
      )}
    </>
  )
}

/* 나머지 다섯은 가로 한 줄짜리 목록입니다. 세로로 쌓으면 이름·값·등락이
 * 타일 높이에 안 들어가고, 다섯은 고르기 전에 훑는 대상이라 목록이 맞습니다. */
export function QuoteRow({ tile }: { tile: Tile }) {
  const price = fracWidth(tile.decimals)
  const face = useTileFace(tile)

  return (
    <>
      {/* 목록의 이름은 잘려도 됩니다 — 여럿 중 하나를 찾는 자리라 앞부분이면
          알아봅니다. 다만 전체는 물어볼 수 있어야 합니다. */}
      <span className="quote-name" title={tile.name}>
        {tile.name}
        <span className="quote-hint" aria-hidden="true">
          ↑ 크게 보기
        </span>
      </span>
      {face.kind === 'values' ? (
        <>
          <span className="quote-price" style={price}>
            <Num value={face.last} decimals={tile.decimals} />
          </span>
          <span className="quote-change" style={price}>
            {face.change !== null && <Num value={face.change} decimals={tile.decimals} signed toned />}
          </span>
          {/* 등락률만 알약에 담습니다. 이 목록은 「무엇이 움직였나」를 찾으며
              훑는 곳이라 등락률이 표적이고, 바탕은 표적에만 깝니다.
              알약 폭은 열 폭 전부입니다 — 값에 맞춰 줄이면 「−13.36%」가
              「−0.88%」보다 긴 알약이 되어 길이가 크기를 말하게 됩니다. */}
          <span className={`quote-pct${face.change !== null && face.change > 0 ? ' up' : face.change !== null && face.change < 0 ? ' down' : ''}`}>
            <span style={fracWidth(2, 1)}>
              {face.changePct !== null && (
                <Num value={face.changePct} decimals={2} signed toned suffix="%" />
              )}
            </span>
          </span>
        </>
      ) : (
        /* 값 세 칸을 한 마디가 대신합니다. 칸마다 같은 말을 세우면 한 줄에
           같은 글자가 셋 섭니다. */
        <span className="quote-word">{faceWord(face)}</span>
      )}
    </>
  )
}

/** 봉 하나의 시각을 한국시각 `HH:MM` 으로. 곡선에 마우스를 올렸을 때 값과 함께 뜹니다. */
function barTime(timestamp: number): string {
  return kstClock(timestamp)
}

/** 한 칸에 담긴 것. 색인이 푸는 종목이거나, 담아 둔 코드가 색인에서 사라진
 *  **낡은 칸**이거나, 빈 칸입니다. */
export type Slot = { kind: 'tile'; tile: Tile } | { kind: 'stale'; code: string } | null

/* 색인에 없는 코드가 담긴 칸 — 담아 둔 월물이 만기를 지나 마스터에서 빠진 경우가
 * 대부분입니다. **못 찾았을 때 대신 세울 것이 있으면 그것을 세웁니다** — 저장한
 * 것이 코드뿐이라 이름 자리에 코드(흐림), 값 자리에 한 마디. 숫자 자리를 뼈대나
 * 「—」로 채우지 않습니다(앞은 「곧 온다」, 뒤는 「원래 없다」라 둘 다 거짓이고,
 * 할 일이 있습니다 — 빼거나 바꿉니다). 큰 타일이면 곡선 자리도 없습니다 —
 * 자리를 남기고 비우면 「아직 안 받음」으로 읽힙니다. */
export function StaleTile({ code, lead }: { code: string; lead: boolean }) {
  /* 큰 타일과 목록 줄은 다른 격자라 같은 칸 이름을 씁니다 — 목록 줄에서는
     한 마디가 값 세 칸을 대신합니다(값이 없는 종목 줄과 같은 자리). */
  return (
    <>
      <span className={`${lead ? 'tile-name' : 'quote-name'} home-stale-code`} title={code}>
        {code}
      </span>
      {/* 큰 타일은 문장, 목록 줄은 한 마디 — 자리 폭이 다릅니다. 까닭(만기 지남
          등)은 화면이 모르니 적지 않습니다. 낱말은 못 연 종목 줄(`app-missing`)과
          같습니다. */}
      <span className={lead ? 'tile-word' : 'quote-word'}>
        {lead ? '종목 목록에 없는 종목입니다' : '목록에 없음'}
      </span>
    </>
  )
}

export function RemoveButton({ name, onRemove }: { name: string; onRemove: () => void }) {
  return (
    <button
      type="button"
      className="home-remove"
      aria-label={`${name} 빼기`}
      title="빼기"
      onClick={onRemove}
    >
      ✕
    </button>
  )
}
