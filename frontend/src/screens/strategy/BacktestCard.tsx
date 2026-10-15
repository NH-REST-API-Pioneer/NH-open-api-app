import { useEffect, useMemo, useRef, useState } from 'react'

import {
  backtestAsk,
  postBacktest,
  type BacktestAnswer,
  type BacktestRange,
  type BacktestTrade,
  type UnjudgedCondition,
} from '../../data/backtest'
import { resolve } from '../../data/instruments'
import { codeOfVersion, type StrategyVersion } from '../../data/strategyList'
import { MOMENT_TITLE, RULE_KEYS, RULE_LABEL, operandWord, type RuleKey, type SettingsDraft } from '../../data/strategyRules'
import { reasonWord } from '../../data/strategyRuns'
import { kstParts } from '../../lib/kst'
import { NumOrDash, currencyCode, currencyDigits, moneyIn, toneOf } from '../../lib/number'

/* 설정 화면 오른쪽 열의 「지난 봉으로 돌려 보기」 카드.
 *
 * 지금 규칙(저장 전이어도)을 받아 둔 지난 봉에 대 본 답을 보입니다. **단추가
 * 없습니다** — 범위를 바꾸면 곧바로, 규칙을 고치면 손을 멈춘 뒤 0.6초에 다시
 * 셉니다. 셈은 서버가 하고 아무것도 남기지 않습니다(저장·실행·기록 0). */

const RANGES: { id: BacktestRange; label: string }[] = [
  { id: '1d', label: '최근 1일' },
  { id: '3d', label: '최근 3일' },
  { id: 'all', label: '받은 만큼' },
]

/** 규칙을 고친 뒤 다시 셀 때까지 기다리는 시간. 타자 중에는 셈을 부르지 않습니다. */
const SETTLE_MS = 600
/** 다른 셈이 돌고 있다는 답(409)에 다시 보내는 간격과 횟수. */
const BUSY_RETRY_MS = 500
const BUSY_RETRIES = 6
/** 거래 표가 이보다 길면 표 안에서 굴립니다. */
const TABLE_ROWS = 20

type Status = 'idle' | 'busy' | 'done' | 'failed'

function monthDay(ms: number): string {
  const { month, day } = kstParts(ms)
  return `${month}/${day}`
}

/** 진입 시각 — 날짜와 시각을 두 줄로(좁은 열). */
function stamp(ms: number) {
  const { month, day, hour, minute } = kstParts(ms)
  return (
    <>
      {month}/{day}
      <br />
      {String(hour).padStart(2, '0')}:{String(minute).padStart(2, '0')}
    </>
  )
}

/** 부호를 단 금액 — 이익은 「+」, 손실은 「−」(`moneyIn`), 0 은 부호 없이. */
function signedMoney(value: number, currency: string): string {
  const text = moneyIn(value, currency)
  return value > 0 ? `+${text}` : text
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((done) => {
    const timer = window.setTimeout(done, ms)
    signal.addEventListener('abort', () => {
      window.clearTimeout(timer)
      done()
    })
  })
}

/* 「계약당 수수료」 칸의 마지막 값. 이 화면에서만 기억합니다 — 설정에 저장하는 값이
   아니라, 셈을 볼 때마다 다시 치지 않도록 둡니다. 버전과 상관없는 값 하나입니다.
   저장소가 막혀 있거나 남은 값이 수가 아니면 0 으로 읽습니다. */
const FEE_KEY = 'nh.backtestFee'

/** 기억해 둔 값과 칸에 세울 글자. 남은 값이 없으면 0, 수가 아니거나 음수면 칸을
 *  비우고 0 으로 셉니다. */
function readFee(): { value: number; text: string } {
  try {
    const raw = localStorage.getItem(FEE_KEY)
    if (raw === null) return { value: 0, text: '0' }
    const value = Number(raw)
    return Number.isFinite(value) && value >= 0 ? { value, text: String(value) } : { value: 0, text: '' }
  } catch {
    return { value: 0, text: '0' }
  }
}

