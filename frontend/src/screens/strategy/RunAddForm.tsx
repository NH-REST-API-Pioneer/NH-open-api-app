import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { contractsOf, resolve } from '../../data/instruments'
import {
  codeOfVersion,
  productOfVersion,
  useStrategyCurrency,
  type StrategyVersion,
} from '../../data/strategyList'
import { sessionKeyOf, sessionLabelOf, sessionLinesFor, type Aux } from '../../data/strategyRules'
import { watchLine } from '../../data/ruleSummary'
import { patchVerify, addRun, savedOf, type OpenRequest } from '../../data/strategyStore'
import {
  FEE_ASSUMED,
  FUNDS_UNKNOWN,
  perOrderNote,
  perOrderOf,
  NO_CASH_DEFAULT,
  cashDefaultOf,
  optionSellWarning,
  type AccountMode,
} from '../../data/strategyRuns'
import { currencyCode, moneyDigits, moneyIn, moneyText } from '../../lib/number'
import { runAddWhy } from '../../data/strategyChecks'
import { RunKindBadge } from './runKind'
import { ASK_TEXT, type AskFixed, ENV_WAIT } from './strategyRunUtils'

/* 거래 추가 — 마지막에 **모의/실전 계좌·실제 계약·수량·청산 감시 방식**을
 * 다시 보여 주고 시작합니다.
 *
 * 계좌는 읽기만 합니다. 계좌번호·비밀번호를 새로 받는 자리를 만들지 않고
 * 설정에 있는 것을 씁니다. */
/** 고른 버전을 저장하는 중일 때의 까닭. 목록의 저장 잠금과 같은 말입니다. */
const SAVING_WHY = '저장하는 중입니다'

