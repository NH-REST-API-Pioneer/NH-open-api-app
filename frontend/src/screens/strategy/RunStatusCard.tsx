import { kstClockSeconds } from '../../lib/kst'
import { MINUS, Num, moneyIn } from '../../lib/number'
import { condCount, oppositeSignalOf, type Aux, type Rule, type RuleSet } from '../../data/strategyRules'
import type { ExpectedOrder, VerifyRun } from '../../data/strategyRuns'

/* 진행 탭 실행 상세의 상태 카드 — 자금 · 가격 · 신호가 나면 나갈 주문.
 *
 * **값은 실행 줄이 실어 온 그대로입니다.** 묶인 증거금·남은 돈·예상 주문가는
 * 서버가 한도 검사와 실제 주문에 쓰는 셈으로 내 줍니다. 화면이 다시 셈하면 화면의
 * 숫자와 서버가 막는 숫자가 갈립니다. 서버가 셈하지 못한 칸은 「셈하지 못함」으로
 * 두고 까닭을 마우스에 답니다.
 */

/** 계약당 증거금을 거래소만 셈할 수 있는 근거. 이 근거면 기다려도 값이 오지 않습니다. */
const EXCHANGE_BASES = ['no-margin-field', 'sell-unknown', 'mixed']

const NOT_COUNTED = '셈하지 못함'

const SIDE_WORD = { buy: '매수', sell: '매도' } as const
type Side = keyof typeof SIDE_WORD

/** 나갈 주문 한 줄의 재료. */
interface Planned {
  key: string
  rule: string
  side: Side
  quantity: number
  expected: ExpectedOrder | null
}

/** 값을 그 종목의 자릿수로 적은 글자. 문장 안에 넣을 때 씁니다. 음수는 값 칸(`Num`)과
 *  같은 마이너스 기호로 적습니다. */
function priceWord(value: number, decimals: number): string {
  const text = Math.abs(value).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
  return value < 0 ? `${MINUS}${text}` : text
}

/** 신호를 낼 수 있는 규칙인지 — 켜져 있고 조건이 하나라도 있습니다. 서버가 판정하는
 *  규칙과 같은 잣대입니다. */
function usable(rule: Rule | null | undefined): boolean {
  return !!rule && rule.on && condCount(rule) > 0
}

/** 지정가 주문의 가격 기준. 방향마다 기준이 있으면 그것, 없으면 공용 기준입니다.
 *  설정의 「신호가」는 지금 가격으로 셈하므로 「현재가」로 적습니다. */
function basisOf(aux: Aux | null | undefined, side: Side): string {
  const own = side === 'buy' ? aux?.buyPriceBasis : aux?.sellPriceBasis
  const basis = (own ?? '').trim() || (aux?.priceBasis ?? '').trim()
  return basis.replace('신호가', '현재가')
}

/** 주문 유형마다 예상가를 어떻게 셌는지 한 문장. */
function footOf(
  expected: ExpectedOrder | null | undefined,
  aux: Aux | null | undefined,
  side: Side,
  decimals: number,
): string {
  if (!expected) return ''
  const tail = '실제 체결가와 다를 수 있습니다'
  const stop = expected.stopPrice === null ? '—' : priceWord(expected.stopPrice, decimals)
  switch (expected.orderType) {
    case '시장가':
      return `시장가라 현재가로 셉니다. ${tail}`
    case '지정가': {
      const basis = basisOf(aux, side)
      return basis ? `지정가 규칙(${basis})으로 셉니다. ${tail}` : `지정가 규칙으로 셉니다. ${tail}`
    }
    case 'STOP-M':
      return `스탑가 ${stop}에 걸리면 시장가로 나갑니다. ${tail}`
    case 'STOP-L': {
      const price = expected.price === null ? '—' : priceWord(expected.price, decimals)
      return `스탑가 ${stop}에 걸리면 지정가 ${price}로 나갑니다. ${tail}`
    }
    default:
      return tail
  }
}