/* 가정 줄의 계약당 수수료. 소수는 **통화 자릿수 이상, 더 친 자리는 그대로** 적습니다
   (USD 1.5 → 「1.50 USD」, 0.125 → 「0.125 USD」, 원 1.5 → 「1.5원」). 통화 자릿수로
   반올림하면 원 전략에 1.5 를 넣었을 때 칸은 1.5 인데 가정 줄은 2원이 됩니다. */
function feeIn(fee: number, currency: string): string {
  const code = currencyCode(currency)
  if (!Number.isFinite(fee) || code === '') return moneyIn(fee, currency)
  const least = currencyDigits(code) ?? 2
  const digits = Math.min(20, Math.max(least, decimalsOf(fee)))
  const text = fee.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
  return code === 'KRW' ? `${text}원` : `${text} ${code}`
}

/** 값을 적을 때 쓰인 소수 자리 수(「1.5」 → 1, 「1e-7」 → 7). */
function decimalsOf(value: number): number {
  const [body, exponent] = String(Math.abs(value)).split('e')
  const fraction = body.split('.')[1]?.length ?? 0
  return Math.max(0, fraction - Number(exponent ?? 0))
}

/* 칸에 수로 읽히지 않는 글자를 쳤을 때 칸 곁에 세우는 말. */
const FEE_NOT_NUMBER = '계약당 수수료는 수로 적으세요'

function keepFee(value: number): void {
  try {
    localStorage.setItem(FEE_KEY, String(value))
  } catch {
    /* 기억하지 못해도 셈은 그대로입니다. */
  }
}

