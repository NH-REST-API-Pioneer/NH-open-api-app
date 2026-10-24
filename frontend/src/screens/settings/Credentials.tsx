import { useEffect, useRef, useState } from 'react'
import { Modal } from '../../app/Modal'
import {
  accepts,
  generation,
  loadConfig,
  marketConfigured,
  useEnvironment,
  type CredentialField,
  type Environment,
} from '../../data/environment'

/* 인증 정보 편집.
 *
 * 값은 화면으로 내려오지 않습니다. 서버는 「채워져 있는지」와 「가린 표시」만
 * 보내고, 실제 값은 사용자 홈의 설정 파일에만 있습니다.
 *
 * 채워진 칸은 입력칸이 아니라 **글자**로 그립니다. 바꾸려면 「바꾸기」를 눌러야
 * 그 칸 하나가 빈 입력칸으로 열립니다. 가린 문자열이 입력칸에 들어가는 순간이
 * 없으므로, 그 문자열이 저장되어 실제 값을 덮어쓰는 일이 생길 수 없습니다.
 *
 * 저장할 때는 **연 칸만** 보냅니다. 안 보낸 칸은 서버가 손대지 않습니다.
 *
 * 설정의 상태(무엇이 채워졌는지·활성 환경)는 앱이 한 곳(`data/environment.ts`)에서
 * 들고 있습니다. 여기서 따로 읽으면 배지가 보는 환경과 이 화면이 펴는 환경이
 * 서로 다른 시각의 답이 됩니다.
 */

const ENVIRONMENTS: { id: Environment; label: string }[] = [
  { id: 'paper', label: '모의' },
  { id: 'real', label: '실전' },
]

const MARKETS = [
  { id: 'domestic', label: '국내' },
  { id: 'overseas', label: '해외' },
] as const

const FIELDS: { id: CredentialField; label: string }[] = [
  { id: 'app_key', label: 'App Key' },
  { id: 'app_secret', label: 'Secret Key' },
]

interface Check {
  environment: string
  market: string
  ok: boolean
}

/** 「모의/국내/app_key」처럼 한 칸을 가리키는 이름. */
const cellKey = (env: string, market: string, field: CredentialField) =>
  `${env}.${market}.${field}`

type MarketId = (typeof MARKETS)[number]['id']

/** 토큰을 다시 받은 결과. 설정 창을 닫으면 사라집니다 — 지난 결과가 다음에 연
 *  창에 남으면 방금 한 일로 읽힙니다. */
type Reissued =
  | { kind: 'done'; at: string; revokeFailed: boolean; sameToken: boolean }
  | { kind: 'failed'; text: string }

/** 서버가 보낸 시각(`2026-09-30T01:02:03+09:00`)의 시:분. 서버가 한국시간으로 적어
 *  보내므로 그 글자를 그대로 읽습니다 — 이 컴퓨터의 시간대로 다시 셈하지 않습니다. */
function clockOf(iso: unknown): string {
  return typeof iso === 'string' && /T\d\d:\d\d/.test(iso) ? iso.slice(11, 16) : ''
}

interface Props {
  /** 쓸 수 있는 시장이 하나도 없어 열린 창인지. 그때는 채워야 할 묶음을 펼친 채
   *  엽니다 — 창을 연 까닭이 그 칸을 채우라는 것이라, 한 번 더 누르게 하지 않습니다. */
  openUnusable?: boolean
}