export function RunStatusCard({
  run,
  aux,
  rules,
  decimals,
  currency,
}: {
  run: VerifyRun
  /** 그 실행이 도는 버전의 설정. 아직 못 받았으면 비어 있습니다. */
  aux: Aux | null | undefined
  rules: RuleSet | null | undefined
  decimals: number
  /** 금액을 적을 통화(`runCurrencyOf`). */
  currency: string
}) {
  /* ── 자금 ── */
  const budget = run.marginBudget ?? run.cash
  const used = run.marginUsed ?? null
  const left = run.marginLeft ?? null
  const basis = run.perContractBasis
  const unknownWhy =
    basis !== null && EXCHANGE_BASES.includes(basis)
      ? '계약당 증거금은 거래소가 셈합니다'
      : '계약당 증거금을 아직 모릅니다'
  /* 묶인 돈은 셈했는데 남은 돈이 없으면 예산을 정하지 않은 실행입니다. */
  const leftWhy = used !== null && left === null ? '증거금 예산을 정하지 않았습니다' : unknownWhy

  /* ── 가격 ── */
  const quoteAt = run.quoteAt ?? (run.feedAt > 0 ? run.feedAt : null)

  /* ── 신호가 나면 나갈 주문 ──
     보유가 있으면 그 보유를 닫는 주문(`exit`) 하나입니다. 그 보유의 청산 규칙이
     있으면 「{보유 방향} 청산」, 없더라도 반대 신호에 청산하는 설정이고 반대 방향
     진입 규칙이 있으면 「반대 신호 청산」입니다. 둘 다 없으면 신호로 나갈 청산이
     없습니다 — 서버의 `exit` 는 규칙과 상관없이 셈한 값이라 화면이 여기서 가립니다.
     보유가 없으면 신호를 낼 수 있는 진입 규칙마다 그 방향의 진입 주문 하나입니다. */
  const holding = (run.position ?? 0) > 0 && run.side !== null ? run.side : null
  const exit = run.expectedOrder?.exit ?? null
  const closeRule = holding
    ? usable(rules?.[holding === 'buy' ? 'buyExit' : 'sellExit'])
      ? `${SIDE_WORD[holding]} 청산`
      : oppositeSignalOf(aux?.oppositeSignal) !== 'ignore' &&
          usable(rules?.[holding === 'buy' ? 'sellEntry' : 'buyEntry'])
        ? '반대 신호 청산'
        : null
    : null
  const planned: Planned[] = holding
    ? closeRule
      ? [
          {
            key: 'exit',
            rule: closeRule,
            side: exit?.side ?? (holding === 'buy' ? 'sell' : 'buy'),
            quantity: run.position ?? 0,
            expected: exit,
          },
        ]
      : []
    : (['buy', 'sell'] as const)
        .filter((side) => usable(rules?.[side === 'buy' ? 'buyEntry' : 'sellEntry']))
        .map((side) => ({
          key: side,
          rule: `${SIDE_WORD[side]} 진입`,
          side,
          quantity: run.qty,
          expected: run.expectedOrder?.[side] ?? null,
        }))

  return (
    <div className="run-status">
      <section className="run-status-cell">
        <h3 className="run-status-title">자금</h3>
        <dl className="run-status-list">
          <div>
            <dt>이 실행의 자금</dt>
            <dd>{moneyIn(budget, currency)}</dd>
          </div>
          <div>
            <dt>증거금으로 묶임</dt>
            <dd title={used === null ? unknownWhy : undefined}>
              {used === null ? NOT_COUNTED : moneyIn(used, currency)}
            </dd>
          </div>
          {used !== null && run.perContract !== null && (
            <div className="run-status-sub">
              <dt>
                (보유 {run.position ?? 0} + 진입 주문 {run.openEntry ?? 0}) × 계약당{' '}
                {moneyIn(run.perContract, currency)}
              </dt>
            </div>
          )}
          <div className="run-status-sum">
            <dt>남은 돈</dt>
            <dd title={left === null ? leftWhy : undefined}>
              {left === null ? NOT_COUNTED : moneyIn(left, currency)}
            </dd>
          </div>
        </dl>
      </section>

      <section className="run-status-cell">
        <h3 className="run-status-title">
          가격
          <span className="run-status-at">{quoteAt === null ? '' : kstClockSeconds(quoteAt)}</span>
        </h3>
        <dl className="run-status-list">
          <div>
            <dt>현재가</dt>
            <dd className="run-status-big">
              {run.lastPrice === null ? '—' : <Num value={run.lastPrice} decimals={decimals} />}
            </dd>
          </div>
          <div>
            <dt>매수1 호가</dt>
            <dd>{run.bid1 == null ? '—' : <Num value={run.bid1} decimals={decimals} />}</dd>
          </div>
          <div>
            <dt>매도1 호가</dt>
            <dd>{run.ask1 == null ? '—' : <Num value={run.ask1} decimals={decimals} />}</dd>
          </div>
        </dl>
      </section>

      <section className="run-status-cell">
        <h3 className="run-status-title">신호가 나면 나갈 주문</h3>
        {planned.length === 0 ? (
          <p className="run-status-foot">
            {!rules
              ? '전략 설정을 아직 받지 못했습니다'
              : holding
                ? '청산 규칙이 없습니다 — 손절·익절·추적만 지켜봅니다'
                : '켜진 진입 규칙이 없습니다'}
          </p>
        ) : (
          planned.map((one) => {
            const expected = one.expected
            const orderType = expected?.orderType || aux?.orderType || '—'
            return (
              <div key={one.key} className="run-status-order">
                <dl className="run-status-list">
                  <div>
                    <dt>규칙</dt>
                    <dd>{one.rule}</dd>
                  </div>
                  <div>
                    <dt>방향 · 수량</dt>
                    <dd>
                      <span className={one.side === 'buy' ? 'up' : 'down'}>{SIDE_WORD[one.side]}</span>{' '}
                      {one.quantity}계약
                    </dd>
                  </div>
                  <div>
                    <dt>주문 유형</dt>
                    <dd>{orderType}</dd>
                  </div>
                  <div className="run-status-sum">
                    <dt>예상가</dt>
                    {/* 서버가 이 주문을 셈하지 못했으면 「셈하지 못함」입니다. 주문가격이
                        없는 유형(시장가·STOP-M)은 지금 가격을 적습니다. */}
                    <dd>
                      {!expected ? (
                        NOT_COUNTED
                      ) : expected.price !== null ? (
                        <Num value={expected.price} decimals={decimals} />
                      ) : run.lastPrice !== null ? (
                        <>
                          현재가 <Num value={run.lastPrice} decimals={decimals} />
                        </>
                      ) : (
                        '—'
                      )}
                    </dd>
                  </div>
                </dl>
                <p className="run-status-foot">{footOf(expected, aux, one.side, decimals)}</p>
              </div>
            )
          })
        )}
      </section>
    </div>
  )
}