export function BacktestCard({
  version,
  draft,
  dirty,
  blocked,
  currency,
}: {
  version: StrategyVersion
  draft: SettingsDraft
  /** 저장 안 한 고침이 있는지 — 있으면 카드 머리에 「저장 전 규칙으로 셈」. */
  dirty: boolean
  /** 저장이 막힌 상태인지(저장 단추와 같은 판정). 막혀 있으면 셈을 부르지 않습니다. */
  blocked: boolean
  currency: string
}) {
  /* 범위는 **저장하지 않는 화면 값**입니다 — 탭을 다시 열면 「받은 만큼」입니다. */
  const [range, setRange] = useState<BacktestRange>('all')
  const [status, setStatus] = useState<Status>('idle')
  const [answer, setAnswer] = useState<BacktestAnswer | null>(null)
  /* 보이는 답을 셈한 요청의 열쇠. 지금 설정의 열쇠와 다르면 그 답은 옛 설정의 답입니다. */
  const [answerKey, setAnswerKey] = useState('')
  const [why, setWhy] = useState<string | null>(null)
  const [showTrades, setShowTrades] = useState(false)
  /* 계약당 수수료 — 셈에 쓰는 값(`fee`)과 칸에 친 글자(`feeText`). 셈은 Enter 를
     치거나 칸을 떠날 때만 다시 합니다 — 칠 때마다 셈을 부르면 한 자리 칠 때마다
     요청이 나갑니다. 칸의 글자는 자릿수로 꾸미지 않습니다 — 칸에 보이는 값이 셈에
     넣은 값과 같아야 합니다. */
  const code = currencyCode(currency)
  const [fee, setFee] = useState<number>(() => readFee().value)
  const [feeText, setFeeText] = useState(() => readFee().text)
  const [feeWhy, setFeeWhy] = useState<string | null>(null)
  const feeBox = useRef<HTMLInputElement>(null)
  function commitFee() {
    const box = feeBox.current
    if (!box) return
    /* 수로 읽히지 않는 글자(「e」 등)면 셈을 부르지 않고 그 까닭을 칸 곁에 세웁니다 —
       보던 결과는 그대로입니다. 빈 칸은 0 입니다. 음수는 고치지 않고 그대로 보내
       서버의 까닭을 세웁니다 — 화면이 따로 막으면 서버가 받는 범위와 갈릴 수 있습니다. */
    if (box.validity.badInput) {
      setFeeWhy(FEE_NOT_NUMBER)
      return
    }
    setFeeWhy(null)
    const value = Number.isFinite(box.valueAsNumber) ? box.valueAsNumber : 0
    if (box.value !== '') setFeeText(String(value))
    if (value >= 0) keepFee(value)
    setFee(value)
  }

  /* 차례 번호와 끊는 손잡이. **늦게 온 옛 답은 버립니다** — 고친 뒤의 답이 먼저
     오고 고치기 전의 답이 뒤에 오면, 옛 규칙의 결과가 새 결과를 덮습니다. */
  const turn = useRef(0)
  const holder = useRef<AbortController | null>(null)

  const ask = useMemo(
    () => (blocked ? null : backtestAsk(version, draft, range, fee)),
    [blocked, version, draft, range, fee],
  )
  const key = ask === null ? '' : JSON.stringify(ask)
  /* 바로 셀지(처음·범위·수수료 바꿈) 손을 멈추길 기다릴지(규칙 고침). 수수료는
     이미 Enter·칸 떠남으로 정한 값이라 기다리지 않습니다. */
  const lastRange = useRef<BacktestRange | null>(null)
  const lastFee = useRef<number | null>(null)

  async function count(body: Record<string, unknown>) {
    holder.current?.abort()
    const control = new AbortController()
    holder.current = control
    turn.current += 1
    const mine = turn.current
    setStatus('busy')
    setWhy(null)
    for (let tried = 0; ; tried += 1) {
      const reply = await postBacktest(body, control.signal)
      if (reply === null || mine !== turn.current) return
      /* 다른 셈이 돌고 있으면 — 방금 끊은 앞 셈일 때가 많습니다 — 셈 중을 그대로 두고
         조금 뒤 다시 보냅니다. 그래도 안 되면 실패로 말합니다. */
      if (reply.kind === 'busy' && tried < BUSY_RETRIES) {
        await wait(BUSY_RETRY_MS, control.signal)
        if (control.signal.aborted || mine !== turn.current) return
        continue
      }
      if (reply.kind === 'done') {
        setAnswer(reply.answer)
        setAnswerKey(JSON.stringify(body))
        setStatus('done')
      } else {
        /* 실패해도 **앞 결과는 지우지 않습니다** — 「다시」를 누르기 전까지 보던 것을 봅니다. */
        setWhy(reply.why)
        setStatus('failed')
      }
      return
    }
  }

  useEffect(() => {
    if (ask === null) {
      holder.current?.abort()
      turn.current += 1
      setStatus('idle')
      return
    }
    const now = lastRange.current === null || lastRange.current !== range || lastFee.current !== fee
    lastRange.current = range
    lastFee.current = fee
    const timer = window.setTimeout(() => void count(ask), now ? 0 : SETTLE_MS)
    return () => window.clearTimeout(timer)
    // 몸이 같으면 다시 셀 까닭이 없습니다 — 열쇠로만 봅니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  /* 설정 탭을 떠나면(카드가 사라지면) 나간 요청을 끊고, 늦게 온 답은 아무 데도
     그리지 않습니다. 전략·버전을 바꾸면 몸이 바뀌어 위에서 끊깁니다. */
  useEffect(
    () => () => {
      holder.current?.abort()
      turn.current += 1
    },
    [],
  )
  useEffect(() => {
    setAnswer(null)
    setShowTrades(false)
  }, [version.id])

  const bars = answer?.bars
  const lockOf = (id: BacktestRange): string | null => {
    if (!bars || id === 'all') return null
    const need = id === '1d' ? 1 : 3
    return bars.sessions < need ? `받은 봉이 ${bars.have}개뿐입니다` : null
  }
  /* 고른 범위가 받은 봉으로는 안 되는 것으로 드러나면 「받은 만큼」으로 돌아갑니다 —
     잠긴 범위가 고른 채로 남으면 무엇으로 셈한 답인지 헷갈립니다. */
  const rangeLocked = lockOf(range) !== null
  useEffect(() => {
    if (rangeLocked) setRange('all')
  }, [rangeLocked])

  /* 거래 표의 가격 자릿수 — **종목 색인이 답합니다**(다른 체결 표와 같은 자리). 모르면
     「—」입니다: 자릿수를 지어내면 보이는 값이 받은 값과 달라집니다. */
  const decimals = resolve(codeOfVersion(version))?.product.decimals ?? null

  const trades = useMemo<BacktestTrade[]>(
    () => [...(answer?.trades ?? [])].sort((a, b) => b.openedAt - a.openedAt),
    [answer],
  )

  return (
    <section className="bt-card" aria-label="지난 봉으로 돌려 보기">
      <div className="bt-head">
        <h3 className="bt-title">지난 봉으로 돌려 보기</h3>
        {dirty && <span className="bt-draft">저장 전 규칙으로 셈</span>}
      </div>

      <div className="bt-range">
        <div className="seg" role="group" aria-label="범위">
          {RANGES.map((one) => {
            const lock = lockOf(one.id)
            return (
              <button
                key={one.id}
                type="button"
                className="seg-item"
                aria-pressed={range === one.id}
                aria-disabled={lock !== null}
                title={lock ?? undefined}
                onClick={() => {
                  if (lock === null) setRange(one.id)
                }}
              >
                {one.label}
              </button>
            )
          })}
        </div>
        {bars && bars.from !== null && bars.to !== null && (
          <span className="bt-span">
            {draft.baseBar} {bars.count.toLocaleString('en-US')}개 · {monthDay(bars.from)}~{monthDay(bars.to)}
          </span>
        )}
      </div>

      {/* 셈에 넣는 계약당 수수료. 범위 줄 바로 아래 한 줄이고, 단위는 그 전략의 통화입니다. */}
      <label className="bt-fee">
        <span className="bt-fee-label">계약당 수수료</span>
        <input
          ref={feeBox}
          className="control"
          type="number"
          min={0}
          step="any"
          value={feeText}
          aria-label="계약당 수수료"
          onChange={(event) => setFeeText(event.target.value)}
          onBlur={commitFee}
          onKeyDown={(event) => {
            if (event.key === 'Enter') commitFee()
          }}
        />
        <span className="bt-fee-unit">{code === 'KRW' ? '원' : code}</span>
        {feeWhy && <span className="bt-fee-why">{feeWhy}</span>}
      </label>

      {blocked ? (
        <p className="bt-state">조건을 다 채우면 셉니다</p>
      ) : (
        <>
          {status === 'busy' && (
            <p className="bt-state">
              {answer ? `셈하는 중 — ${answer.bars.count.toLocaleString('en-US')}봉` : '셈하는 중'}
            </p>
          )}
          {status === 'failed' && (
            <p className="bt-fail">
              셈하지 못했습니다 — {why}{' '}
              <button type="button" className="bt-link" onClick={() => ask && void count(ask)}>
                다시
              </button>
            </p>
          )}
          {/* 설정을 고치면 새 셈이 시작되기 전(손을 멈추길 기다리는 동안)에도 곧바로
              흐립니다 — 가정 줄은 지금 설정을 따르므로, 옛 숫자가 새 설정의 결과처럼
              읽히지 않게 합니다. 새 답이 오면 다시 또렷해집니다. */}
          {answer && (
            <div className={`bt-result${status === 'busy' || answerKey !== key ? ' is-stale' : ''}`}>
              {!answer.enough ? (
                <p className="bt-state">
                  봉이 모자랍니다 — 필요 {answer.bars.need.toLocaleString('en-US')} · 받은{' '}
                  {answer.bars.have.toLocaleString('en-US')}
                </p>
              ) : (
                <Result
                  answer={answer}
                  currency={currency}
                  decimals={decimals}
                  trades={trades}
                  show={showTrades}
                  onShow={setShowTrades}
                />
              )}
              <Assumptions
                answer={answer}
                daily={draft.baseBar === '일봉'}
                entryWindow={Boolean(draft.aux.entryStart.trim() || draft.aux.entryEnd.trim())}
                sessionEndFlat={draft.aux.sessionEndFlat}
                tickEval={draft.evalMode === '틱'}
                currency={currency}
              />
            </div>
          )}
        </>
      )}
    </section>
  )
}

function Result({
  answer,
  currency,
  decimals,
  trades,
  show,
  onShow,
}: {
  answer: BacktestAnswer
  currency: string
  decimals: number | null
  trades: BacktestTrade[]
  show: boolean
  onShow: (on: boolean) => void
}) {
  const tone = toneOf(answer.pl)
  return (
    <>
      <p className="bt-main">
        신호 {answer.signals.toLocaleString('en-US')} · 체결 {answer.fills.toLocaleString('en-US')} ·{' '}
        <span className={tone || undefined}>{signedMoney(answer.pl, currency)}</span>
      </p>
      <p className="bt-sub">
        승 {answer.wins} · 패 {answer.losses} · 최대 낙폭 {moneyIn(Math.abs(answer.maxDrawdown), currency)} · 수수료{' '}
        {moneyIn(answer.fee, currency)}
      </p>
      {answer.openPosition && (
        <p className="bt-sub">
          보유 남음 — {answer.openPosition.side === 'buy' ? '매수' : '매도'} {answer.openPosition.quantity}계약 · 평가{' '}
          {answer.openPosition.openPl === null ? (
            '—'
          ) : (
            <span className={toneOf(answer.openPosition.openPl) || undefined}>
              {signedMoney(answer.openPosition.openPl, currency)}
            </span>
          )}
        </p>
      )}
      {trades.length === 0 ? (
        <>
          <p className="bt-none">이 범위에서는 신호가 없었습니다</p>
          {/* 「바뀌는 순간」 표기와 같은 문장입니다 — 한 자리에서 가져옵니다. */}
          <p className="bt-note">{MOMENT_TITLE}</p>
        </>
      ) : (
        <>
          <button type="button" className="bt-link" aria-expanded={show} onClick={() => onShow(!show)}>
            거래 {trades.length.toLocaleString('en-US')}건 {show ? '접기' : '보기'}
          </button>
          {show && (
            <div className={`bt-table${trades.length > TABLE_ROWS ? ' is-long' : ''}`}>
              <table>
                <thead>
                  <tr>
                    <th scope="col">진입</th>
                    <th scope="col">방향</th>
                    <th scope="col">진입가</th>
                    <th scope="col">청산가</th>
                    <th scope="col">까닭</th>
                    <th scope="col">손익</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((one) => (
                    <tr key={`${one.openedAt}-${one.closedAt}`}>
                      <td>{stamp(one.openedAt)}</td>
                      <td className={one.side === 'buy' ? 'up' : 'down'}>{one.side === 'buy' ? '매수' : '매도'}</td>
                      <td>
                        <NumOrDash value={one.entryPrice} decimals={decimals} />
                      </td>
                      <td>
                        <NumOrDash value={one.exitPrice} decimals={decimals} />
                      </td>
                      <td>{reasonWord(one.reason ?? '') || '—'}</td>
                      <td className={toneOf(one.pl) || undefined}>{signedMoney(one.pl, currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  )
}

/** 판정하지 못한 조건이 결과에 미치는 것마다의 뒤 절. 앞의 둘은 그 규칙이나 단계가
 *  아예 서지 않는다는 뜻이라 경고로 적습니다. 모르는 값은 가장 약한 쪽(그 조건만
 *  거짓)으로 적습니다. */
const UNJUDGED_EFFECT: Record<string, { tail: string; warn: boolean; rank: number }> = {
  ruleNeverFires: { tail: '이 규칙은 한 번도 걸리지 않습니다', warn: true, rank: 0 },
  stepBlocked: { tail: '이 단계가 채워지지 않아 규칙이 여기서 멈춥니다', warn: true, rank: 1 },
  condFalse: { tail: '이 조건만 거짓으로 두고 나머지 조건으로 판정합니다', warn: false, rank: 2 },
}

/** 판정하지 못한 조건 줄은 이만큼까지 적고, 나머지는 한 줄로 셉니다. */
const UNJUDGED_SHOWN = 3

/** 판정하지 못한 조건을 **규칙의 단계마다 한 줄로** 적습니다. 같은 단계의 항목은
 *  「·」로 묶고, 규칙이 아예 안 걸리는 줄이 있으면 그 규칙의 다른 줄은 적지 않습니다 —
 *  규칙이 서지 않는데 단계 하나를 따로 말하면 덜 나쁜 일처럼 읽힙니다. */
function unjudgedLines(rows: readonly UnjudgedCondition[]): { text: string; warn: boolean }[] {
  const groups = new Map<string, { rule: string; step: number; effect: string; words: string[] }>()
  for (const row of rows) {
    const key = `${row.rule}|${row.step}`
    const group = groups.get(key) ?? { rule: row.rule, step: row.step, effect: row.effect, words: [] }
    const word = operandWord(row.operand) ?? '호가 항목'
    if (!group.words.includes(word)) group.words.push(word)
    groups.set(key, group)
  }
  const effectOf = (effect: string) => UNJUDGED_EFFECT[effect] ?? UNJUDGED_EFFECT.condFalse
  const silenced = new Set(
    [...groups.values()].filter((group) => group.effect === 'ruleNeverFires').map((group) => group.rule),
  )
  const ruleOrder = (rule: string) => {
    const at = RULE_KEYS.indexOf(rule as RuleKey)
    return at < 0 ? RULE_KEYS.length : at
  }
  const lines = [...groups.values()]
    .filter((group) => group.effect === 'ruleNeverFires' || !silenced.has(group.rule))
    .sort(
      (a, b) =>
        effectOf(a.effect).rank - effectOf(b.effect).rank ||
        ruleOrder(a.rule) - ruleOrder(b.rule) ||
        a.step - b.step,
    )
    .map((group) => {
      const effect = effectOf(group.effect)
      const rule = RULE_LABEL[group.rule as RuleKey] ?? '규칙'
      return {
        text: `${rule} ${group.step}단계 · ${group.words.join('·')} 조건은 지난 봉에 값이 없어 판정하지 않습니다 — ${effect.tail}`,
        warn: effect.warn,
      }
    })
  if (lines.length <= UNJUDGED_SHOWN) return lines
  const hidden = lines.slice(UNJUDGED_SHOWN)
  return [
    ...lines.slice(0, UNJUDGED_SHOWN),
    {
      text: `호가 조건 ${hidden.length}곳 더 — 같은 까닭으로 판정하지 않습니다`,
      warn: hidden.some((line) => line.warn),
    },
  ]
}

/** 가정 문장 — 답의 `assumptions` 를 줄마다 따로 적습니다. 지난 봉에는 호가가 없어
 *  종이 검증과 체결을 채우는 방식이 다르므로, 무엇을 어림했는지가 결과 곁에 늘 섭니다.
 *  만기 줄은 만기일이 셈한 봉의 끝 이전일 때만 섭니다 — 그 뒤의 만기는 이 결과에 닿지
 *  않습니다. */
/* 서버 가정 칸의 값마다 세우는 한 줄. */
const DAILY_ENTRY_WINDOW_LINE: Record<string, string> = {
  'next-session-open': '일봉은 신규 진입 시간 안에 낸다고 보고 셉니다 — 실제 실행은 그 시간 안 첫 체결에 냅니다',
}
const SESSION_END_FLAT_LINE: Record<string, string> = {
  'followed-sessions-only':
    '세션 끝 정리는 다음 세션이 자료에 있을 때만 셉니다 — 자료의 마지막 세션은 정리하지 않아 보유가 남을 수 있습니다',
  'not-applied-daily': '일봉에서는 세션 끝 정리를 셈하지 않습니다',
}
/* 표에 있는 값의 줄만 냅니다. 모르는 값이면 `null` 입니다. */
function lineOf(table: Record<string, string>, value: string | null | undefined): string | null {
  return value && Object.prototype.hasOwnProperty.call(table, value) ? table[value] : null
}
/* 서버가 까닭 글을 싣지 않았을 때 쓰는 글. 서버가 싣는 글과 같은 말입니다. */
const BUDGET_UNCHECKED_LINE = '계약당 증거금을 몰라 증거금 예산 검사를 하지 않습니다'

/* `entryWindow`·`sessionEndFlat`·`tickEval` 은 지금 설정에서 신규 진입 시간을 정했는지,
   세션 끝 정리를 켰는지, 틱으로 판정하는지입니다. 그 설정이 없는 전략에 그 가정 줄이
   서면 틀린 말이라, 답에 칸이 있어도 설정이 맞을 때만 적습니다. */
function Assumptions({
  answer,
  daily,
  entryWindow,
  sessionEndFlat,
  tickEval,
  currency,
}: {
  answer: BacktestAnswer
  daily: boolean
  entryWindow: boolean
  sessionEndFlat: boolean
  tickEval: boolean
  currency: string
}) {
  const said = answer.assumptions
  const fee = said.feePerContract ?? 0
  const slip = said.slippageTicks ?? 0
  const market = slip === 0 ? '시장가는 신호가 그대로' : `시장가는 신호가에서 ${slip}틱 불리하게`
  const lines = [
    `봉으로만 셈합니다 — 판정 규칙은 종이 검증과 같고, 체결은 봉 체결 모델(${answer.model})로 어림합니다`,
    `${market} · 지정가는 봉이 그 가격을 넘어설 때만(닿기만 하면 안 됨) · 봉 안은 시가 → 불리한 끝 → 유리한 끝 → 종가 순서 · 같은 봉에 손절과 익절이 함께 닿으면 손절 · 수수료 계약당 ${feeIn(fee, currency)}`,
  ]
  if (daily && said.dailyOrders) lines.push('일봉 신호는 다음 세션 첫 봉 시가에 냅니다')
  /* 신규 진입 시간을 정한 일봉 전략. 같은 일봉 이야기라 위 줄 바로 다음에 둡니다. */
  const windowLine = daily && entryWindow ? lineOf(DAILY_ENTRY_WINDOW_LINE, said.dailyEntryWindow) : null
  if (windowLine) lines.push(windowLine)
  const expiry = said.expiryBlock ? said.expiryBlock.split('-').map(Number) : null
  if (expiry && answer.bars.to !== null) {
    const [year, month, day] = expiry
    const lastDay = kstParts(answer.bars.to)
    const within =
      year < lastDay.year ||
      (year === lastDay.year && (month < lastDay.month || (month === lastDay.month && day <= lastDay.day)))
    if (within) lines.push(`${month}/${day} 만기일부터 새로 진입하지 않습니다`)
  }
  /* 그 전략의 설정에 따라 붙는 가정. 서버가 싣는 칸만 적고, 칸이 없거나 모르는 값이면
     적지 않습니다. */
  const sessionEndLine = sessionEndFlat ? lineOf(SESSION_END_FLAT_LINE, said.sessionEndFlat) : null
  if (sessionEndLine) lines.push(sessionEndLine)
  if (said.budgetUnchecked === true) lines.push(said.budgetUncheckedWhy || BUDGET_UNCHECKED_LINE)
  lines.push('그래서 손절·익절·지정가 체결은 실제 검증과 다를 수 있습니다')
  return (
    <div className="bt-assume">
      {/* 판정하지 못한 호가 조건이 맨 앞입니다 — 결과가 실제와 가장 크게 갈리는
          까닭이라, 다른 가정보다 먼저 읽혀야 합니다. */}
      {unjudgedLines(said.unjudged ?? []).map((line, index) => (
        <p key={`unjudged-${index}`} className={line.warn ? 'bt-warn' : undefined}>
          {line.text}
        </p>
      ))}
      {/* 틱으로 판정하는 전략을 봉 마감 값으로 셈했으면 그 차이를 맨 앞에 적습니다 —
          실제 실행은 봉이 끝나기 전에도 신호를 내므로 결과가 갈립니다. 서버는 어느
          전략이든 셈한 기준(`bar-close`)을 실으므로, 마감으로 판정하는 전략에는 차이가
          없어 적지 않습니다. */}
      {said.evalBasis === 'bar-close' && tickEval && (
        <p className="bt-warn">틱 판정 전략도 봉이 끝난 값으로 셉니다 — 봉 안에서 먼저 난 신호는 빠지거나 늦게 잡힙니다</p>
      )}
      {lines.map((line) => (
        <p key={line}>{line}</p>
      ))}
      {fee === 0 && <p className="bt-warn">수수료 0 이면 손익이 실제보다 큽니다</p>}
    </div>
  )
}
