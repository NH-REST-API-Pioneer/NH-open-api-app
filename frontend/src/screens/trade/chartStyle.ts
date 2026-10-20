import { lastDrawingStyle, overlayStyles } from './chartDrawings'

/** CSS 토큰을 라이브러리 스타일로 옮깁니다. 색을 두 곳에 적어 두지 않습니다. */
export function styleFromTokens(): Record<string, unknown> {
  const css = getComputedStyle(document.documentElement)
  const token = (name: string) => css.getPropertyValue(name).trim()
  const up = token('--up')
  const down = token('--down')
  const upBar = token('--up-bar')
  const downBar = token('--down-bar')
  const label = token('--text-label')
  const dim = token('--text-dim')
  const grid = token('--divider')

  return {
    grid: {
      horizontal: { color: grid },
      vertical: { color: grid },
    },

    /* 국내 관례를 따릅니다 — 오르면 빨강, 내리면 파랑. 라이브러리 기본은
       그 반대(초록·빨강)라 반드시 덮어써야 합니다. 앱의 다른 방향값과 같은
       색이어야 화면을 옮겨도 같은 뜻입니다. */
    candle: {
      bar: {
        upColor: up,
        downColor: down,
        noChangeColor: dim,
        upBorderColor: up,
        downBorderColor: down,
        noChangeBorderColor: dim,
        upWickColor: up,
        downWickColor: down,
        noChangeWickColor: dim,
      },
      priceMark: {
        high: { color: label },
        low: { color: label },
        last: { upColor: up, downColor: down, noChangeColor: dim },
      },
      /* 값은 이 앱의 범례가 말합니다. 라이브러리 말풍선은 봉 위에 상자를 띄워
         봉을 가립니다. */
      tooltip: { showRule: 'none' },
    },

    /* 거래량 막대는 호가 잔량 막대와 같은 옅은 색을 씁니다. 봉과 같은 진한
       색으로 칠하면 아래 칸이 위 칸만큼 눈에 들어와 주가를 가립니다.
       선 색은 지표마다 사용자 설정이 덮어씁니다. */
    indicator: {
      ohlc: { upColor: upBar, downColor: downBar, noChangeColor: dim },
      bars: [{ upColor: upBar, downColor: downBar, noChangeColor: dim }],
      circles: [{ upColor: upBar, downColor: downBar, noChangeColor: dim }],
      tooltip: { showRule: 'none' },
      /* 마지막 값 표시는 켜면 모든 지표에 붙어 가격축이 이동평균 값으로
         덮입니다. 아래 칸의 배지는 이 앱이 따로 그립니다. */
      lastValueMark: { show: false },
    },

    xAxis: { axisLine: { color: grid }, tickLine: { color: grid }, tickText: { color: label } },
    yAxis: { axisLine: { color: grid }, tickLine: { color: grid }, tickText: { color: label } },

    crosshair: {
      horizontal: { line: { color: dim }, text: { backgroundColor: label } },
      vertical: { line: { color: dim }, text: { backgroundColor: label } },
    },

    /* 그린 도형의 기본색. 도형마다 사용자 색이 덮어씁니다. */
    overlay: overlayStyles(lastDrawingStyle()),

    separator: { color: grid },
  }
}
