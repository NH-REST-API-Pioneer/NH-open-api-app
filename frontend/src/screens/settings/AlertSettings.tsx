import { useState } from 'react'

import {
  ALERT_KINDS,
  ALERT_KIND_LABEL,
  SILENT_KINDS,
  osRoute,
  playTone,
  sendTestNotification,
  useAlertSettings,
  type AlertKind,
  type AlertSettings,
} from '../../data/alerts'

/* 설정 「일반」의 알림 묶음 — 전략 실행에서 일어난 일을 토스트·소리·운영체제 알림으로
 * 알릴지.
 *
 * 값은 화면 상태 파일(`nh.alerts`)에 남아 다른 창에서도 같습니다. 바꾸면 바로
 * 반영됩니다 — 저장 단추가 없습니다. */

function Switch({
  label,
  on,
  onChange,
  locked = null,
}: {
  label: string
  on: boolean
  onChange: (on: boolean) => void
  /** 켤 수 없는 까닭. 있으면 잠기고 `title` 로 그 까닭을 보입니다. */
  locked?: string | null
}) {
  return (
    <button
      type="button"
      className="alert-switch"
      role="switch"
      aria-checked={on}
      aria-disabled={locked !== null}
      title={locked ?? undefined}
      onClick={() => {
        if (locked === null) onChange(!on)
      }}
    >
      <span className="alert-switch-track" aria-hidden="true">
        <span className="alert-switch-knob" />
      </span>
      {label}
    </button>
  )
}

