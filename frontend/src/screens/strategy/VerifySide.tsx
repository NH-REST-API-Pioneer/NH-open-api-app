import { Fragment } from 'react'
import { FUNDS_SHORT, marginBasisWord, marginKnown, runFunds, type VerifyRun } from '../../data/strategyRuns'
import { sessionLabelOf } from '../../data/strategyRules'
import { storeNote, useStrategyState } from '../../data/strategyStore'
import { moneyIn } from '../../lib/number'
import { PICK_HINT, RunStats, targetLine } from './runStats'
import {
  type BottomTab,
  type Deed,
  FEED_LABEL,
  FundsNote,
  minuteOf,
  runSessionLabel,
  shortInstrument,
} from './strategyVerifyUtils'
import type { Dispatch, SetStateAction, RefObject } from 'react'
import type { useVerifyRun } from './useVerifyRun'
import type { useVerifyChart } from './useVerifyChart'
import type { makeVerifyActions } from './verifyActions'

type RunValues = ReturnType<typeof useVerifyRun>
type ChartValues = ReturnType<typeof useVerifyChart>
type ActionValues = ReturnType<typeof makeVerifyActions>
type SideParts = ReturnType<typeof verifySideParts>
type StoreState = ReturnType<typeof useStrategyState>

type VerifySideArgs = Pick<RunValues, 'picked'> &
  Pick<ChartValues, 'nameOf' | 'runCurrency' | 'currency'> &
  Pick<ActionValues, 'toggleCheck' | 'pickRun'> &
  {
    checked: string[]
    setBottom: Dispatch<SetStateAction<BottomTab>>
    tabAsked: RefObject<BottomTab | null>
    open: { fund: boolean; fill: boolean }
    setOpen: Dispatch<SetStateAction<{ fund: boolean; fill: boolean }>>
  }