export function Credentials({ openUnusable = false }: Props) {
  const { status, active, config: view } = useEnvironment()
  /* 사용자가 열어서 입력 중인 칸만 들어 있습니다. 여기 있는 것만 저장됩니다. */
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [checks, setChecks] = useState<Check[] | null>(null)
  /* 저장이 안 된 까닭. 저장 단추 곁 안내 자리를 대신해 섭니다 — 누른 것의 답이
     누른 자리에 섭니다. 칸을 고치거나 다시 눌러 성공하면 걷힙니다. */
  const [failure, setFailure] = useState<string | null>(null)
  /* 토큰 다시 받기. 확인창을 연 시장, 받는 중인 시장, 시장마다의 마지막 결과입니다.
     받는 동안은 다른 시장의 단추와 저장 단추도 잠급니다 — 같은 설정 파일과 토큰
     파일을 건드리는 일이 겹치지 않게 합니다. */
  const [asking, setAsking] = useState<MarketId | null>(null)
  const [reissuing, setReissuing] = useState<MarketId | null>(null)
  /* 결과는 **환경과 시장**으로 담습니다 — 시장만으로 담으면 환경이 바뀐 뒤 다른
     환경의 묶음에 지난 결과가 섭니다. */
  const [reissued, setReissued] = useState<Record<string, Reissued>>({})
  /* 보내는 중인지 **바로** 아는 자리. 확인 단추를 빠르게 두 번 누르면 화면이 다시
     그려지기 전이라 상태로는 못 막고, 폐기와 발급이 두 번 나갑니다. */
  const inFlight = useRef(false)
  /* 펼친 묶음(환경·시장 하나). 처음에는 **활성 환경의 찬 묶음**만 폅니다 — 열두
     칸을 다 펴 두면 화면이 길어지고, 한 시장만 쓰는 사람에게 안 쓰는 시장의 빈
     칸을 늘 펼쳐 두면 채워야 할 것으로 읽힙니다. 빈 묶음은 접힌 머리의 「비어
     있음」이 알립니다. 쓸 수 있는 시장이 하나도 없어 열린 창이면 반대로 활성
     환경의 **못 쓰는 묶음**(빈 것과 반쯤 찬 것)을 폅니다. 환경이나 설정을 아직 모르면 아무것도 안 펴고, 알게 되거나
     환경이 바뀌면 다시 고릅니다 — 저장해서 칸이 바뀐 것으로는 다시 고르지 않습니다. */
  const filledGroups = (env: Environment): string[] =>
    view
      ? MARKETS.filter((market) => marketConfigured(view, env, market.id) !== openUnusable).map(
          (market) => `${env}.${market.id}`,
        )
      : []
  const [open, setOpen] = useState<string[]>(() => (active ? filledGroups(active) : []))
  const loaded = view !== null
  useEffect(() => {
    if (active && loaded) setOpen(filledGroups(active))
    // 환경이 바뀌거나 설정이 처음 도착한 때만 다시 고릅니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, loaded])

  const openCell = (key: string) => {
    setFailure(null)
    setEdits((prev) => ({ ...prev, [key]: '' }))
  }

  const closeCell = (key: string) => {
    setFailure(null)
    setEdits((prev) => {
      const next = { ...prev }
      delete next[key]
      return next
    })
  }

  const save = () => {
    /* 연 칸을 {환경: {시장: {항목: 값}}} 으로 접습니다. */
    const environments: Record<string, Record<string, Partial<Record<CredentialField, string>>>> = {}
    for (const [key, value] of Object.entries(edits)) {
      const [env, market, field] = key.split('.') as [string, string, CredentialField]
      environments[env] ??= {}
      environments[env][market] ??= {}
      environments[env][market][field] = value
    }
    if (Object.keys(environments).length === 0) return

    setSaving(true)
    setChecks(null)
    setFailure(null)
    void (async () => {
      try {
        const res = await fetch('/api/config', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ environments }),
        })
        if (!res.ok) {
          /* 서버가 까닭을 적어 보냈으면 그 문장 그대로입니다. 없으면 상태 코드만
             적습니다 — 까닭을 지어 서버의 말처럼 세우지 않습니다. 연 칸은 친 값
             그대로 두어 다시 누를 수 있게 합니다. */
          const body = (await res.json().catch(() => null)) as { detail?: unknown } | null
          setFailure(
            typeof body?.detail === 'string' && body.detail !== ''
              ? body.detail
              : `저장하지 못했습니다 (${res.status})`,
          )
          return
        }
        const data = (await res.json()) as { checks?: Check[] }
        setChecks(data.checks ?? [])
        /* 입력칸을 닫고 다시 읽습니다 — 화면에 값이 남지 않게 합니다. */
        setEdits({})
        void loadConfig()
      } catch {
        setFailure('저장하지 못했습니다 — 서버에 닿지 않습니다')
      } finally {
        setSaving(false)
      }
    })()
  }

  /** 지금 쓰는 환경의 한 시장 토큰을 폐기하고 같은 키로 새로 받습니다. 환경은 서버가
   *  답한 활성 환경입니다. 보내는 동안 환경이 바뀌면 그 답은 버립니다 — 다른 환경의
   *  결과를 이 줄에 적으면 틀린 말이 됩니다. */
  const reissue = (market: MarketId) => {
    if (!active || inFlight.current) return
    inFlight.current = true
    const environment = active
    const since = generation()
    setAsking(null)
    setReissuing(market)
    const slot = `${environment}.${market}`
    setReissued((prev) => {
      const next = { ...prev }
      delete next[slot]
      return next
    })
    void (async () => {
      let result: Reissued
      try {
        const res = await fetch('/api/auth/reissue', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ environment, market }),
        })
        if (!accepts(res, since)) return
        const body = (await res.json().catch(() => null)) as Record<string, unknown> | null
        if (res.ok) {
          result = {
            kind: 'done',
            at: clockOf(body?.reissuedAt),
            revokeFailed: body?.revokeFailed === true,
            sameToken: body?.sameToken === true,
          }
        } else {
          /* 서버가 까닭을 적어 보냈으면 그 문장 그대로입니다. 없으면 상태 코드만
             적습니다. */
          const detail = body?.detail
          result = {
            kind: 'failed',
            text:
              typeof detail === 'string' && detail !== ''
                ? detail
                : `토큰을 다시 받지 못했습니다 (${res.status})`,
          }
        }
      } catch {
        if (since !== generation()) return
        result = { kind: 'failed', text: '토큰을 다시 받지 못했습니다 — 서버에 닿지 않습니다' }
      } finally {
        inFlight.current = false
        setReissuing(null)
      }
      setReissued((prev) => ({ ...prev, [slot]: result }))
    })()
  }

  const openCount = Object.keys(edits).length

  const toggleGroup = (id: string) =>
    setOpen((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))

  /* 설정을 못 읽은 것과 안 채운 것은 다릅니다. 못 읽었으면 칸을 세울 수 없고,
     다시 읽는 길만 남습니다. */
  if (view === null && status === 'failed') {
    return (
      <section className="settings-section" aria-label="인증 정보">
        <h2 className="settings-name">인증 정보</h2>
        <div className="notice">
          <p className="notice-title">설정을 읽지 못했습니다</p>
          <button
            type="button"
            className="btn btn-outline notice-action"
            onClick={() => void loadConfig()}
          >
            다시 시도
          </button>
        </div>
      </section>
    )
  }

  return (
    <section className="settings-section" aria-label="인증 정보">
      <h2 className="settings-name">인증 정보</h2>
      {/* 어디에 저장되는지 적어 둡니다. 이 값이 어디 있는지 모르면 백업도
          삭제도 못 합니다. */}
      <p className="settings-note">
        사용자 홈의 <code>NHFutures/config/config.yaml</code> 에 저장됩니다. 저장소 안에는
        만들지 않습니다.
      </p>

      {view === null ? (
        <p className="settings-note">불러오는 중</p>
      ) : (
        <div className="cred-groups">
          {ENVIRONMENTS.map((env) =>
            MARKETS.map((market) => {
              const groupId = `${env.id}.${market.id}`
              const cells = view.environments?.[env.id]?.[market.id]
              const check = checks?.find((c) => c.environment === env.id && c.market === market.id)
              const expanded = open.includes(groupId)
              /* 빈 칸 개수. 다 찼으면 아무것도 안 답니다 — 표시가 있다는 것
                 자체가 신호가 되고, 접힌 채로도 어디가 비었는지 읽힙니다. 두 칸
                 다 비었으면 「비어 있음」, 한 칸만 비었으면 그 수를 적습니다 —
                 반쯤 찬 묶음은 어느 칸을 채울지가 할 일입니다. */
              const empty = FIELDS.filter((f) => !cells?.[f.id]?.set).length
              /* 토큰 다시 받기는 **지금 쓰는 환경**의 묶음에만 섭니다 — 쓰지 않는
                 환경의 토큰은 쓰이지 않아 다시 받을 일이 없습니다. */
              const reissuable = env.id === active
              const configured = marketConfigured(view, env.id, market.id)
              const result = reissuable ? reissued[groupId] : undefined

              return (
                <div key={groupId} className="cred-group">
                  <div className="cred-headrow">
                    <button
                      type="button"
                      className="cred-head"
                      aria-expanded={expanded}
                      onClick={() => toggleGroup(groupId)}
                    >
                      <span className="cred-caret" aria-hidden="true">
                        {expanded ? '▾' : '▸'}
                      </span>
                      <span className="cred-title">
                        {env.label} {market.label}
                      </span>
                      {empty > 0 && (
                        <span className="cred-empty">
                          {empty === FIELDS.length ? '비어 있음' : `${empty}칸 비어 있음`}
                        </span>
                      )}
                      {check && (
                        <span className={`badge${check.ok ? '' : ' badge-warn'}`}>
                          {check.ok ? '인증 확인됨' : '인증 실패'}
                        </span>
                      )}
                    </button>
                    {result?.kind === 'done' && (
                      <span className="cred-reissued" role="status">
                        다시 받았습니다{result.at && ` · ${result.at}`}
                        {result.revokeFailed && ' · 옛 토큰은 폐기하지 못했습니다'}
                      </span>
                    )}
                    {reissuable && (
                      <button
                        type="button"
                        className="btn btn-quiet cred-reissue"
                        /* `disabled` 가 아니라 `aria-disabled` 입니다 — 잠긴 까닭(인증 정보가
                           빔)에 키보드로도 닿으려면 초점을 받아야 합니다. */
                        aria-disabled={!configured || saving || reissuing !== null}
                        title={configured ? undefined : '인증 정보를 먼저 넣으세요'}
                        onClick={() => {
                          if (configured && !saving && reissuing === null) setAsking(market.id)
                        }}
                      >
                        {reissuing === market.id ? '받는 중' : '토큰 다시 받기'}
                      </button>
                    )}
                  </div>
                  {result?.kind === 'done' && result.sameToken && (
                    <p className="cred-reissue-warn" role="alert">
                      새 토큰이 옛 토큰과 같습니다 — 이용 신청 변경이 아직 반영되지 않았을 수 있습니다
                    </p>
                  )}
                  {result?.kind === 'failed' && (
                    <p className="cred-reissue-warn" role="alert">
                      {result.text}
                    </p>
                  )}

                  {expanded &&
                    FIELDS.map((field) => {
                      const key = cellKey(env.id, market.id, field.id)
                      const cell = cells?.[field.id]
                      const editing = key in edits

                      return (
                        <div key={field.id} className="cred-row">
                          <span className="control-label cred-label">{field.label}</span>

                          {editing ? (
                            <>
                              <input
                                className="control cred-input"
                                type="password"
                                autoComplete="off"
                                spellCheck={false}
                                value={edits[key]}
                                onChange={(event) => {
                                  setFailure(null)
                                  setEdits((prev) => ({ ...prev, [key]: event.target.value }))
                                }}
                                aria-label={`${env.label} ${market.label} ${field.label}`}
                              />
                              <button
                                type="button"
                                className="btn btn-quiet cred-action"
                                onClick={() => closeCell(key)}
                              >
                                취소
                              </button>
                            </>
                          ) : (
                            <>
                              {/* 가린 표시는 글자입니다. 입력칸이 아니라서 저장될 수
                                  없습니다. */}
                              <span className="cred-masked">
                                {cell?.set ? cell.masked : '비어 있음'}
                              </span>
                              <button
                                type="button"
                                className="btn btn-outline cred-action"
                                onClick={() => openCell(key)}
                              >
                                {cell?.set ? '바꾸기' : '입력'}
                              </button>
                            </>
                          )}
                        </div>
                      )
                    })}
                </div>
              )
            }),
          )}
        </div>
      )}

      <div className="cred-actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={openCount === 0 || saving || reissuing !== null}
          onClick={save}
        >
          {saving ? '저장하는 중' : '저장'}
        </button>
        {/* 몇 칸을 보내는지 미리 말합니다 — 나머지는 손대지 않는다는 뜻입니다.
            저장이 안 됐으면 그 동안은 이 자리에 까닭이 섭니다. */}
        {failure !== null ? (
          <span className="cred-fail" role="alert">
            {failure}
          </span>
        ) : (
          <span className="settings-note">
            {openCount === 0 ? '바꿀 칸을 먼저 여세요' : `연 ${openCount}칸만 저장합니다`}
          </span>
        )}
      </div>

      {asking !== null && active && (
        <ReissueConfirm
          title={`${active === 'paper' ? '모의' : '실전'} ${asking === 'overseas' ? '해외' : '국내'} 토큰 다시 받기`}
          overseas={asking === 'overseas'}
          onCancel={() => setAsking(null)}
          onConfirm={() => reissue(asking)}
        />
      )}
    </section>
  )
}