export function AlertSettingsGroup() {
  const [settings, store] = useAlertSettings()
  const set = (patch: Partial<AlertSettings>) => store({ ...settings, ...patch })
  const setKind = (kind: AlertKind, part: 'toast' | 'sound' | 'os', on: boolean) =>
    set({ kinds: { ...settings.kinds, [kind]: { ...settings.kinds[kind], [part]: on } } })

  /* 운영체제 알림의 길. 데스크톱 앱이면 앱이 풍선을 띄우고, 브라우저면 브라우저 알림
     권한이 있어야 합니다. 권한은 **스위치를 켜거나 「보내 보기」를 누를 때만** 묻습니다. */
  const route = osRoute()
  const [permission, setPermission] = useState<NotificationPermission | null>(() =>
    route === 'browser' ? Notification.permission : null,
  )
  const denied = route === 'browser' && permission === 'denied'
  const unsupported = route === 'none' ? '이 브라우저는 운영체제 알림을 지원하지 않습니다' : null
  /* 브라우저 알림 권한을 묻습니다. 이미 정해져 있으면 그 값입니다. */
  async function ask(): Promise<NotificationPermission | null> {
    if (route !== 'browser') return null
    if (Notification.permission !== 'default') {
      setPermission(Notification.permission)
      return Notification.permission
    }
    const said = await Notification.requestPermission().catch(() => Notification.permission)
    setPermission(said)
    return said
  }
  const osOff = !settings.os || denied

  return (
    <section className="settings-alerts" aria-label="알림">
      <h2 className="settings-name">알림</h2>
      <p className="settings-note">
        {settings.os
          ? '전략 실행에서 일어난 일을 화면 오른쪽 아래에 알리고, 창이 가려져 있으면 운영체제 알림으로도 알립니다.'
          : '전략 실행에서 일어난 일을 화면 오른쪽 아래에 알립니다.'}
      </p>
      <div className="alert-top">
        <Switch label="토스트" on={settings.toast} onChange={(on) => set({ toast: on })} />
        <Switch label="소리" on={settings.sound} onChange={(on) => set({ sound: on })} />
        <Switch
          label="운영체제 알림"
          on={settings.os}
          locked={unsupported}
          onChange={(on) => {
            set({ os: on })
            if (on) void ask()
          }}
        />
        {/* 소리를 켰을 때 두 소리를 한 번씩 들려줍니다 — 체결음, 경고음 차례. */}
        <button
          type="button"
          className="btn btn-outline alert-preview"
          aria-disabled={!settings.sound}
          title={settings.sound ? undefined : '소리를 켜면 들어 볼 수 있습니다'}
          onClick={() => {
            if (!settings.sound) return
            playTone('fill', true)
            window.setTimeout(() => playTone('warn', true), 600)
          }}
        >
          들어 보기
        </button>
        {/* 시험 알림 하나 — 데스크톱 앱이면 창이 앞에 있어도 띄웁니다. */}
        <button
          type="button"
          className="btn btn-quiet alert-preview-os"
          aria-disabled={!settings.os || unsupported !== null}
          title={settings.os ? undefined : '운영체제 알림을 켜면 보내 볼 수 있습니다'}
          onClick={async () => {
            if (!settings.os || unsupported !== null) return
            if (route === 'browser' && (await ask()) !== 'granted') return
            sendTestNotification()
          }}
        >
          보내 보기
        </button>
      </div>
      {/* 브라우저가 알림을 막아 두었으면 — 스위치는 켜 둘 수 있지만 지금은 알림이 안
          나므로 OS 열이 잠기고, 어디서 풀면 되는지 한 줄로 적습니다. 데스크톱 앱에서는
          서지 않습니다. */}
      {denied && (
        <p className="alert-denied">
          브라우저가 이 앱의 알림을 막아 두었습니다 — 주소창 왼쪽 자물쇠에서 알림을 허용하세요
        </p>
      )}

      {/* 종류마다 토스트·소리. 토스트 열은 「토스트」가, 소리 열은 「소리」가 꺼져
          있으면 흐리게 잠깁니다 — 켜 둔 칸은 그대로 두되, 지금은 그 알림이 안 난다는
          것을 그대로 보입니다. */}
      <table
        className={`alert-table${settings.toast ? '' : ' is-toast-off'}${settings.sound ? '' : ' is-muted'}${osOff ? ' is-os-off' : ''}`}
      >
        <thead>
          <tr>
            <th scope="col">종류</th>
            <th scope="col">토스트</th>
            <th scope="col">소리</th>
            <th scope="col">OS</th>
          </tr>
        </thead>
        <tbody>
          {ALERT_KINDS.map((kind) => {
            const label = ALERT_KIND_LABEL[kind]
            const silent = SILENT_KINDS.includes(kind)
            return (
              <tr key={kind}>
                <th scope="row">{label}</th>
                <td className="alert-toast-cell">
                  <input
                    type="checkbox"
                    aria-label={`${label} 토스트`}
                    checked={settings.kinds[kind].toast}
                    disabled={!settings.toast}
                    onChange={(event) => setKind(kind, 'toast', event.target.checked)}
                  />
                </td>
                <td className="alert-sound-cell">
                  {silent ? (
                    <span className="alert-silent" title="신호는 소리를 내지 않습니다">
                      —
                    </span>
                  ) : (
                    <input
                      type="checkbox"
                      aria-label={`${label} 소리`}
                      checked={settings.kinds[kind].sound}
                      disabled={!settings.sound}
                      onChange={(event) => setKind(kind, 'sound', event.target.checked)}
                    />
                  )}
                </td>
                <td className="alert-os-cell">
                  <input
                    type="checkbox"
                    aria-label={`${label} 운영체제 알림`}
                    checked={settings.kinds[kind].os}
                    disabled={osOff}
                    onChange={(event) => setKind(kind, 'os', event.target.checked)}
                  />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <label className="alert-sim">
        <input
          type="checkbox"
          checked={settings.simRuns}
          onChange={(event) => set({ simRuns: event.target.checked })}
        />
        검증(앱 시뮬레이션) 실행도 알림
      </label>
      <p className="settings-note">끄면 검증 실행은 한도 정지와 시세 끊김만 알립니다.</p>
    </section>
  )
}