/** 왼쪽 칸의 실행 줄·접는 카드와 돈·증거금을 적는 함수. */
export function verifySideParts({
  picked,
  checked,
  toggleCheck,
  setBottom,
  tabAsked,
  pickRun,
  nameOf,
  runCurrency,
  open,
  setOpen,
  currency,
}: VerifySideArgs) {
  function runRow(run: VerifyRun) {
    /* 끝난 실행. 앞으로 일어날 일을 말하는 줄들이 여기서는 빠집니다. */
    const done = run.state === 'ended'
    return (
      /* 값을 못 받는 중인 줄은 **흐리게**. 앞 박자에 받은 값이 그대로 선 것이라
         「지금 값이 아니다」를 말해야 하는데, 값마다 표시를 달면 줄이 표시로
         덮입니다. 단추는 안 흐려집니다 — 그때도 눌러야 하는 것들입니다. */
      /* 체크는 「이 실행에 동작을 건다」, 줄 몸 누름은 「이 실행을 본다」입니다.
         보는 실행 표시는 줄 바탕(`is-picked`)이 맡습니다. */
      <label
        className={`vrf-run${run.id === picked?.id ? ' is-picked' : ''}${run.stale ? ' is-stale' : ''}`}
        key={run.id}
      >
        <input
          type="checkbox"
          checked={checked.includes(run.id)}
          onChange={() => toggleCheck(run.id)}
        />
        <button
          type="button"
          className="vrf-run-body"
          aria-current={run.id === picked?.id ? 'true' : undefined}
          onClick={(event) => {
            /* 「안 낸 신호」 배지를 누르면 그 실행을 고르고 이벤트 탭으로 갑니다 —
               까닭은 이벤트 줄에 있습니다. */
            const toEvents = (event.target as HTMLElement).closest('.vrf-unsent-badge') !== null
            if (toEvents) {
              if (run.id === picked?.id) setBottom('이벤트')
              else tabAsked.current = '이벤트'
            }
            pickRun(run.id)
          }}
        >
          {/* 버전과 종목을 **줄을 나눠** 적습니다. 한 줄에 붙이면 좁은 열에서
              종목이 만기부터 잘리는데, 하필 잘리는 자리가 만기입니다. */}
          <span className="vrf-run-name">
            <span className="vrf-run-name-text">{nameOf(run.version).name}</span>
          </span>
          <span className="vrf-run-sub">{nameOf(run.version).version}</span>
          <span className="vrf-run-sub">{shortInstrument(run.code)}</span>
          {/* 세션은 제 줄에 — 같은 전략을 주간·야간으로 따로 돌리면 둘을 가르는
              것이 세션뿐입니다. */}
          <span className="vrf-run-sub">{runSessionLabel(run)}</span>
          {/* 상태와 가상 보유는 값이라 본문색입니다. 색으로 상태를 말하면
              읽는 사람이 색표를 외워야 합니다. 낱말은 **서버가 함께 줍니다** —
              화면이 상태 표를 또 두면 두 표가 갈립니다. */}
          <span className="vrf-run-state">
            {run.stateLabel}
            {(run.position ?? 0) > 0 && ` · ${run.side === 'buy' ? '매수' : '매도'} ${run.position}계약`}
            {/* 자금이 증거금에 못 미치면 이 실행은 진입이 막힙니다(서버가 막음).
                끝난 실행에는 앞이 없어 안 답니다. */}
            {!done && runFunds(run, runCurrency(run)).kind === 'short' && (
              <span className="badge badge-warn vrf-funds-badge" title={FUNDS_SHORT}>
                자금 부족
              </span>
            )}
            {/* 오늘 규칙이 참이었는데 주문을 내지 않은 봉의 수. 까닭은 이벤트에
                있습니다(누르면 그 탭). 없으면 안 섭니다. */}
            {(run.unsentToday ?? 0) > 0 && (
              <span className="badge badge-warn vrf-unsent-badge" title={`오늘 안 낸 신호 ${run.unsentToday}건`}>
                안 낸 신호 {run.unsentToday}
              </span>
            )}
          </span>
          {/* 성과 한 줄 — 서버가 센 신호·체결 수와 손익, 마지막 신호 시각. */}
          <RunStats run={run} currency={runCurrency(run)} />
          {/* 봉이 모자라 아직 판정을 못 하는 동안은 그 사실이 상태보다 먼저
              알아야 하는 것입니다 — 「감시 중」인데 아무 일도 안 나는 까닭입니다. */}
          {/* 준비 중은 **중립**입니다 — 이상이 아니라 아직 봉이 모자란 것입니다.
              경고색은 끊김 하나가 씁니다(머리의 점과 같은 규칙).

              **끝난 실행에는 안 세웁니다.** 준비도 시세도 「앞으로 올 것」을
              말하는 줄인데, 끝난 실행에는 앞이 없습니다. */}
          {/* 봉 수를 모르면(`null`) 준비 줄을 세우지 않습니다 — 「확보 —」는 준비 중인지
              아닌지를 말하지 못합니다. */}
          {!done && run.warmup != null && run.bars != null && run.bars < run.warmup && (
            <span className="vrf-run-feed">
              준비 중 — 필요 {run.warmup} · 확보 {run.bars}
            </span>
          )}
          {!done && run.feed !== 'live' && (
            <span className={`vrf-run-feed${run.feed === 'gap' ? ' is-warn' : ''}`}>
              시세 {FEED_LABEL[run.feed]}
              {/* 「마지막」은 **끊긴 줄에만** 답니다. 아직 안 붙은 줄에 마지막
                  시각이 서면 「온 적 없다」와 「여기까지 왔다」가 한 줄에 함께
                  섭니다. */}
              {run.feed === 'gap' && run.feedAt > 0 && ` · 마지막 ${minuteOf(run.feedAt)}`}
            </span>
          )}
        </button>
      </label>
    )
  }

  function accordion(
    id: keyof typeof open,
    title: string,
    summary: string,
    body: React.ReactNode,
    warn: string = '',
  ) {
    return (
      <section className="card vrf-acc">
        <button
          type="button"
          className="vrf-acc-head"
          aria-expanded={open[id]}
          aria-label={`${title} ${open[id] ? '접기' : '펼치기'}`}
          /* 직전 값에서 뒤집습니다 — 바깥의 `open` 을 그대로 쓰면 같은 순간에
             두 아코디언을 누를 때 앞의 것이 묻힙니다. */
          onClick={() => setOpen((prev) => ({ ...prev, [id]: !prev[id] }))}
        >
          <span className="vrf-acc-title">{title}</span>
          {!open[id] && (
            <span className="vrf-acc-sum" title={summary}>
              {summary}
            </span>
          )}
          {/* 경고는 요약 밖에 따로 둡니다 — 좁은 칸에서 요약이 말줄임으로 잘려도
              이 말은 남습니다. */}
          {!open[id] && warn && <span className="vrf-acc-warn">{warn}</span>}
          <span className="vrf-acc-mark">{open[id] ? '⌃' : '⌄'}</span>
        </button>
        {open[id] && <div className="vrf-acc-body">{body}</div>}
      </section>
    )
  }

  /** 돈을 적는 말. **통화는 그 실행의 것**입니다 — 해외 전략을 검증하면
   *  실행 자금도 그 통화로 셉니다. */
  const money = (value: number | null, unit = currency) => moneyIn(value, unit)

  /* 사용 증거금 = (보유 + 진입 미체결 + 이번 주문) × 계약당. **서버의 한도
     검사와 같은 셈**입니다. 계약당을 못 내는 근거에서는 이 값도 못 냅니다. */
  const usedOf = (row: VerifyRun): number | null =>
    /* 보유나 나가 있는 진입 수량을 모르면 사용액도 모릅니다 — 0 으로 더하면 실제보다
       적게 셉니다. */
    row.perContract === null || row.position === null || row.openEntry === null
      ? null
      : (row.position + row.openEntry + row.qty) * row.perContract

  /* 「—」와 「아직 못 받음」은 다릅니다 — 앞은 그 갈래에서 **원래 없는 값**이고,
     뒤는 낼 수 있는데 재료가 아직 안 온 것입니다. 한 말로 뭉뚱그리면 기다리면
     되는 자리와 기다려도 안 되는 자리가 같아 보입니다. */
  const usedText = (row: VerifyRun): string => {
    if (!marginKnown(row.perContractBasis)) return '—'
    const used = usedOf(row)
    if (used === null) return '아직 못 받음'
    return row.perContractBasis === 'premium-now' ? `${money(used)}(어림)` : money(used)
  }

  /* 증거금 줄의 조각들. **글자 하나로 안 냅니다** — 좁은 판에서 줄이 접힐 때
     「· 사용」과 그 값이 갈리면 사용액이 계약당 값의 꼬리처럼 읽힙니다. 조각마다
     안 끊기게 두고 조각 사이에서만 접습니다. */
  /* 증거금 줄에 설 것 — **값 조각들과 까닭을 한 번에** 냅니다. 둘을 따로 세면
     같은 갈래 판정을 두 번 하게 되고, 한쪽만 고쳐지는 날 값과 까닭이 어긋납니다.
     - `parts` 는 **글자 하나로 안 냅니다**: 좁은 판에서 줄이 접힐 때 「· 사용」과
       그 값이 갈리면 사용액이 계약당 값의 꼬리처럼 읽힙니다.
     - `why` 는 **값이 아니라 설명**이라 값들과 「·」로 잇지 않고 흐린 꼬리로 답니다. */
  const marginLine = (row: VerifyRun): { parts: string[]; why: string } => {
    const word = marginBasisWord(row.perContractBasis)
    if (!marginKnown(row.perContractBasis)) return { parts: ['계약당 —', '사용 —'], why: word }
    if (row.perContract === null) {
      return { parts: ['계약당 아직 못 받음', '사용 아직 못 받음'], why: '' }
    }
    const each = word ? `계약당 ${money(row.perContract)}(${word})` : `계약당 ${money(row.perContract)}`
    return { parts: [each, `사용 ${usedText(row)}`], why: '' }
  }

  return {
    runRow,
    accordion,
    money,
    usedText,
    marginLine,
  }
}

