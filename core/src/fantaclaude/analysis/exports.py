"""Renderings of a run: rankings.md / rankings.csv and the asta plan under
data/exports/ (regenerable, rewritten by every rank), and the durable
parquet copies under records/ (committed, named by run_id / rules_hash,
never rewritten -- live-event requirement 5: a journal entry that links a
run_id nothing can resolve is worthless)."""

from __future__ import annotations

import csv
from pathlib import Path

import duckdb

from fantaclaude.analysis.valuation import ValuationRun
from fantaclaude.model.demand import ROLE_CLASSES

CSV_COLUMNS = ("run_id", "player_id", "name", "team", "classic_role", "role_class", "roles", "tier", "exp_presenze",
               "exp_fantamedia", "value_p25", "value_p50", "value_p75", "vor", "quot_mantra", "expected_price",
               "max_p25", "max_p50", "max_p75", "implied_value", "divergence")


def _rows(run: ValuationRun, scenario: str) -> list[dict]:
    board = run.boards[scenario]
    rows = []
    for p in run.projections:
        price = board.prices[p.player_id]
        implied, div = run.implied[p.player_id]
        rows.append({"run_id": run.run_id, "player_id": p.player_id, "name": p.name, "team": p.team_short,
                     "classic_role": p.classic_role, "role_class": p.role_class, "roles": ";".join(p.roles),
                     "tier": run.tiers[p.player_id], "exp_presenze": round(p.exp_presenze, 1),
                     "exp_fantamedia": round(p.exp_fantamedia, 2), "value_p25": round(p.value_p25, 1),
                     "value_p50": round(p.value_p50, 1), "value_p75": round(p.value_p75, 1),
                     "vor": round(run.vor[p.player_id], 1), "quot_mantra": p.quotazione,
                     "expected_price": price.expected_price, "max_p25": price.band.p25, "max_p50": price.band.p50,
                     "max_p75": price.band.p75, "implied_value": round(implied, 1), "divergence": round(div, 1)})
    return rows


def _header(run: ValuationRun) -> list[str]:
    s = run.summary
    return [f"run `{run.run_id}` · rules {run.rules_hash} · model {run.model_hash} · inputs {run.inputs_hash}",
            f"{s['team_count']} teams × {s['budget']} credits = {s['market_credits']} on the market · "
            f"giornata {s['giornate_played']} played, {s['giornate_remaining']} remaining · voti sheet {s['sheet']}"
            + (" · D-Factor active" if s.get("d_factor_active") else ""),
            *(f"warning: {w}" for w in run.warnings)]


def write_rankings(run: ValuationRun, exports_dir: Path) -> tuple[Path, Path]:
    exports_dir.mkdir(parents=True, exist_ok=True)
    scenario = run.scenarios[0].name
    rows = _rows(run, scenario)
    board = run.boards[scenario]
    lines = ["# Rankings", "", *_header(run), f"inflation {board.inflation:.2f} · composition "
             + ", ".join(f"{cls} {n}" for cls, n in board.composition.items() if n) + f" · reserve {board.reserve}", ""]
    for cls in ROLE_CLASSES:
        ranked = sorted((r for r in rows if r["role_class"] == cls), key=lambda r: -r["value_p50"])
        if not ranked:
            continue
        lines += [f"## {cls}  (replacement {run.replacement.get(cls, 0.0):.0f})", "",
                  "| # | player | team | roles | tier | pres | fm | value p50 (p25–p75) | VOR | quot | exp | max p25/p50/p75 | Δ market |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for i, r in enumerate(ranked, 1):
            lines.append(f"| {i} | {r['name']} | {r['team']} | {r['roles']} | {r['tier']} | {r['exp_presenze']} | "
                         f"{r['exp_fantamedia']} | {r['value_p50']} ({r['value_p25']}–{r['value_p75']}) | {r['vor']} | "
                         f"{r['quot_mantra']} | {r['expected_price']} | {r['max_p25']}/{r['max_p50']}/{r['max_p75']} | "
                         f"{r['divergence']:+} |")
        lines.append("")
    md = exports_dir / "rankings.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    out = exports_dir / "rankings.csv"
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (ROLE_CLASSES.index(r["role_class"]), -r["value_p50"])))
    return md, out


