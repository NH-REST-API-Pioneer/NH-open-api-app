import { Fragment, useEffect, useMemo, useRef, type ReactNode } from 'react'
import { Count, Num, fracWidth } from '../../lib/number'
import type { ChainLeg, ChainRow } from '../../lib/types'
import {
  BAR_COLUMN_MAX,
  CHAIN_FIELDS,
  STRIKE_MIN_WIDTH,
  type FieldDef,
  type FieldKey,
  type Preset,
} from './chainFields'

/* 옵션 체인.
 *
 * ATM을 화면 가운데 두고 엽니다. 행사가가 수십 개인데 위에서부터 로드하면
 * 정작 볼 구간이 화면 밖입니다.
 *
 * **다른 표와 달리 행 사이에 선을 긋지 않습니다.** 여기는 행을 가르는 층이
 * 이미 셋입니다 — 가운데 행사가 열, 내가격 구간의 음영, 마우스가 얹힌 행.
 * 그 위에 가로선까지 더하면 표가 격자가 되고, 900px 넘는 가로선이 세 층
 * 사이의 대비를 눌러 오히려 어느 행인지 찾기 어려워집니다.
 */

export type ChainSide = 'both' | 'call' | 'put'

interface Props {
  rows: ChainRow[]
  preset: Preset
  side: ChainSide
  /** 이 품목 종목들의 가격 소수 자릿수 */
  decimals: number
  /** 첫 답이 왔는지. 행사가 축까지 서버가 주므로 **답이 오기 전에는 표가
   *  없습니다** — 그 자리에 「받는 중」 한 줄이 섭니다. */
  loaded: boolean
  /** 어느 체인인지(품목·만기·세션). 이것이 바뀌면 등가격을 가운데로 엽니다. */
  chainKey: string
  /** 마지막 물음이 실패했으면 그 까닭. 받아 둔 표가 있으면 표는 그대로 서고 한
   *  줄이 붙고, 없으면 그 줄이 표 자리에 섭니다. 거절은 눌러도 같은 답이라
   *  단추를 안 세웁니다. */
  failure?: 'retry' | 'rejected' | 'paper' | null
  onRetry?: () => void
  /** 국내 야간 답인지. 야간은 시세가 없어 전일종가·미결제만 값이고 나머지 칸이
   *  빕니다 — 표 머리에 그 사실을 한 마디로 답니다. */
  night?: boolean
  /** 기초 선물 현재가. 콜·풋 구간을 가르는 자리에 배지로 섭니다. **모르면
   *  `null`** — 야간·해외에는 안 오고, 그때는 배지·내가격 음영을 안 그립니다. */
  futuresPrice: number | null
  /** 등가격 행사가. 국내는 기초 선물에 가장 가까운 행사가, 해외는 서버 표시입니다.
   *  모르면 `null` 이고 가운데 줄 표시가 없습니다. */
  atm: number | null
  strikeDecimals: number
  /** 지금 고른 줄의 **종목코드**. 화면에 적힌 글자로 견주지 않습니다 — 행사가를
   *  자리 수에 맞춰 적는 순간 서로 다른 행사가가 같은 글자가 됩니다. */
  selectedCode: string | null
  onSelect: (pick: ChainPick) => void
  onOpen: (pick: ChainPick) => void
}

/** 체인에서 고른 것. **계약 하나를 통째로 넘깁니다** — 코드가 신원이고 콜풋·행사가는
 *  체인이 준 원본 값입니다. 화면에 적힌 글자를 되읽어 숫자를 되찾으면, 자리 수에
 *  맞춰 반올림된 글자가 원래 행사가가 아닌 값으로 돌아옵니다. */
export interface ChainPick {
  code: string
  side: 'call' | 'put'
  strike: number
}

function fieldDecimals(def: FieldDef, priceDecimals: number): number {
  return def.decimals === 'price' ? priceDecimals : def.decimals
}

