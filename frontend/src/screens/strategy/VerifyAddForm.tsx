import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { contractsOf, resolve } from '../../data/instruments'
import {
  NO_CASH_DEFAULT,
  cashDefaultOf,
  perOrderNote,
  perOrderOf,
  fundsVerdict,
  type FundsVerdict,
} from '../../data/strategyRuns'
import {
  codeOfVersion,
  productOfVersion,
  useStrategyCurrency,
  type StrategyVersion,
} from '../../data/strategyList'
import { sessionKeyOf, sessionLabelOf, sessionLinesFor } from '../../data/strategyRules'
import { watchLine } from '../../data/ruleSummary'
import { useProductInfo } from '../../data/productInfo'
import { addRun, patchVerify, savedOf, type OpenRequest } from '../../data/strategyStore'
import { currencyCode, moneyDigits, moneyIn, moneyText } from '../../lib/number'
import { runAddWhy } from '../../data/strategyChecks'
import { RunKindBadge } from './runKind'
import { FundsNote } from './strategyVerifyUtils'

/* 검증 추가 — 전략·버전 → 종목·월물·세션 → 수량·한도 → 실행 자금·체결 가정
 * 순서입니다. 추가한다고 이미 도는 검증을 건드리지 않습니다. */
/** 고른 버전을 저장하는 중일 때의 까닭. 목록의 저장 잠금과 같은 말입니다. */
const SAVING_WHY = '저장하는 중입니다'

