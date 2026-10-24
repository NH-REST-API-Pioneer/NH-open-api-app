import { Component, type ErrorInfo, type ReactNode } from 'react'
import { hasUnsaved } from '../data/strategyStore'

/** 화면(탭) 하나를 감싸는 오류 경계.
 *
 *  한 화면을 그리다가 오류가 나면 **그 화면 자리에만** 안내를 세웁니다. 상단 띠와
 *  옆 레일은 경계 밖이라 그대로 살아 있어, 다른 탭으로 옮겨 계속 쓸 수 있습니다.
 *  경계가 없으면 오류 하나로 앱 전체가 빈 화면이 됩니다.
 *
 *  **오류가 없을 때는 아무것도 감싸지 않습니다** — 화면 루트가 그대로 화면 칸의
 *  자식이어야 화면 칸의 배치 규칙(`.app-screen > *`)이 그 루트에 걸립니다.
 *
 *  부르는 쪽이 탭마다 다른 `key` 를 주어, 탭을 옮기면 경계가 새로 서고 안내가
 *  걷힙니다. 같은 탭 안에서는 다시 서지 않습니다. */
export class ScreenBoundary extends Component<{ children: ReactNode }, { error: unknown }> {
  state: { error: unknown } = { error: null }

  static getDerivedStateFromError(error: unknown): { error: unknown } {
    return { error: error ?? new Error('알 수 없는 오류') }
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    /* 원문은 안내 아래 「오류 내용」에도 서지만, 컴포넌트 위치는 콘솔에만 있습니다. */
    console.error('[화면 오류]', error, info.componentStack)
  }

  render(): ReactNode {
    const { error } = this.state
    if (error === null) return this.props.children
    return (
      <div className="screen-error" role="alert">
        <p className="screen-error-title">이 화면을 그리지 못했습니다</p>
        <p className="screen-error-text">
          다른 탭은 그대로 쓸 수 있습니다 — 이미 낸 주문과 도는 실행은 이 화면과 상관없이 그대로입니다
        </p>
        {/* 새로 고치면 화면 안에만 있던 전략 설정 초안이 사라집니다. 그런 초안이
            있을 때만 미리 말합니다. */}
        {hasUnsaved() && (
          <p className="screen-error-draft">저장하지 않은 전략 설정은 새로 고치면 사라집니다</p>
        )}
        <button type="button" className="btn btn-primary screen-error-reload" onClick={() => window.location.reload()}>
          새로 고침
        </button>
        <details className="screen-error-detail">
          <summary>오류 내용</summary>
          <pre>{errorText(error)}</pre>
        </details>
      </div>
    )
  }
}

/** 안내 아래에 적는 오류 원문. 이름·문장과 호출 자리 앞 여섯 줄입니다 — 그 아래는
 *  라이브러리 안쪽이라 읽을 것이 없습니다. `Error` 가 아닌 값이 던져졌으면 그 값을
 *  글자로 적습니다. */
function errorText(error: unknown): string {
  if (!(error instanceof Error)) return String(error)
  const head = `${error.name}: ${error.message}`
  const stack = (error.stack ?? '')
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '' && line !== head)
    .slice(0, 6)
  return [head, ...stack].join('\n')
}