function renderValue(def: FieldDef, leg: ChainLeg, priceDecimals: number): ReactNode {
  const value = def.value(leg)
  // 없는 칸은 비웁니다 — 「—」를 세우면 열 줄에 같은 글자가 서서 값처럼 읽힙니다.
  if (value === null) return null
  // 흐림은 건수 칸(거래량·미결제)의 0 에만 — 「그 행사가에 일어난 일이 없다」라
  // 볼 것이 없고, 같은 0 이 열 줄 반복되면 그 열이 죽어 보이는 것이 맞습니다.
  // 값 칸의 0(등락 0.00·값 0)은 「그만큼이다」라 본문색입니다(`toneOf` 와 같은 규칙).
  const dead = def.count === true && value === 0
  const body = def.count ? (
    <Count value={value} signed={def.signed} />
  ) : (
    <Num
      value={value}
      decimals={fieldDecimals(def, priceDecimals)}
      signed={def.signed}
      toned={def.toned}
      suffix={def.suffix}
    />
  )
  // 매수·매도처럼 방향이 고정된 값은 열 머리의 글자가 두 번째 단서입니다.
  if (def.fixedTone) return <span className={def.fixedTone}>{body}</span>
  return dead ? <span className="dead">{body}</span> : body
}

export function OptionChain({
  rows,
  preset,
  side,
  decimals,
  loaded,
  chainKey,
  failure = null,
  onRetry,
  night = false,
  futuresPrice,
  atm,
  strikeDecimals,
  selectedCode,
  onSelect,
  onOpen,
}: Props) {
  const atmRef = useRef<HTMLTableRowElement>(null)
  const pickedRef = useRef<HTMLTableRowElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  /* 볼 구간이 화면 밖에 있으면 표를 여는 의미가 없습니다.
   * 가로도 가운데로 엽니다 — 열이 넘칠 때 왼쪽 끝에서 시작하면 풋 쪽 끝 열만
   * 잘려서, 같은 행사가의 콜과 풋을 나란히 비교한다는 이 표의 이유가 깨집니다.
   * 가운데로 열면 양쪽이 같은 만큼 잘려 대칭이 남습니다. */
  /* **답이 5초마다 갈아 끼워져도 안 움직입니다.** 값이 바뀔 때마다 가운데로 되돌리면
     사용자가 내려 보던 자리를 잃습니다 — 여는 때(묶음·콜풋·체인이 바뀔 때, 그리고 그
     체인의 첫 답이 왔을 때)만입니다. 등가격이 옮겨 가는 것만으로는 안 움직입니다 —
     배지 줄이 표 안에서 움직일 뿐입니다. */
  /* **고른 계약이 있으면 그 줄을 엽니다.** 등가격은 「아직 안 골랐을 때 어디를
     보여 줄까」에 대한 답이라, 이미 고른 계약이 있으면 그 자리가 볼 자리입니다 —
     종목코드로 열고 들어온 옵션이 표의 다른 쪽 끝에 있으면, 표를 열어 놓고도
     자기가 고른 줄을 찾아 훑어야 합니다.

     **자리는 직접 셉니다.** `scrollIntoView({block:'center'})` 는 고정된 머리글을
     볼 자리로 치지 않아, 머리 높이만큼 위로 치우친 자리에 줄이 섭니다 — 머리글
     아래 남는 칸의 한가운데가 사용자가 「가운데」로 보는 자리입니다. */
  useEffect(() => {
    const box = scrollRef.current
    if (!box) return
    /* 코드가 앉힌 자리. 사용자가 손으로 굴렸는지 가리는 데 씁니다. */
    let ours = -1
    let watching = true
    /* 마지막으로 앉힐 때의 판 높이. **이 값이 다시 앉히기를 멈춥니다** — 앉히면서
       읽은 높이를 적어 두고, 높이가 그대로면 다시 앉히지 않습니다. 크기 관찰자가
       제가 일으킨 변화로 다시 불려 끝없이 도는 것을 막는 자리입니다. */
    let seated = -1
    const seat = () => {
      const row = pickedRef.current ?? atmRef.current
      if (!row) return
      const head = box.querySelector('thead')
      const headHeight = head ? head.getBoundingClientRect().height : 0
      const rowBox = row.getBoundingClientRect()
      const boxBox = box.getBoundingClientRect()
      const middle = boxBox.top + headHeight + (boxBox.height - headHeight - rowBox.height) / 2
      box.scrollTop += rowBox.top - middle
      ours = box.scrollTop
      seated = box.clientHeight
      /* 가로도 가운데입니다 — 열이 넘칠 때 왼쪽 끝에서 시작하면 풋 쪽 끝 열만
         잘려, 같은 행사가의 콜과 풋을 나란히 본다는 이 표의 까닭이 깨집니다. */
      box.scrollLeft = (box.scrollWidth - box.clientWidth) / 2
    }
    seat()
    /* **판은 첫 그림 뒤에 커집니다.** 카드 높이가 그때 정해져, 처음 잡은 자리는
       한참 위로 치우쳐 남습니다 — 크기가 바뀌면 다시 앉힙니다. 사용자가 손으로
       굴린 뒤에는 그만둡니다: 보던 자리를 빼앗지 않습니다. */
    const onScroll = () => {
      if (Math.abs(box.scrollTop - ours) > 1) watching = false
    }
    const watcher = new ResizeObserver(() => {
      if (watching && box.clientHeight !== seated) seat()
    })
    watcher.observe(box)
    box.addEventListener('scroll', onScroll)
    return () => {
      watcher.disconnect()
      box.removeEventListener('scroll', onScroll)
    }
  }, [preset.id, side, chainKey, loaded])

  const showCall = side !== 'put'
  const showPut = side !== 'call'
  const fields = preset.fields
  const columnCount = fields.length * (showCall && showPut ? 2 : 1) + 1

  /* 막대는 열마다 그 열의 최댓값을 기준으로 그립니다. 거래량 최댓값으로
     미결제를 나누면 미결제 막대가 전부 꽉 차서 분포가 사라집니다 —
     두 값은 자릿수가 달라 같은 자로 잴 수 없습니다. */
  const barMax = useMemo(() => {
    const out = new Map<FieldKey, number>()
    for (const key of preset.fields) {
      const def = CHAIN_FIELDS[key] as FieldDef
      if (!def.bar) continue
      out.set(
        key,
        Math.max(
          ...rows.flatMap((row) => [def.value(row.call) ?? 0, def.value(row.put) ?? 0]),
          1,
        ),
      )
    }
    return out
  }, [preset, rows])

  // 콜 쪽은 행사가에서 바깥으로 나가는 순서라 열 정의를 뒤집어 그립니다.
  const callFields = [...fields].reverse()

  /* 값 열의 폭. 고정 폭은 세 자리 값 기준으로 잰 것이라, **네 자리 값(깊은
     내가격 옵션 4,319.50)** 이 오면 잘립니다. 그래서 값 열은 이 답에서 가장 긴
     글자 수로 다시 잽니다 — 표 폭은 답마다 조금 다를 수 있지만 잘린 값보다 낫습니다.
     숫자는 같은 폭 글꼴이라 글자 수로 재도 어긋나지 않습니다. */
  const priceWidth = useMemo(() => {
    let chars = 0
    for (const key of preset.fields) {
      const def = CHAIN_FIELDS[key] as FieldDef
      if (def.decimals !== 'price') continue
      for (const row of rows) {
        for (const leg of [row.call, row.put]) {
          const value = def.value(leg)
          if (value === null) continue
          const text = Math.abs(value).toLocaleString('ko-KR', {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
          })
          chars = Math.max(chars, text.length + (def.signed ? 1 : 0))
        }
      }
    }
    return chars * 8 + 12
  }, [rows, preset, decimals])
  const widthOf = (def: FieldDef) =>
    def.decimals === 'price' ? Math.max(def.minWidth, priceWidth) : def.minWidth

  // 열이 최소폭 합보다 좁아지면 가로로 스크롤합니다. 행사가 열은 남습니다.
  const sides = showCall && showPut ? 2 : 1
  const oneSide = (grown: boolean) =>
    fields.reduce((sum, key) => {
      const def = CHAIN_FIELDS[key] as FieldDef
      return sum + (grown && def.bar ? BAR_COLUMN_MAX : widthOf(def))
    }, 0)
  const tableMinWidth = oneSide(false) * sides + STRIKE_MIN_WIDTH
  // 넓어지면 미결제·거래량 열만 늘어나고, 그마저 상한에 닿으면 멈춥니다.
  const tableMaxWidth = oneSide(true) * sides + STRIKE_MIN_WIDTH

  /* 기초 선물 배지가 설 자리 — 그 값 이하인 첫 행사가 행의 **앞**입니다. 값이
     행사가 전부보다 낮으면 그런 행이 없으므로 마지막 행 **뒤**(`rows.length`)에
     섭니다 — 전부보다 높을 때 첫 행 앞에 서는 것과 같은 자리입니다. 거래소가
     주는 행사가 목록이 그 값을 사이에 둔다는 보장이 없어, 자리를 못 찾으면
     배지가 아예 사라지고 콜·풋 구간을 가르는 표시가 표에서 없어집니다.
     값을 모르면 자리도 없습니다. */
  const markIndex = (() => {
    if (futuresPrice === null) return -1
    const at = rows.findIndex((row) => row.strike <= futuresPrice)
    return at === -1 ? rows.length : at
  })()
  const markRow = futuresPrice !== null && (
    <tr className="chain-mark">
      <td colSpan={columnCount}>
        <div className="chain-mark-line">
          <span className="badge badge-pill chain-mark-badge">
            기초 선물 {futuresPrice.toFixed(decimals)}
          </span>
        </div>
      </td>
    </tr>
  )

  const renderCells = (
    leg: ChainLeg,
    order: FieldKey[],
    legSide: 'call' | 'put',
    itm: boolean,
    strike: number,
  ) =>
    order.map((key) => {
      const pick: ChainPick = { code: leg.code, side: legSide, strike }
      const def = CHAIN_FIELDS[key] as FieldDef
      const extra = def.suffix ? def.suffix.length : 0
      return (
        <td
          key={`${legSide}-${key}`}
          className={[
            'row-click',
            key === 'oi' || key === 'oiChange' ? 'col-oi' : '',
            itm ? 'chain-itm' : '',
            selectedCode !== null && selectedCode === leg.code ? 'chain-picked' : '',
            def.bar ? `vol-cell vol-${legSide}` : '',
          ]
            .filter(Boolean)
            .join(' ')}
          style={{ ...fracWidth(fieldDecimals(def, decimals), extra), minWidth: widthOf(def) }}
          onClick={() => onSelect(pick)}
          onDoubleClick={() => onOpen(pick)}
        >
          {def.bar && loaded && (
            <span
              className="vol-bar"
              style={{ width: `${((def.value(leg) ?? 0) / (barMax.get(key) ?? 1)) * 100}%` }}
              aria-hidden="true"
            />
          )}
          <span className={def.bar ? 'vol-value' : undefined}>{renderValue(def, leg, decimals)}</span>
        </td>
      )
    })

  const headerCells = (order: FieldKey[], prefix: string) =>
    order.map((key) => {
      const def = CHAIN_FIELDS[key] as FieldDef
      return (
        <th key={`${prefix}-${key}`} style={{ minWidth: widthOf(def) }}>
          {def.label}
        </th>
      )
    })

  const strikeStyle = { minWidth: STRIKE_MIN_WIDTH }

  /* 폭은 열이 정합니다. 고정 열은 실측 최소폭을 그대로 쓰고, 막대 열만
   * 폭을 비워 두어 남는 자리를 나눠 갖습니다. */
  const cols = (order: FieldKey[], prefix: string) =>
    order.map((key) => {
      const def = CHAIN_FIELDS[key] as FieldDef
      return <col key={`${prefix}-${key}`} style={def.bar ? undefined : { width: widthOf(def) }} />
    })

  /* **표의 사정은 조작 줄 아래 상태 줄 하나가 말합니다** — 받는 중, 못 받음, 행사가
     없음, 야간 표지가 모두 같은 자리입니다. 자리가 하나라 무엇이 오든 눈이 같은
     곳을 봅니다. 표 안에 두면 그 행에 대한 말로 읽히고, 표는 등가격을 가운데 두고
     열려 위쪽이 화면 밖이라 **스크롤 밖**입니다.

     첫 답이 오기 전에는 표가 없습니다 — 행사가 축까지 서버가 주므로 세울 줄이
     없습니다. 받아 둔 표가 있으면 실패해도 표는 그대로 서고 이 줄만 붙습니다 —
     낡은 표가 없는 표보다 낫고, 다음 물음이 5초 뒤 옵니다. 거절은 눌러도 같은
     답이라 단추를 안 세웁니다. */
  const state = !loaded
    ? failure
      ? 'failed'
      : 'loading'
    : rows.length === 0
      ? 'empty'
      : failure
        ? 'failed'
        : null
  const statusLine = (night || state) && (
    <p className="list-stale chain-note">
      {night && <span>야간 · 전일종가 기준</span>}
      {state === 'loading' && <span>받는 중</span>}
      {state === 'empty' && <span>해당하는 행사가가 없습니다</span>}
      {state === 'failed' && (
        <span>
          {/* 모의투자라 못 받는 것은 까닭이 정해진 답이라 그대로 말하고, 다시 받는
              단추를 안 세웁니다. */}
          {failure === 'paper' ? '모의투자에서는 야간 옵션 시세를 받을 수 없습니다' : '받지 못했습니다'}
          {failure === 'retry' && (
            <button type="button" className="btn btn-quiet" onClick={onRetry}>
              다시
            </button>
          )}
        </span>
      )}
    </p>
  )
  if (!loaded || rows.length === 0) return <>{statusLine}</>

  return (
    <>
      {statusLine}
    <div className="table-scroll chain-scroll" ref={scrollRef}>
      <table
        className="data-table chain-table rows-dense t-dense"
        style={{ minWidth: tableMinWidth, maxWidth: tableMaxWidth }}
      >
          <colgroup>
            {showCall && cols(callFields, 'cc')}
            <col style={{ width: STRIKE_MIN_WIDTH }} />
            {showPut && cols(fields, 'pc')}
          </colgroup>
          <thead>
            <tr className="chain-group-row">
              {showCall && <th colSpan={fields.length}>콜</th>}
              <th className="chain-strike" style={strikeStyle}>
                행사가
              </th>
              {showPut && <th colSpan={fields.length}>풋</th>}
            </tr>
            <tr className="chain-field-row">
              {showCall && headerCells(callFields, 'ch')}
              <th className="chain-strike" style={strikeStyle} />
              {showPut && headerCells(fields, 'ph')}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              /* **기초 선물 값을 전제로 서는 것은 조회 전에 전부 걷습니다.**
                 내가격 음영·ATM 줄·그 언저리 표시는 모두 「기초 선물이 여기쯤」을
                 말하는 장치인데, 그 값을 모르는 자리에서는 지어낸 기본값을
                 말하게 됩니다. 값 칸을 다 비운 표에서 그 음영만 남으면 **표의
                 유일한 내용이 지어낸 값**이 됩니다. */
              const isAtm = atm !== null && row.strike === atm
              const isPicked =
                selectedCode !== null &&
                (row.call.code === selectedCode || row.put.code === selectedCode)
              const strikeText = row.strike.toFixed(strikeDecimals)

              return (
                <Fragment key={row.strike}>
                  {index === markIndex && markRow}
                  <tr
                    ref={isPicked ? pickedRef : isAtm ? atmRef : undefined}
                    className={[
                      isAtm ? 'chain-atm' : '',
                      markIndex >= 0 && Math.abs(index - markIndex) <= 3 ? 'chain-near' : '',
                    ]
                      .filter(Boolean)
                      .join(' ') || undefined}
                  >
                    {showCall &&
                      renderCells(row.call, callFields, 'call', futuresPrice !== null && row.strike < futuresPrice, row.strike)}
                    <td className="chain-strike" style={strikeStyle}>
                      {strikeText}
                    </td>
                    {showPut &&
                      renderCells(row.put, fields, 'put', futuresPrice !== null && row.strike > futuresPrice, row.strike)}
                  </tr>
                  {/* 값이 행사가 전부보다 낮을 때의 자리 — 마지막 행 뒤. */}
                  {index === rows.length - 1 && markIndex === rows.length && markRow}
                </Fragment>
              )
            })}
          </tbody>
      </table>
    </div>
    </>
  )
}