export function RunAddForm({
  rows,
  savingId,
  seed,
  why,
  ask,
  askable,
  onAsk,
  onBack,
  onCancel,
  onStarted,
}: {
  /** 고를 수 있는 전략. 목록과 같은 것을 씁니다. */
  rows: StrategyVersion[]
  /** 지금 서버에 저장하는 중인 버전 id. 고른 버전이 이것이면 시작을 잠급니다 — 그
   *  몇 초 동안 시작하면 서버가 아직 담지 않은 버전으로 실행을 세우게 됩니다. */
  savingId: string | null
  /** 목록에서 들고 온 전략·버전. */
  seed: OpenRequest | null
  /** 서버가 시작을 막은 까닭. **서버 문장 그대로**입니다 — 화면이 같은 검사를
   *  다시 하면 둘이 갈립니다. */
  why: string | null
  /** 확인 얼굴이 고정한 갈래·환경. `null` 이면 폼 얼굴입니다. **창은 하나**이고
   *  얼굴만 바뀝니다. */
  ask: AskFixed | null
  /** 지금 세울 수 있는 계좌 갈래. 모르면 `null` 이고 확인 얼굴로 안 넘어갑니다. */
  askable: AccountMode | null
  onAsk: () => void
  onBack: () => void
  onCancel: () => void
  onStarted: () => void
}) {
  const names = [...new Set(rows.map((row) => row.name))]
  const [strategy, setStrategy] = useState(seed?.strategy || (names[0] ?? ''))
  const versions = rows.filter((row) => row.name === strategy).map((row) => row.version)
  const [version, setVersion] = useState(seed?.version || (versions[0] ?? ''))
  /* 창이 새로 열리면 앞 창에서 서버가 막은 까닭을 지웁니다 — 남겨 두면 아직
     누르지도 않은 이번 시작이 막힌 것으로 읽힙니다. 그리기 전에 지워 옛 글이
     한 번도 비치지 않게 합니다. 폼과 확인 얼굴은 한 창이라 얼굴을 오갈 때는
     지우지 않습니다. */
  useLayoutEffect(() => {
    patchVerify({ addWhy: null })
  }, [])
  const [qty, setQty] = useState('1')
  const [fee, setFee] = useState('0')
  /* 실행 자금. **계좌의 돈이 아닙니다** — 이 실행의 손익과 묶인 증거금을 세는
     기준이고, 서버가 0 보다 큰 수를 요구합니다. 검증 탭과 **같은 서버 칸**
     (`cash`)이라 낱말도 같습니다 — 한 사실에 두 낱말을 두면 둘이 다른 값으로
     읽힙니다. */
  const [cash, setCash] = useState('50000000')
  /* 사용자가 자금 칸을 고쳤는지. 고친 값은 통화가 바뀌어도 덮지 않습니다. */
  const [cashTouched, setCashTouched] = useState(false)
  const [sending, setSending] = useState(false)
  /* 확인 얼굴의 첫 초점. **창이 이미 떠 있는 채로 얼굴만 바뀌므로** 창이
     잡아 주는 초점이 다시 돌지 않습니다 — 직접 옮기지 않으면 눌렸던 단추가
     사라진 자리에 초점이 남아 문서 맨 앞으로 튑니다. */
  const backRef = useRef<HTMLButtonElement>(null)
  const asking = ask !== null
  useEffect(() => {
    if (asking) backRef.current?.focus()
  }, [asking])

  const row = rows.find((item) => item.name === strategy && item.version === version)
    ?? rows.find((item) => item.name === strategy)
  /* 이 실행이 붙을 종목. **품목은 전략이 정합니다** — 그것을 바꾸면 다른
     전략입니다. 바꿀 수 있는 것은 **월물**뿐이고, 비워 두면 전략이 정한
     것(「근월 자동」이면 오늘의 근월)입니다. */
  const [month, setMonth] = useState('')
  const product = row ? productOfVersion(row) : null
  const months = useMemo(
    () => (product && row ? contractsOf(product, row.productKind) : []),
    [product, row],
  )
  /* 고른 월물이 지금 품목의 월물 목록에 없으면 비웁니다 — 다른 품목의 월물이 남으면
     그 달의 다른 종목으로 시작 요청이 나갑니다. 목록에 있는 값은 그대로 둡니다. */
  useEffect(() => {
    if (month && !months.some((item) => item.code === month)) setMonth('')
  }, [month, months])
  const code = month || (row ? codeOfVersion(row) : '')
  const instrument = code ? (resolve(code)?.name ?? code) : ''
  /* 세션도 그 전략의 시장을 따릅니다 — 해외 전략에 국내 세션을 세우면 고를 수
     없는 조합이 만들어집니다. */
  const market = row?.market ?? 'domestic'
  const sessions = sessionLinesFor(market)
  /* 이 실행의 통화 — 전략의 품목이 정합니다(해외는 품목마다 다릅니다). 자금·수수료 칸과
     확인창 금액이 이 통화이고, 자금 기본값도 이 통화로 섭니다(`cashDefaultOf`, 검증 추가
     창과 같은 표). 표에 없는 통화는 칸을 비우고, 사용자가 고친 값은 덮지 않습니다. */
  const currency = useStrategyCurrency(row ?? null)
  useEffect(() => {
    if (cashTouched) return
    const unit = currencyCode(currency)
    if (unit) setCash(cashDefaultOf(unit) ?? '')
  }, [currency, cashTouched])
  const unitCode = currencyCode(currency)
  const noCashDefault = cash === '' && unitCode !== '' && cashDefaultOf(unitCode) === null
  const unitTail = unitCode ? `(${unitCode === 'KRW' ? '원' : unitCode})` : ''
  /* 해외는 계약당 증거금을 미리 알 수 없어(거래소가 셈함) 자금과 견주지 않습니다 —
     그 사실을 실행 자금 줄 아래 한 줄로 말합니다. */
  const marginUnknown = market === 'overseas'
  /* 옵션을 **팔고 들어가는** 전략(국내·해외) — 손실이 실행 자금을 넘을 수 있어 승인 문장
     바로 위에 따로 알립니다(막지는 않음).
     판정과 글은 서버 규칙의 거울 하나입니다(`optionSellWarning` — 시장으로 글만 가름). */
  const optionSell = row ? optionSellWarning(market, row.productKind, savedOf(row.id)?.rules) : null
  /* 앱이 보는 청산 기준입니다. **담긴 설정이 답합니다** — 못 박아 두면 설정을
     고쳐도 확인창이 옛 값을 설명합니다. */
  const draft = row ? savedOf(row.id) : null
  /* 수량 기본값은 **그 버전 설정의 주문당**입니다. 창을 열 때, 전략·버전을 바꿀 때,
     담긴 설정이 늦게 도착했을 때 다시 정합니다. 같은 버전에서 사용자가 고친 값은
     그대로 둡니다 — 버전을 바꾸면 그 버전의 값으로 갑니다. */
  const perOrder = perOrderOf(draft?.aux)
  const qtyFor = useRef<string | null>(null)
  const qtyTouched = useRef(false)
  useEffect(() => {
    const id = row?.id ?? null
    if (qtyFor.current === id && qtyTouched.current) return
    qtyFor.current = id
    qtyTouched.current = false
    setQty(String(perOrder ?? 1))
  }, [row?.id, perOrder])
  /* 세션 기본값은 **그 전략·버전에 담긴 세션**입니다(검증 추가 창과 같은 규칙).
     창을 열 때, 전략·버전을 바꿀 때, 담긴 설정이 늦게 도착했을 때 다시 정하고, 그
     사이 사용자가 고른 값은 그대로 둡니다. */
  const savedKey = sessionKeyOf(market, draft?.aux.session)
  const [session, setSession] = useState<string>(savedKey)
  useEffect(() => {
    setSession(savedKey)
  }, [row?.id, savedKey])
  const watch = draft?.aux

  /* 해외 품목도 계좌 실행을 엽니다. 막는 거래소(서버가 정함)는 미리 막지 않고 시작한
     뒤 서버 문장을 그대로 적습니다 — 화면이 같은 표를 또 두면 둘이 갈립니다. 접속
     환경을 아직 확인하지 못했으면 어느 계좌로 나갈지 말할 수 없어 확인 얼굴로 넘어가지
     않습니다. */
  /* 세 칸의 판정. 틀린 칸은 붉은 테와 칸 아래 문장이 서고 시작이 막힙니다. */
  const bad = runAddWhy({ qty, cash, fee })
  const inputBad = bad.qty !== null || bad.cash !== null || bad.fee !== null
  /* 고른 버전을 저장하는 중인지. 고른 것은 바꾸지 않고 시작만 잠급니다 — 말없이
     다른 버전으로 바꾸면 고른 적 없는 전략이 시작됩니다. */
  const rowSaving = row !== undefined && row.id === savingId
  const blocked =
    !row || !draft
      ? '담긴 설정이 없어 시작할 수 없습니다'
      : rowSaving
        ? SAVING_WHY
        : code === ''
        ? '이 전략의 종목을 종목 목록에서 찾지 못했습니다'
        : askable === null
          ? ENV_WAIT
          : null

  async function start() {
    if (!row || !draft || sending || ask === null || rowSaving) return
    setSending(true)
    const ok = await addRun({
      id: `run-${Date.now()}`,
      versionId: row.id,
      draft,
      market,
      code,
      session,
      /* 판정을 지난 값만 여기 옵니다(`runAddWhy`) — 그대로 수로 바꿉니다. */
      qty: Number(qty),
      cash: Number(cash),
      feePerContract: Number(fee),
      /* 확인 얼굴이 고정한 갈래와 환경 — 창에 보인 그대로 보냅니다. */
      mode: ask.mode,
      environment: ask.environment,
      /* **확인창을 지났다는 표지.** 서버는 이것이 없으면 한 건도 안 냅니다.
         시각은 안 보냅니다 — 서버가 제 시계로 찍습니다. */
      approved: true,
    })
    setSending(false)
    if (ok) onStarted()
  }

  const pickStrategy = (name: string) => {
    /* 고른 것이 바뀌면 앞 시작 요청에 서버가 단 말은 이 고른 것의 답이 아닙니다. */
    patchVerify({ addWhy: null })
    setStrategy(name)
    const first = rows.find((item) => item.name === name)
    setVersion(first?.version ?? '')
    /* 전략을 바꾸면 골라 둔 월물은 앞 품목의 것입니다. */
    setMonth('')
  }

  const field = (label: string, node: React.ReactNode, why: string | null = null) => (
    <div key={label}>
      <label className="run-add-row">
        <span className="run-add-label">{label}</span>
        {node}
      </label>
      {/* 안 채운 칸(기본값 없는 통화의 자금)은 경고색, 틀린 값은 오류색입니다. */}
      {why !== null && <p className={`add-field-why${why === NO_CASH_DEFAULT ? ' is-missing' : ''}`}>{why}</p>}
    </div>
  )

  /* 확인 얼굴. **패널과 같은 줄들**을 쓰고 계좌 한 줄을 앞에 답니다 —
     둘이 갈리면 확인창이 패널과 다른 주문을 설명하게 됩니다. */
  if (ask !== null) {
    const text = ASK_TEXT[ask.mode]
    return (
      <div className="run-add">
        <div className="run-final">
          {/* 계좌 칸은 **배지**입니다. 굵은 글자로 두면 아래 문장의 굵은 글자와
              한 창에서 두 뜻이 됩니다 — 굵은 글자는 「실제 주문이 나간다」 한
              곳에만 씁니다. 검증의 시작 확인창과 같은 얼굴입니다. */}
          <div className="run-confirm-row">
            <span>계좌</span>
            <RunKindBadge kind={ask.mode} short />
          </div>
          {finalRows({ session, instrument, qty, cash, fee, watch, bad, currency, marginUnknown })}
        </div>
        {/* 해외 옵션 매도 — 승인 문장 바로 위 한 줄입니다. 막지 않고 알립니다. */}
        {optionSell && (
          <p className="run-option-sell">
            <span className="badge badge-warn">옵션 매도</span>
            {optionSell}
          </p>
        )}
        {/* **한 줄입니다.** 뒤에 한 문장을 더 달면 무거운 쪽이 둘로 갈려,
            읽는 사람이 어느 쪽이 이 창의 말인지 고르게 됩니다. */}
        {/* 실전 계좌 갈래에서는 굵은 조각만 경고색입니다 — 이 창에서 경고색은
            이 한 조각뿐입니다. */}
        <p className="run-approve">
          승인하면 <b className={ask.mode === 'real' ? 'run-approve-real' : undefined}>{text.approve}</b>
        </p>
        <div className="run-add-acts">
          <button ref={backRef} type="button" className="btn btn-quiet" onClick={onBack}>
            그만두기
          </button>
          {/* 서버가 시작을 막았으면(막는 거래소 등) 같은 것을 다시 보내도 같은 답이라
              승인 단추를 잠급니다. 그만두기로 돌아가 전략·월물을 바꾸면 풀립니다. */}
          <button
            type="button"
            className="btn btn-heavy"
            aria-disabled={sending || why !== null || rowSaving}
            title={why ?? (rowSaving ? SAVING_WHY : undefined)}
            onClick={() => !sending && why === null && !rowSaving && void start()}
          >
            {text.button}
          </button>
        </div>
        {/* 서버가 시작을 막은 문장(막는 거래소 등)은 오류색입니다. */}
        <p className={`run-hint run-start-why${why ? ' is-error' : ''}`}>{why ?? (rowSaving ? SAVING_WHY : '')}</p>
      </div>
    )
  }

  return (
    <div className="run-add">
      {field(
        '전략',
        <select
          className="control"
          value={strategy}
          onChange={(e) => pickStrategy(e.target.value)}
        >
          {names.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>,
      )}
      {field(
        '버전',
        <select className="control" value={version} onChange={(e) => {
            patchVerify({ addWhy: null })
            setVersion(e.target.value)
            /* 버전이 바뀌면 월물은 「전략이 정한 것」으로 — 버전마다 품목이 다를 수
               있습니다. */
            setMonth('')
          }}>
          {versions.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>,
      )}
      {/* 종목은 **품목이 정하고 월물만 고릅니다.** 품목 칸을 여기 두면 전략이
          말하는 종목과 다른 종목으로 도는 실행이 생깁니다. */}
      {field('종목', <span className="run-add-fixed">{instrument || '—'}</span>)}
      {field(
        '월물',
        <select
          className="control"
          value={month}
          aria-label="월물"
          onChange={(e) => {
            patchVerify({ addWhy: null })
            setMonth(e.target.value)
          }}
        >
          {/* 여기에 풀린 종목을 덧붙이지 않습니다 — 윈 줄의 「종목」이 지금 고른
              것이 무엇으로 풀리는지를 이미 보여 줍니다. 덧붙이면 특정 월물을 골랐을 때
              이 줄이 그 월물 이름을 달아, 「전략이 정한 것」이 아닌 것을 그렇게 말합니다. */}
          <option value="">전략이 정한 것</option>
          {months.map((item) => (
            <option key={item.code} value={item.code}>
              {item.label}
            </option>
          ))}
        </select>,
      )}
      {field(
        '세션',
        <select
          className="control"
          value={session}
          /* 고른 줄에서 키를 되찾습니다 — `e.target.value` 는 그냥 글자라
             그대로 담으면 서버가 못 읽는 값도 들어갑니다. */
          onChange={(e) => {
            const found = sessions.find((item) => item.key === e.target.value)
            if (found) setSession(found.key)
          }}
        >
          {sessions.map((item) => (
            <option key={item.key} value={item.key}>
              {item.label}
            </option>
          ))}
        </select>,
      )}
      {field(
        '주문당 수량',
        <input
          className={`control run-num${bad.qty !== null ? ' is-bad' : ''}`}
          value={qty}
          inputMode="numeric"
          aria-invalid={bad.qty !== null}
          onChange={(e) => {
            qtyTouched.current = true
            setQty(e.target.value)
          }}
        />,
        bad.qty,
      )}
      {/* 설정과 다르게 고쳤을 때만 — 틀린 값이면 위 오류 줄이 말합니다. */}
      {perOrder !== null && bad.qty === null && Number(qty) !== perOrder && (
        <p className="vrf-funds-dim">{perOrderNote(perOrder)}</p>
      )}
      {field(
        `실행 자금${unitTail}`,
        <input
          className={`control run-num${noCashDefault ? ' is-missing' : bad.cash !== null ? ' is-bad' : ''}`}
          value={moneyText(cash)}
          inputMode="numeric"
          aria-invalid={bad.cash !== null}
          onChange={(e) => {
            setCashTouched(true)
            setCash(moneyDigits(e.target.value))
          }}
        />,
        noCashDefault ? NO_CASH_DEFAULT : bad.cash,
      )}
      {field(
        `계약당 수수료${unitTail}`,
        <input
          className={`control run-num${bad.fee !== null ? ' is-bad' : ''}`}
          value={moneyText(fee)}
          inputMode="numeric"
          aria-invalid={bad.fee !== null}
          onChange={(e) => setFee(moneyDigits(e.target.value))}
        />,
        bad.fee,
      )}

      <div className="run-final">
        <p className="run-final-title">시작하면 이렇게 나갑니다</p>
        {finalRows({ session, instrument, qty, cash, fee, watch, bad, currency, marginUnknown })}
      </div>

      <div className="run-add-acts">
        <button type="button" className="btn btn-quiet" onClick={onCancel}>
          그만두기
        </button>
        {/* 누르면 곧바로 나가지 않고 **확인 얼굴이 한 번 섭니다.** 그 얼굴을
            지난 표지가 없으면 서버가 한 건도 내지 않습니다. */}
        <button
          type="button"
          className="btn btn-primary"
          aria-disabled={blocked !== null || inputBad}
          aria-describedby={blocked === null ? undefined : 'run-start-why'}
          onClick={() => blocked === null && !inputBad && onAsk()}
        >
          거래 시작
        </button>
      </div>
      <p id="run-start-why" className={`run-hint run-start-why${blocked === null && why ? ' is-error' : ''}`}>
        {blocked ?? why ?? ''}
      </p>
    </div>
  )
}

/** 「이렇게 나갑니다」의 줄들. **패널과 확인창이 같은 것을 씁니다** — 둘이
 *  갈리면 확인창이 패널과 다른 주문을 설명하게 됩니다. */
function finalRows({
  session,
  instrument,
  qty,
  cash,
  fee,
  watch,
  bad,
  currency,
  marginUnknown,
}: {
  session: string
  instrument: string
  qty: string
  cash: string
  fee: string
  watch: Partial<Aux> | undefined
  /** 금액의 통화. 그 전략 품목의 것입니다. */
  currency: string
  /** 계약당 증거금을 몰라 자금과 견주지 않는 실행(해외)인지. */
  marginUnknown: boolean
  /** 칸 판정(`runAddWhy`). 틀린 칸의 값은 「—」로 섭니다 — 틀린 값을 되묻지 않습니다. */
  bad: ReturnType<typeof runAddWhy>
}) {
  return (
    <>
      <div className="run-confirm-row">
        <span>실제 계약</span>
        <b>{instrument || <span className="dead">—</span>}</b>
      </div>
      <div className="run-confirm-row">
        <span>세션</span>
        <b>{sessionLabelOf(session)}</b>
      </div>
      <div className="run-confirm-row">
        <span>수량</span>
        <b>{bad.qty === null ? `주문당 ${qty}계약` : '—'}</b>
      </div>
      {/* 손절·익절은 **담긴 설정**입니다. 못 박아 두면 설정을 고쳐도 확인창이
          옛 값을 설명합니다. **한 줄입니다** — 셋은 「이 실행이 어떻게 빠져
          나오나」 하나를 말하는 값이라, 줄로 나누면 나란히 선 다른 칸들과
          같은 무게가 됩니다. 앱이 보는 값이라 「앱 감시」를 함께 적습니다:
          앱이 꺼지면 이쪽은 멈춥니다. */}
      <div className="run-confirm-row">
        <span>청산 감시</span>
        <b>
          {watchLine(watch)} · 앱 감시
        </b>
      </div>
      {/* 계좌의 돈이 아니라 **이 실행의 장부 기준**입니다. 손익과 묶인
          증거금을 이 값으로 셉니다 — 적어 놓고 안 보여 주면 무엇으로 세는지
          모르는 채 시작하게 됩니다. */}
      <div className="run-confirm-row">
        <span>실행 자금</span>
        <b>{bad.cash === null ? moneyIn(Number(cash), currency) : '—'}</b>
      </div>
      {marginUnknown && <p className="vrf-funds-dim">{FUNDS_UNKNOWN}</p>}
      <div className="run-confirm-row">
        <span title={FEE_ASSUMED}>
          수수료<span className="fee-assumed"> (가정)</span>
        </span>
        <b>{bad.fee === null ? `계약당 ${moneyIn(Number(fee), currency)}` : '—'}</b>
      </div>
    </>
  )
}