export function VerifyAddForm({
  rows,
  savingId,
  seed,
  why,
  onStarted,
  onCancel,
}: {
  /** 고를 수 있는 전략. **목록과 같은 것**을 씁니다 — 새로 만든 전략이 여기
   *  안 보이면 만든 것을 검증할 길이 없습니다. */
  rows: StrategyVersion[]
  /** 지금 서버에 저장하는 중인 버전 id. 고른 버전이 이것이면 시작을 잠급니다 — 그
   *  몇 초 동안 시작하면 서버가 아직 담지 않은 버전으로 실행을 세우게 됩니다. */
  savingId: string | null
  /** 목록에서 들고 온 전략·버전. 없으면 첫 줄로 시작합니다. */
  seed: OpenRequest | null
  /** 서버가 시작을 막은 까닭. **서버 문장 그대로**입니다 — 화면이 같은 검사를
   *  다시 하면 둘이 갈립니다. */
  why: string | null
  onCancel: () => void
  onStarted: () => void
}) {
  const names = [...new Set(rows.map((row) => row.name))]
  const [strategy, setStrategy] = useState(seed?.strategy || (names[0] ?? ''))
  const versions = rows.filter((row) => row.name === strategy).map((row) => row.version)
  const [version, setVersion] = useState(seed?.version || (versions[0] ?? ''))
  /* 창이 새로 열리면 앞 창에서 서버가 막은 까닭을 지웁니다 — 남겨 두면 아직
     누르지도 않은 이번 시작이 막힌 것으로 읽힙니다. 그리기 전에 지워 옛 글이
     한 번도 비치지 않게 합니다. */
  useLayoutEffect(() => {
    patchVerify({ addWhy: null })
  }, [])
  /* 세션과 통화는 **고른 전략의 시장**을 따릅니다 — 해외 전략에 국내 세션을
     세우면 고를 수 없는 조합이 만들어집니다. */
  const row = rows.find((item) => item.name === strategy && item.version === version)
    ?? rows.find((item) => item.name === strategy)
  const market = row?.market ?? 'domestic'
  /* 금액의 통화. 해외인데 담긴 코드가 없으면 품목정보의 통화입니다. */
  const currency = useStrategyCurrency(row ?? null)
  /* 세션은 **키로 다룹니다** — 서버에 보내는 것이 키이고, 화면에 세우는 것은
     글자입니다. 둘을 한 값으로 두면 보낼 때 글자에서 키를 되찾아야 합니다. */
  const sessions = sessionLinesFor(market)
  const [qty, setQty] = useState('1')
  const [cash, setCash] = useState('50000000')
  /* 사용자가 자금 칸을 고쳤는지. 고친 값은 통화가 바뀌어도 덮지 않습니다. */
  const [cashTouched, setCashTouched] = useState(false)
  /* 실행 자금의 기본값은 **그 전략의 통화로** 섭니다(`cashDefaultOf`) — 원 기본값이
     달러 칸에 그대로 서면 5천만 달러로 읽힙니다. 표에 없는 통화는 칸을 비웁니다. 통화를
     아직 모르면(해외 품목정보를 받는 중) 두고, 사용자가 고친 값은 덮지 않습니다. */
  useEffect(() => {
    if (cashTouched) return
    const code = currencyCode(currency)
    if (code) setCash(cashDefaultOf(code) ?? '')
  }, [currency, cashTouched])
  const cashCode = currencyCode(currency)
  const noCashDefault = cash === '' && cashCode !== '' && cashDefaultOf(cashCode) === null
  const [fee, setFee] = useState('0')
  const [sending, setSending] = useState(false)

  /* 이 실행이 붙을 종목. **품목은 전략이 정합니다** — 그것을 바꾸면 다른
     전략입니다. 바꿀 수 있는 것은 **월물**뿐이고, 비워 두면 전략이 정한
     것(「근월 자동」이면 오늘의 근월)입니다: 같은 전략을 다른 달로 돌려 보는
     자리입니다. */
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
  /* 시작할 때 물고 가는 설정은 **담긴 것**입니다 — 안 담긴 초안으로 시작하면
     새로고침 뒤 실행과 버전의 설정이 갈립니다. */
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
  /* 세션 기본값은 **그 전략·버전에 담긴 세션**입니다. 창을 열 때, 전략·버전을
     바꿀 때, 담긴 설정이 늦게 도착했을 때 다시 정합니다 — 그 사이 사용자가 고른
     값은 그대로 둡니다. 담긴 세션이 그 시장 목록에 없으면 시장의 첫째입니다. */
  const savedSession = draft?.aux.session ?? ''
  const savedKey = sessionKeyOf(market, savedSession)
  const [session, setSession] = useState<string>(savedKey)
  useEffect(() => {
    setSession(savedKey)
  }, [row?.id, savedKey])
  /* 전략과 다른 세션으로 돌리는 것은 막지 않고 한 줄로 알립니다. 담긴 세션이 없는
     버전에는 견줄 것이 없어 안 섭니다. */
  const savedLabel = sessions.find((item) => item.label === savedSession)?.label ?? ''
  const sessionNote =
    savedLabel && session !== savedKey
      ? `전략은 ${savedLabel} — 이 실행만 ${sessionLabelOf(session)}으로 돕니다`
      : ''

  async function start() {
    if (!row || !draft || sending || rowSaving) return
    setSending(true)
    const ok = await addRun({
      id: `run-${Date.now()}`,
      versionId: row.id,
      draft,
      market,
      code,
      /* **허브 맥락 키를 보냅니다**(`domestic-day`). 서버가 실행을 그 키로
         담고 방송의 줄도 그 키로 옵니다 — 화면이 문구로 보내면 서버가 한 번
         더 옮겨야 하고, 그 옮기는 자리가 곧 어긋나는 자리입니다. */
      session,
      /* 판정을 지난 값만 여기 옵니다(`runAddWhy`) — 그대로 수로 바꿉니다. */
      qty: Number(qty),
      cash: Number(cash),
      feePerContract: Number(fee),
      /* **이 화면은 종이 장부뿐입니다.** 계좌로 나가는 실행은 진행 화면이
         세우고, 그쪽은 확인창을 지나야 합니다. 여기서 고를 수 있는 자리를
         두지 않는 것이 「여기서 나가는 주문은 없다」를 지키는 길입니다. */
      mode: 'paper',
      approved: false,
    })
    setSending(false)
    if (ok) onStarted()
  }

  /* 시장이 바뀌면 세션도 그 시장의 것으로. 남겨 두면 해외 전략에 「국내 주간」이
     붙은 채 검증이 시작됩니다. */
  const pickStrategy = (name: string) => {
    setStrategy(name)
    const first = rows.find((item) => item.name === name)
    setVersion(first?.version ?? '')
    /* 전략을 바꾸면 골라 둔 월물은 앞 품목의 것입니다 — 남겨 두면 없는
       조합이 섭니다. */
    setMonth('')
  }

  /* 세 칸의 판정 — 진행 화면의 폼과 같은 함수입니다. */
  const bad = runAddWhy({ qty, cash, fee })
  const inputBad = bad.qty !== null || bad.cash !== null || bad.fee !== null
  /* 고른 버전을 저장하는 중인지. 고른 것은 바꾸지 않고 시작만 잠급니다 — 말없이
     다른 버전으로 바꾸면 고른 적 없는 전략이 시작됩니다. */
  const rowSaving = row !== undefined && row.id === savingId
  /* 칸 이름의 단위. 통화를 모르면 괄호를 달지 않습니다. */
  const unitCode = currencyCode(currency)
  const unitTail = unitCode ? `(${unitCode === 'KRW' ? '원' : unitCode})` : ''

  /* 자금과 증거금. **계약당 값은 일반주문 폼의 개시증거금과 같은 곳**(품목정보)에서
     받습니다. 국내 선물만 그 값이 있고, 해외·옵션·스프레드와 품목정보를 아직 못
     받은 때는 「모름」입니다. 칸 값이 틀리면 견주지 않습니다. */
  const futuresHere = market === 'domestic' && row?.productKind === 'futures'
  const info = useProductInfo(futuresHere ? code : '')
  const funds: FundsVerdict | null =
    bad.qty !== null || bad.cash !== null
      ? null
      : futuresHere && info.status === 'ready' && info.row
        ? fundsVerdict(info.row.contractInitialMargin, Number(qty), Number(cash), currency)
        : { kind: 'unknown' }

  const field = (label: string, node: React.ReactNode, why: string | null = null) => (
    <div key={label}>
      <label className="vrf-add-row">
        <span className="vrf-add-label">{label}</span>
        {node}
      </label>
      {/* 안 채운 칸(기본값 없는 통화의 자금)은 경고색, 틀린 값은 오류색입니다. */}
      {why !== null && <p className={`add-field-why${why === NO_CASH_DEFAULT ? ' is-missing' : ''}`}>{why}</p>}
    </div>
  )

  return (
    <div className="vrf-add">
      {field(
        '전략',
        <select
          className="control"
          value={strategy}
          /* 전략을 바꾸면 버전·세션도 그 전략의 것으로 갈아 끼웁니다 — 안 그러면
             없는 조합(다른 전략의 버전, 다른 시장의 세션)이 남습니다. */
          onChange={(e) => pickStrategy(e.target.value)}
        >
          {names.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>,
      )}
      {field(
        '버전',
        <select
          className="control"
          value={version}
          onChange={(e) => {
            setVersion(e.target.value)
            /* 버전이 바뀌면 월물은 「전략이 정한 것」으로 — 버전마다 품목이 다를 수
               있습니다. */
            setMonth('')
          }}
        >
          {versions.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>,
      )}
      {/* 종목은 **품목이 정하고 월물만 고릅니다.** 품목 칸을 여기 두면 전략이
          말하는 종목과 다른 종목으로 도는 실행이 생깁니다. */}
      {field('종목', <span className="vrf-add-fixed">{instrument || '—'}</span>)}
      {field(
        '월물',
        <select
          className="control"
          value={month}
          aria-label="월물"
          onChange={(e) => setMonth(e.target.value)}
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
          /* 고른 줄에서 키를 되찾습니다. `e.target.value` 는 그냥 글자라 그대로
             담으면 목록에 없는 값도 들어가고, 그 값은 서버가 못 읽습니다. */
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
      {sessionNote && <p className="vrf-session-note">{sessionNote}</p>}
      {field(
        '주문당 수량',
        <input
          className={`control vrf-num${bad.qty !== null ? ' is-bad' : ''}`}
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
          className={`control vrf-num${noCashDefault ? ' is-missing' : bad.cash !== null ? ' is-bad' : ''}`}
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
      {/* 수수료를 0 으로 두면 체결 품질과 순손익이 비용 없는 수가 됩니다.
          기본은 0 이고, 아는 값이 있으면 여기 적습니다. */}
      {field(
        `계약당 수수료${unitTail}`,
        <input
          className={`control vrf-num${bad.fee !== null ? ' is-bad' : ''}`}
          value={moneyText(fee)}
          inputMode="numeric"
          aria-invalid={bad.fee !== null}
          onChange={(e) => setFee(moneyDigits(e.target.value))}
        />,
        bad.fee,
      )}

      {/* 시작하면 무엇이 서는지. 되돌릴 수 없는 자리는 아니지만, 무엇으로
          도는지는 누르기 전에 보여야 합니다(확인창). */}
      <div className="run-final">
        <p className="run-final-title">시작하면 이렇게 돕니다</p>
        {/* 계좌 칸은 **진행의 승인창과 같은 갈래 배지**입니다 — 같은 구조의 두
            시작 확인창이 갈래를 다른 얼굴로 보이면 다른 것을 묻는 것으로
            읽힙니다. 「(가상 장부)」는 이 실행이 무엇으로 도는지 밝히는 말이라
            배지 뒤에 한 급 낮춰 남깁니다. */}
        <div className="run-confirm-row">
          <span>계좌</span>
          <div className="run-kind-value">
            <RunKindBadge kind="paper" short />
            <span className="run-kind-note">(가상 장부)</span>
          </div>
        </div>
        <div className="run-confirm-row">
          <span>실제 계약</span>
          <b>{instrument || '—'}</b>
        </div>
        <div className="run-confirm-row">
          <span>세션</span>
          <b>{sessionLabelOf(session)}</b>
        </div>
        <div className="run-confirm-row">
          <span>수량</span>
          <b>{bad.qty === null ? `주문당 ${qty}계약` : '—'}</b>
        </div>
        {/* 이 실행의 장부가 얼마로 시작하는지. **손익과 증거금이 전부 이
            값에서 나옵니다** — 적어 놓고 안 보여 주면 무엇으로 도는지 모르는
            채 시작하게 됩니다. */}
        <div className="run-confirm-row">
          <span>실행 자금</span>
          <b>{bad.cash === null ? moneyIn(Number(cash), currency) : '—'}</b>
        </div>
        {funds && <FundsNote verdict={funds} qty={Number(qty)} currency={currency} />}
        <div className="run-confirm-row">
          <span>청산 감시</span>
          <b>
            {watchLine(draft?.aux)} · 앱 감시
          </b>
        </div>
        <div className="run-confirm-row">
          <span>수수료</span>
          <b>{bad.fee === null ? `계약당 ${moneyIn(Number(fee), currency)}` : '—'}</b>
        </div>
      </div>
      <p className="vrf-hint">
        실행마다 장부가 따로입니다 — 같은 종목을 여러 전략이 검증해도 서로의 체결을 쓰지 않습니다
      </p>
      <div className="vrf-add-acts">
        {/* 「취소」는 주문 취소와 겹칩니다. 창을 물러나는 낱말은 앱 전체에서
            「그만두기」입니다. */}
        <button type="button" className="btn btn-quiet" onClick={onCancel}>
          그만두기
        </button>
        <button
          type="button"
          className="btn btn-primary"
          aria-disabled={!row || sending || inputBad || rowSaving}
          aria-describedby="vrf-start-why"
          onClick={() => !inputBad && !rowSaving && void start()}
        >
          검증 시작
        </button>
      </div>
      {/* 서버가 막은 까닭이 여기 섭니다 — 시작 검사는 서버가 하고,
          화면은 그 문장을 옮기지 않고 그대로 세웁니다. */}
      <p id="vrf-start-why" className="vrf-hint vrf-start-why">
        {rowSaving ? SAVING_WHY : (why ?? (row ? '' : '고를 전략이 없습니다'))}
      </p>
    </div>
  )
}