type RunsCardArgs = Pick<RunValues, 'all'> &
  Pick<ActionValues, 'chosen' | 'acts' | 'whyIdOf' | 'groups'> &
  Pick<SideParts, 'runRow'> &
  {
    storeWhy: ReturnType<typeof storeNote>
    status: StoreState['verify']['status']
    setDeed: Dispatch<SetStateAction<Deed | null>>
  }

/** 실행 카드 — 실행 목록, 고른 실행에 거는 단추와 못 누르는 까닭. */
export function renderRunsCard({
  storeWhy,
  status,
  all,
  runRow,
  chosen,
  acts,
  whyIdOf,
  setDeed,
  groups,
}: RunsCardArgs) {
  return (
          <div className="card vrf-runs">
            <h2 className="vrf-card-title">실행</h2>
            {/* 담아 둔 실행을 서버가 못 읽었으면 **목록이 빈 까닭**을 이 카드
                안에 한 줄로 답니다. 카드는 단추가 서 있어 통째로 비지 않으므로
                블록이 아니라 줄입니다. 위의 「못 받았다」와도 다른 말입니다 —
                그쪽은 서버에 못 닿은 것이고 이쪽은 서버가 파일을 못 읽은 것이라
                다시 받아도 같습니다.
                파일 이름은 **마우스를 올렸을 때만** 보입니다 — 사용자가 할 일을
                바꾸는 말이 아니라 나중에 찾을 때 쓰는 말이고, 좁은 카드에서
                여러 줄로 접히면 실행 목록이 밀려납니다. */}
            {storeWhy !== null && (
              <p className="vrf-store-why" title={storeWhy.reason ?? undefined}>
                {storeWhy.title}
              </p>
            )}
            <div className="vrf-run-list">
              {status === 'loading' && <p className="vrf-why">실행 목록을 받는 중입니다</p>}
              {/* 비었다는 말은 가운데 빈 화면이 합니다 — 여기 또 적으면 같은 말이 두 번 섭니다.
                  담아 둔 파일을 **못 읽었으면 그 빈 화면도 안 섭니다** — 바로 위 한 줄이 이미
                  무슨 일인지 말했고, 「없다」고 하면 그 말과 반대가 됩니다. 이 앱 파일이 아닌
                  경우는 읽기는 읽었고 그 실행들이 안 도는 것이 사실이라 빈 화면이 섭니다. */}
              {all.map(runRow)}
            </div>
            {/* 단추는 모두 확인 창을 지납니다 — 여러 실행을 고르므로 무엇에 걸리고
                무엇이 빠지는지를 창이 먼저 보입니다. **「확인 필요」 줄에는 어떤
                요청도 보내지 않습니다** — 사용자가 먼저 풀어야 합니다. */}
            {all.length > 0 && <p className="vrf-target">{targetLine(chosen.length)}</p>}
            {acts.map((one) => (
              <button
                key={one.id}
                type="button"
                className="btn btn-quiet vrf-stop"
                aria-disabled={one.why !== null}
                aria-describedby={one.why === null ? undefined : whyIdOf(one.id)}
                title={one.why === PICK_HINT ? PICK_HINT : undefined}
                onClick={() => {
                  if (one.why === null) setDeed(one.deed)
                }}
              >
                {one.label}
              </button>
            ))}
            {/* 못 누르는 까닭은 눌리지 않는 단추 아래에 답니다. 막힌 것이
                없어도 빈 줄 하나를 두어 목록이 오르내리지 않습니다. */}
            <div className="vrf-whys">
              {groups.length === 0 ? (
                <p className="vrf-why" />
              ) : (
                groups.map((group) => (
                  <p className="vrf-why" id={`vrf-why-${group.ids[0]}`} key={group.ids[0]}>
                    {groups.length > 1 && `${group.names.join(' · ')}: `}
                    {group.why}
                  </p>
                ))
              )}
            </div>
          </div>
  )
}