def write_asta_plan(run: ValuationRun, exports_dir: Path) -> Path:
    exports_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# Asta plan", "", *_header(run), ""]
    for scenario in run.scenarios:
        board = run.boards[scenario.name]
        q = scenario.quantile
        rows = _rows(run, scenario.name)
        lines += [f"## {scenario.name}", "",
                  f"Risk appetite {scenario.risk_appetite}: bid to {q}. Inflation {board.inflation:.2f}, reserve {board.reserve}."
                  + (f" Departed from the target at {', '.join(board.targets_departed)}." if board.targets_departed else ""),
                  "", "**Composition** (players · credits): "
                  + ", ".join(f"{cls} {n} · {board.credits_by_class.get(cls, 0)}" for cls, n in board.composition.items() if n),
                  "", "**Targets per class** (max price at the chosen quantile, tier):", ""]
        for cls in ROLE_CLASSES:
            ranked = sorted((r for r in rows if r["role_class"] == cls), key=lambda r: -r["value_p50"])[:3]
            if ranked:
                lines.append(f"- {cls}: " + ", ".join(f"{r['name']} {r['max_' + q]} (t{r['tier']})" for r in ranked))
        lines.append("")
    rows = _rows(run, run.scenarios[0].name)
    cheap = sorted((r for r in rows if r["expected_price"] <= 5 and r["vor"] > 0),
                   key=lambda r: -r["vor"] / r["expected_price"])[:10]
    lines += ["## Cheap value", "", *(f"- {r['name']} ({r['role_class']}, {r['team']}): VOR {r['vor']} at ~{r['expected_price']}"
                                       for r in cheap), ""]
    diverging = sorted(rows, key=lambda r: -abs(r["divergence"]))[:10]
    lines += ["## We disagree with the market", "",
              *(f"- {r['name']} ({r['role_class']}): we say {r['value_p50']}, the quotazione implies {r['implied_value']} "
                f"({r['divergence']:+})" for r in diverging), ""]
    lines += ["## If I lose him", ""]
    for cls in ROLE_CLASSES:
        ranked = sorted((r for r in rows if r["role_class"] == cls), key=lambda r: -r["value_p50"])
        if ranked:
            top = ranked[0]
            mates = [r["name"] for r in ranked[1:] if r["tier"] == top["tier"]][:3]
            lines.append(f"- {cls}: {top['name']} → " + (", ".join(mates) if mates else "nobody in his tier"))
    path = exports_dir / "asta-plan.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _literal(value: str) -> str:
    """A SQL string literal: COPY does not take bound parameters, so the two
    keys are inlined -- both are hex/timestamp identifiers, escaped anyway."""
    return "'" + value.replace("'", "''") + "'"


def export_records(con: duckdb.DuckDBPyConnection, run_id: str, rules_hash: str, records_dir: Path) -> list[Path]:
    """Parquet copies of the run's rows and of the settings row it used; a file that exists is left alone."""
    run, rules = _literal(run_id), _literal(rules_hash)
    targets = [
        (records_dir / "valuation_runs" / f"{run_id}.parquet", f"SELECT * FROM valuation_runs WHERE run_id = {run}"),
        (records_dir / "valuations" / f"{run_id}.parquet", f"SELECT * FROM valuations WHERE run_id = {run}"),
        (records_dir / "valuation_prices" / f"{run_id}.parquet", f"SELECT * FROM valuation_prices WHERE run_id = {run}"),
        (records_dir / "league_settings" / f"{rules_hash}.parquet",
         f"SELECT * FROM league_settings WHERE rules_hash = {rules} ORDER BY snapshot_id DESC LIMIT 1"),
    ]
    written: list[Path] = []
    for path, query in targets:
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        con.execute(f"COPY ({query}) TO {_literal(path.as_posix())} (FORMAT PARQUET)")
        written.append(path)
    return written