/** 토큰 다시 받기 확인창. **같은 키를 쓰는 다른 프로그램의 토큰도 함께 폐기되므로**
 *  한 번 묻습니다. 첫 초점은 「그만두기」입니다 — Enter 한 번에 폐기가 나가지 않게
 *  합니다. */
function ReissueConfirm({
  title,
  overseas,
  onCancel,
  onConfirm,
}: {
  title: string
  overseas: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <Modal
      label={title}
      closable={false}
      onClose={onCancel}
      head={<span className="modal-title">{title}</span>}
    >
      <p className="cred-confirm-text">
        지금 토큰을 폐기하고 새로 받습니다. 같은 키로 접속한 다른 프로그램은 다시 접속해야 합니다.
      </p>
      {/* 해외 실시간 시세는 이용 신청을 바꾼 뒤 토큰을 새로 받아야 바뀐 신청이
          반영됩니다. 이 단추를 누르는 까닭이 대개 그것이라 해외에만 적습니다. */}
      {overseas && (
        <p className="cred-confirm-text">
          해외 실시간 시세 이용 신청을 바꾼 뒤에 누르면 새 신청이 반영됩니다.
        </p>
      )}
      <div className="cred-confirm-acts">
        <button type="button" className="btn btn-quiet" onClick={onCancel}>
          그만두기
        </button>
        <button type="button" className="btn btn-primary" onClick={onConfirm}>
          다시 받기
        </button>
      </div>
    </Modal>
  )
}