type FundSectionsArgs = Pick<RunValues, 'all' | 'picked'> &
  Pick<ChartValues, 'currency'> &
  Pick<SideParts, 'accordion' | 'usedText' | 'money' | 'marginLine'>

/** 자금 · 증거금과 체결 가정 카드. */
export function renderFundSections({
  all,
  accordion,
  picked,
  usedText,
  money,
  marginLine,
  currency,
}: FundSectionsArgs) {
  return (
          all.length > 0 && (
          <>
          {accordion(
            'fund',
            /* 이름에 「실행」을 붙이지 않습니다 — 이 화면이 통째로 실행 하나를 보는
               자리라 없어도 같은 말이고, 그 두 글자가 접힘 머리의 값을 자릅니다
               (값에 쓸 수 있는 폭 84px, 필요한 폭 90px). */
            '자금 · 증거금',
            /* 접힘 머리에는 **사용액 하나만** 적습니다. 실행 자금은 사용자가 정해
               둔 값이라 접힌 채로 다시 볼 까닭이 없고, 둘을 다 세우면 좁은 판에서
               값이 잘립니다 — 접힘 머리는 「지금 어떤가」 하나를 답하는 자리입니다. */
            picked ? `사용 ${usedText(picked)}` : '—',
            <>
              {/* 증거금을 정하는 값이라 자금 옆에 둡니다. 위 상태 줄은 지금
                  들고 있는 것만 싣습니다.

                  **맨 위입니다.** 아래 안내는 두 자금 줄을 가리키는 말이라,
                  자금 밑에 두면 사용자가 정한 수량을 가리키는 것으로 읽힙니다. */}
              <div className="vrf-row">
                <span>주문당 수량</span>
                <b>{picked ? `${picked.qty}계약` : '—'}</b>
              </div>
              <div className="vrf-row">
                <span>실행 자금</span>
                <b>{picked ? money(picked.cash) : '—'}</b>
              </div>
              {/* **계약당과 사용액은 다른 값입니다.** 줄에 실려 오는 것은 계약
                  하나에 드는 돈인데, 「묶인 증거금」으로 적으면 지금 묶여 있는
                  금액으로 읽힙니다. 둘을 한 줄에 나란히 적어 무엇이 무엇인지
                  글자로 가릅니다.

                  사용액은 **서버의 한도 검사와 같은 셈**입니다 — 보유에 나가 있는
                  진입 주문과 이번 주문 수량까지 더해 계약당을 곱합니다. 셈이
                  갈리면 사용자는 막힌 까닭을 화면에서 못 찾습니다. */}
              <div className="vrf-row is-long">
                <span>증거금</span>
                <b>
                  {picked
                    ? (() => {
                        const { parts, why } = marginLine(picked)
                        return (
                          <>
                            {parts.map((part, index) => (
                              /* 조각 **사이에만** 빈칸을 둡니다 — 줄은 여기서만
                                 바뀌고, 가운뎃점은 뒤 조각에 붙어 함께 내려갑니다. */
                              <Fragment key={part}>
                                {index > 0 && ' '}
                                <span>
                                  {index > 0 && '· '}
                                  {part}
                                </span>
                              </Fragment>
                            ))}
                            {why && (
                              <>
                                {' '}
                                <span className="vrf-row-why">{why}</span>
                              </>
                            )}
                          </>
                        )
                      })()
                    : '—'}
                </b>
              </div>
              {/* 자금과 증거금을 견준 결과. 셈은 실행 카드의 배지와 같습니다. */}
              {picked && picked.state !== 'ended' && (
                <FundsNote verdict={runFunds(picked, currency)} qty={picked.qty} currency={currency} />
              )}
              <p className="vrf-hint">가상 장부라 실제 주문가능수량과 다릅니다</p>
            </>,
            picked && picked.state !== 'ended' && runFunds(picked, currency).kind === 'short' ? '자금 부족' : '',
          )}

          {accordion(
            'fill',
            '체결 가정',
            picked ? `${sessionLabelOf(picked.session)} · 지연 0.3초` : '—',
            <>
              <div className="vrf-row">
                <span>세션</span>
                {/* 줄이 실어 오는 것은 키(`domestic-day`)입니다. **사람이 읽는
                    자리에는 글자로** 세웁니다 — 키는 서버와 주고받는 이름이지
                    화면에 적는 말이 아닙니다. */}
                <b>{picked ? sessionLabelOf(picked.session) : '—'}</b>
              </div>
              <div className="vrf-row">
                <span>대기 지정가</span>
                <b>보수적 대기열</b>
              </div>
              <div className="vrf-row">
                <span>처리 지연</span>
                <b>0.3초</b>
              </div>
              <p className="vrf-hint">거래소와 같은 결과를 보장하지 않습니다</p>
            </>,
          )}
          </>
          )
  )
}
