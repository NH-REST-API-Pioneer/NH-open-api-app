"""롤링 β 스프레드 예제 (HO × RB) — 모양을 보이려는 예제입니다. 수익 전략이 아닙니다.

최근 WINDOW 분의 HO 를 RB 에 회귀해 β 를 구하고, 스프레드(HO − β·RB)가 그 창 평균에서 얼마나 떨어졌는지(z)로 판단합니다.
- z > ENTRY_Z  : 스프레드가 비싸다 → HO 팔고 RB 산다   (ctx.target 으로 두 다리를 한 번에)
- z < −ENTRY_Z : 반대
- |z| < EXIT_Z 이거나 보유 시간이 MAX_HOLD_MIN 을 넘으면 0 으로 푼다.
표준 라이브러리만 씁니다. 이어받은 실행이면 `ctx.inherited` 와 지금 보유로 방향·진입 시각을 되살립니다.
"""
from __future__ import annotations

from collections import deque
from datetime import timedelta

TITLE = "롤링 β 스프레드 (모양 예제)"
NAME = "spread_rolling_beta"
LEGS = {"ho": "HO", "rb": "RB"}
MAX_QTY = 2

WINDOW = 60          # 회귀 창(분)
ENTRY_Z = 2.0
EXIT_Z = 0.5
MAX_HOLD_MIN = 120   # 보유 시간 상한(분)


def fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """y = a + b·x 최소제곱 → (a, b). x 가 모두 같으면 b = 0."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return my, 0.0
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - b * mx, b


def zscore(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    """(z, β). 마지막 점이 창의 회귀 잔차 분포에서 얼마나 떨어졌는지. 흩어짐이 0 이면 None."""
    a, b = fit(xs, ys)
    resid = [y - a - b * x for x, y in zip(xs, ys)]
    mean = sum(resid) / len(resid)
    sd = (sum((r - mean) ** 2 for r in resid) / len(resid)) ** 0.5
    if sd == 0:
        return None
    return (resid[-1] - mean) / sd, b


def run(ctx):
    rb_px: deque[float] = deque(maxlen=WINDOW)
    ho_px: deque[float] = deque(maxlen=WINDOW)
    entered_at = None

    # 이어받은 실행이면 앱이 준 보유(ctx.position)로 상태를 되살린다 — 진입 시각은 모르니 지금부터 센다.
    inh = ctx.inherited
    if inh:
        ctx.log("inherited", 1, **{f"{k}_qty": v["qty"] for k, v in inh["legs"].items()})
    if ctx.position("ho") or ctx.position("rb"):
        entered_at = ctx.now()

    # 시작할 때 과거 분봉으로 창을 채운다.
    for m in ctx.bars(["ho", "rb"], WINDOW):
        ho_px.append(m.legs["ho"].close)
        rb_px.append(m.legs["rb"].close)

    while ctx.running():                      # 돌려주면 보유가 있을 때 앱이 정리한다 — 날을 넘기려면 계속 돈다
        m = ctx.next_minute(["ho", "rb"])
        if m is None:
            break
        ho_px.append(m.legs["ho"].close)
        rb_px.append(m.legs["rb"].close)
        if len(ho_px) < WINDOW:
            continue
        got = zscore(list(rb_px), list(ho_px))
        if got is None:
            continue
        z, beta = got
        ctx.log("z", z, beta=beta)

        held = ctx.position("ho")
        try:
            if held == 0 and abs(z) > ENTRY_Z:
                side = -1 if z > 0 else 1     # z 가 크면 HO 를 판다
                ctx.target({"ho": side, "rb": -side})
                entered_at = ctx.now()
            elif held != 0:
                too_long = entered_at is not None and ctx.now() - entered_at > timedelta(minutes=MAX_HOLD_MIN)
                if abs(z) < EXIT_Z or too_long:
                    ctx.target({"ho": 0, "rb": 0})
                    entered_at = None
        except Exception as e:                # OrderRejected(장 쉼·한도 등)은 다음 분에 다시. Halted 면 running() 이 거짓이 된다.
            ctx.log("order_failed", 1, why=str(e))
