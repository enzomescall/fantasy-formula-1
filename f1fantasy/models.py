from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _require_list(name: str, v: Any, n: int | None = None) -> list[str]:
    if not isinstance(v, list):
        raise ValueError(f"{name} must be a list")
    if n is not None and len(v) != n:
        raise ValueError(f"{name} must have length {n}")
    out: list[str] = []
    for x in v:
        if not isinstance(x, str) or not x.strip():
            raise ValueError(f"{name} must contain non-empty strings")
        out.append(x)
    return out


@dataclass(frozen=True)
class TeamSpec:
    drivers: list[str]
    constructors: list[str]
    boost_driver: str | None = None

    def validate(self) -> None:
        _require_list("drivers", self.drivers, n=5)
        _require_list("constructors", self.constructors, n=2)
        if self.boost_driver is not None:
            if not isinstance(self.boost_driver, str) or not self.boost_driver.strip():
                raise ValueError("boost_driver must be a non-empty string or None")
            if self.boost_driver not in self.drivers:
                raise ValueError("boost_driver must be one of the 5 drivers")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "TeamSpec":
        ts = TeamSpec(
            drivers=_require_list("drivers", d.get("drivers"), n=5),
            constructors=_require_list("constructors", d.get("constructors"), n=2),
            boost_driver=d.get("boost_driver"),
        )
        ts.validate()
        return ts


@dataclass(frozen=True)
class BudgetSnapshot:
    remaining_m: float
    used_m: float
    cap_m: float
    currency: str = "USD"
    source: str = "fantasy.formula1.com"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TeamState:
    ts_utc: str
    team_id: int
    team_name: str | None
    drivers: list[str]
    constructors: list[str]
    boost_driver: str | None
    budget: BudgetSnapshot | None = None
    score: dict[str, Any] | None = None
    url: str | None = None
    source: str = "site"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.budget is not None:
            d["budget"] = self.budget.to_dict()
        return d


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    diff_final_vs_ideal: dict[str, Any] = field(default_factory=dict)
