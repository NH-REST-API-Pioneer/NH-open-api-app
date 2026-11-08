"""스프레드의 다리(leg) 찾기 — 전략 파일의 `LEGS` 값(품목 뿌리 또는 종목 코드)을 종목·틱·틱 가치·통화로.

순수 함수만 둡니다(`resolve`·`next_month`). 마스터·품목 세부정보를 가져오는 일은 부르는 쪽 몫이고,
파일 읽기인 `master_rows` 만 예외입니다. 값을 지어내지 않습니다 — 못 찾으면 `LegError`(메시지는 화면에 그대로).

근거
- 해외: 종목 마스터 칸 `OVERSEAS_FUTURES_FIELDS`(`comd` 품목, `lmon_my` 만기일 기준 근월, `tsiz` 틱, `tval` 틱 가치,
  `yymm` 만기년월, `ExchName` 거래소). 통화는 마스터에 없어 품목 세부정보 `cur_cd`(기록 `overseas_product-detail`)에서.
- 국내: 종목 마스터 `series`(앞 3자리 = 품목, 미국달러선물 `A75`)·`exp_ym`(만기일)·`ctrt_size`. 틱은 품목 세부정보
  (`dtl_cd_ko_nm`·`cd_val_inf_1`·`tick_val`)에서 읽는데, 줄 이름과 마스터 품목의 대응이 확인된 건 미국달러선물뿐이다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

#: 국내 품목 뿌리 → 품목 세부정보의 줄 이름. 대응을 기록으로 확인한 것만 둔다(나머지는 추측하지 않고 거절).
_DOMESTIC_DETAIL_NAMES = {"A75": "미국달러선물(USD)"}
_SPEC_RE = re.compile(r"^[A-Za-z0-9]+$")


class LegError(ValueError):
    """다리를 찾지 못했다. 메시지는 화면에 그대로 보인다."""


@dataclass(frozen=True)
class Leg:
    name: str          # 전략 파일이 붙인 이름
    sym: str           # 종목 코드
    product: str       # 품목 뿌리 (HO · A75 …)
    market: Literal["domestic", "overseas"]
    exchange: str      # 해외 거래소 코드(FCME …), 국내는 마스터 거래소 코드
    currency: str
    tick: float
    tick_value: float  # 1틱의 가치(통화 단위)
    expiry: str        # 해외 YYYYMM, 국내 YYYYMMDD

    @property
    def point_value(self) -> float:
        """가격 1.0 의 가치 = 틱 가치 / 틱."""
        return self.tick_value / self.tick


def _s(row: dict, key: str) -> str:
    return str(row.get(key, "")).strip()


def _num(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _check_spec(spec: str) -> str:
    spec = str(spec).strip()
    if not spec or not _SPEC_RE.match(spec):
        raise LegError(f"종목 「{spec}」 을 알 수 없습니다 — 품목 뿌리(HO)나 종목 코드(HOZ26)로 적으세요")
    return spec


def _ovs_tradable(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _s(r, "type") == "F" and _s(r, "trdf") == "0"]


def _dom_live(rows: list[dict], today: str) -> list[dict]:
    return [r for r in rows if _s(r, "fo_tp") == "F" and _s(r, "exp_ym") >= today]


def _dom_root(row: dict) -> str:
    return _s(row, "series")[:3]


def _today() -> str:
    return date.today().strftime("%Y%m%d")


def resolve(
    name: str, spec: str, *,
    overseas_rows: list[dict], domestic_rows: list[dict],
    overseas_details: list[dict], domestic_details: list[dict],
    today: str | None = None,
) -> Leg:
    """`spec`(품목 뿌리 또는 정확한 종목 코드)을 `Leg` 로. 뿌리면 만기일 기준 최근월물.

    `today`(`YYYYMMDD`)는 국내에서 이미 지난 월물을 거를 때 — 시험에서만 넘긴다.
    """
    spec = _check_spec(spec)
    today = today or _today()
    ovs = _ovs_tradable(overseas_rows)
    by_code = [r for r in ovs if _s(r, "code") == spec]
    if by_code:
        return _overseas(name, by_code[0], overseas_details)
    by_root = [r for r in ovs if _s(r, "comd") == spec]
    if by_root:
        flagged = [r for r in by_root if _s(r, "lmon_my") == "1"]
        return _overseas(name, min(flagged or by_root, key=lambda r: _s(r, "yymm")), overseas_details)

    dom = _dom_live(domestic_rows, today)
    by_code = [r for r in dom if _s(r, "series") == spec]
    if by_code:
        return _domestic(name, by_code[0], domestic_details)
    by_root = [r for r in dom if len(spec) == 3 and _dom_root(r) == spec]
    if by_root:
        return _domestic(name, min(by_root, key=lambda r: _s(r, "exp_ym")), domestic_details)
    raise LegError(f"종목 「{spec}」 을 마스터에서 찾지 못했습니다 — 품목 뿌리(HO)나 거래 가능한 종목 코드(HOZ26)로 적으세요")


def _overseas(name: str, row: dict, details: list[dict]) -> Leg:
    root = _s(row, "comd")
    detail = next((d for d in details if _s(d, "prd_cd") == root), None)
    currency = _s(detail, "cur_cd") if detail else ""
    if not currency:
        raise LegError(f"{root} 의 통화를 품목 세부정보에서 찾지 못했습니다")
    tick, value = _num(row.get("tsiz")), _num(row.get("tval"))
    if not tick or not value:
        raise LegError(f"{_s(row, 'code')} 의 틱·틱 가치를 마스터에서 읽지 못했습니다")
    return Leg(name, _s(row, "code"), root, "overseas", _s(row, "ExchName"), currency, tick, value, _s(row, "yymm"))


def _domestic(name: str, row: dict, details: list[dict]) -> Leg:
    root = _dom_root(row)
    detail_name = _DOMESTIC_DETAIL_NAMES.get(root)
    detail = next((d for d in details if detail_name and _s(d, "dtl_cd_ko_nm") == detail_name), None)
    if detail is None:
        raise LegError("이 국내 품목의 틱을 찾지 못했습니다")
    tick, detail_value, size = _num(detail.get("cd_val_inf_1")), _num(detail.get("tick_val")), _num(row.get("ctrt_size"))
    if not tick or not detail_value or not size:
        raise LegError(f"{_s(row, 'series')} 의 틱·계약 크기를 읽지 못했습니다")
    value = tick * size
    if abs(value - detail_value) > 1e-6:
        raise LegError(f"{_s(row, 'series')} 의 틱 가치가 마스터({value:g})와 품목 세부정보({detail_value:g})가 다릅니다")
    return Leg(name, _s(row, "series"), root, "domestic", _s(row, "kospi_key"), "KRW", tick, value, _s(row, "exp_ym"))


def next_month(leg: Leg, *, overseas_rows: list[dict], domestic_rows: list[dict]) -> str:
    """같은 품목에서 `leg` 보다 만기가 늦은 가장 가까운 종목 코드."""
    if leg.market == "overseas":
        later = [r for r in _ovs_tradable(overseas_rows) if _s(r, "comd") == leg.product and _s(r, "yymm") > leg.expiry]
        key, code = "yymm", "code"
    else:
        later = [r for r in domestic_rows if _s(r, "fo_tp") == "F" and _dom_root(r) == leg.product and _s(r, "exp_ym") > leg.expiry]
        key, code = "exp_ym", "series"
    if not later:
        raise LegError(f"{leg.sym} 다음 월물을 마스터에서 찾지 못했습니다")
    return _s(min(later, key=lambda r: _s(r, key)), code)


def master_rows(base_dir: Any = None) -> tuple[list[dict], list[dict]]:
    """받아 둔 마스터(가장 최근 날짜)의 (해외 선물 줄, 국내 선물 줄). 파일 읽기라 재시도가 없다.

    해외는 `MASTER_FILES_BY_NAME` 의 읽는 해외 선물 파일(`cme_fut`·`etc_fut`), 국내는 `fut_opt`·`idx_fut_opt`·`stk_fut_opt`
    의 선물 줄(`fo_tp` F). 일부 파일이 없어도 읽은 것만 쓰고, 한쪽이 통째로 비면 `LegError`.
    """
    from backend.master import master_store
    from backend.master.master_files import MASTER_FILES

    overseas: list[dict] = []
    domestic: list[dict] = []
    errors: list[str] = []
    for m in MASTER_FILES:
        if not m.parsed:
            continue
        is_ovs = m.market == "overseas" and m.name.endswith("_fut")
        is_dom = m.market == "domestic"
        if not (is_ovs or is_dom):
            continue
        got = master_store.load_master(m, base_dir)
        if not got.ok or got.table is None:
            errors.append(f"{m.name}: {got.error or '표 없음'}")
            continue
        rows = list(got.table.rows_as_dicts())
        if is_ovs:
            overseas += [r for r in rows if _s(r, "type") == "F"]
        else:
            domestic += [r for r in rows if _s(r, "fo_tp") == "F"]
    if not overseas or not domestic:
        side = "해외" if not overseas else "국내"
        raise LegError(f"{side} 선물 종목 마스터를 읽지 못했습니다 — {'; '.join(errors) or '선물 줄 없음'}")
    return overseas, domestic
