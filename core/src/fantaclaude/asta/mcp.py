"""fantaclaude-asta: the auction MCP (spec, "A second MCP, for the
auction"). Served over HTTP by `asta serve` itself — not a separate process
— so every tool reads the same in-memory state the dashboard is showing,
and being unavailable when no auction is served is correct rather than a
limitation.

Auction-state tools answer from memory on the event loop; `asta_query`
opens fanta.duckdb read-only per call inside a threadpool so an analytical
scan never blocks the WebSocket. `asta_adjust` writes through
server.adjust — the same one-writer path as the dashboard form and the CLI
proxy. The model changes inputs and interprets outputs; it never computes
the number (spec, "What the model is for"): `asta_explain` returns the
pricer's own trace to read, not to recompute.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import duckdb
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from fantaclaude.api.serve import AstaServer, PhaseError
from fantaclaude.asta.adjustments import AdjustmentsError, adjustment_from_entry
from fantaclaude.asta.pricing import explain as explain_price
from fantaclaude.asta.session import SessionError
from fantaclaude.commands.asta import UsageError, player_of

INSTRUCTIONS = (
    "Live read-and-adjust access to the fantaclaude auction board while `fantaclaude asta serve` runs. "
    "Bands and pressure are computed by the server; read them, explain them, and turn facts from the room "
    "into adjustments — never recompute a price. `asta_query` reads the analytical database (fanta.duckdb) "
    "read-only; auction state itself is not in the database, use the board tools for it."
)


def build_mcp(server: AstaServer, db_path: Path) -> FastMCP:
    mcp = FastMCP(name="fantaclaude-asta", instructions=INSTRUCTIONS)

    def board():
        if server.auction is None:
            raise ToolError("the mapping screen has not been answered yet; the board does not exist")
        return server.auction.board

    @mcp.tool
    def asta_status() -> dict[str, Any]:
        """The serve process's state: phase, feed status, session, run, picks so far, problem count."""
        try:
            hello = server.hello()
        except SessionError as exc:
            raise ToolError(str(exc)) from None
        b = hello["board"]
        return {"phase": hello["phase"], "mode": hello["mode"], "feed": hello["feed"],
                "session_code": hello["session_code"], "run": hello["run"], "scenario": hello["scenario"],
                "picks": 0 if b is None else b["picks"],
                "problems": [] if b is None else b["problems"],
                "league_conflicts": hello["league_conflicts"]}

    @mcp.tool
    def asta_board(top: int = 5) -> dict[str, Any]:
        """The board in summary: my ledger, every team's credits and slots, the lot on the block with its
        band and pressure, the top `top` unsold players per role class, composition and inflation. The
        full per-player dict is the dashboard's; ask asta_explain for one player's trace."""
        b = board()
        d = b.to_dict()
        return {"run_id": d["run_id"], "scenario": d["scenario"], "settings": d["settings"],
                "league_conflicts": d["league_conflicts"], "problems": d["problems"],
                "me": d["me"], "teams": d["teams"], "market_credits": d["market_credits"],
                "inflation": d["inflation"], "composition": d["composition"],
                "credits_by_class": d["credits_by_class"], "reserve": d["reserve"], "budget": d["budget"],
                "targets_departed": d["targets_departed"], "lot": d["lot"], "lot_pressure": d["lot_pressure"],
                "adjustments": d["adjustments"], "tiers": b.tiers(top)}

    @mcp.tool
    def asta_explain(player: str) -> dict[str, Any]:
        """One player's price, explained from the pricer's own trace: band, walk/buy values, expected
        price, pressure (who can still bid and how deep), and any adjustment touching him. `player` is
        the listone's spelling ("Martinez L.") or the listone id."""
        b = board()
        try:
            who = player_of(server.run, player)
        except UsageError as exc:
            raise ToolError(str(exc)) from None
        pick = b.state.picks.get(who.player_id)
        trace = explain_price(b.pricing, who.player_id) if who.player_id in b.pricing.prices else None
        pressure = b.pressure[who.player_id].to_dict() if who.player_id in b.pressure else None
        return {"player": who.to_dict(),
                "sold_to": None if pick is None else pick.team_id,
                "cost": None if pick is None else pick.cost,
                "trace": trace, "pressure": pressure,
                "adjustments": [e.adjustment.describe() for e in b.layer.entries if e.player_id == who.player_id]}

    @mcp.tool
    async def asta_adjust(type: str, reason: str, player: str | None = None, player_id: int | None = None,
                          factor: float | None = None, role_class: str | None = None,
                          count: int | None = None) -> dict[str, Any]:
        """Turn a fact from the room into an adjustment — value (with factor), exclude, or target (with
        role_class and count) — appended to data/adjustments.yml with its reason and applied to the board
        at once, through the same single-writer path as the dashboard form."""
        raw = {k: v for k, v in (("player", player), ("player_id", player_id), ("type", type),
                                 ("factor", factor), ("class", role_class), ("count", count),
                                 ("reason", reason)) if v is not None}
        try:
            adjustment = adjustment_from_entry(raw, "asta_adjust")
        except AdjustmentsError as exc:
            raise ToolError(str(exc)) from None
        try:
            out = await server.adjust(adjustment)
        except (PhaseError, UsageError, AdjustmentsError) as exc:
            raise ToolError(str(exc)) from None
        band_after = None
        if out["player_id"] is not None:
            row = out["board"]["prices"].get(str(out["player_id"]))
            band_after = None if row is None else row["band"]
        return {"described": out["described"], "count": out["count"], "band_after": band_after,
                "problems": out["board"]["problems"]}

    @mcp.tool
    async def asta_refresh() -> dict[str, Any]:
        """Reread data/adjustments.yml and the participant dossiers, re-price the whole board, and
        broadcast it — the hand-edited-file case."""
        try:
            out = await server.refresh()
        except (PhaseError, AdjustmentsError) as exc:
            raise ToolError(str(exc)) from None
        return {"problems": out["problems"], "adjustments": out["board"]["adjustments"]}

    @mcp.tool
    async def asta_query(sql: str, limit: int = 50) -> dict[str, Any]:
        """Run one read-only SQL query against fanta.duckdb (players, history, valuations — see
        `fantaclaude schema`). Auction state is NOT in the database; use the board tools. Rows are
        capped at `limit`."""
        def work() -> dict[str, Any]:
            con = duckdb.connect(str(db_path), read_only=True)
            try:
                cursor = con.execute(sql)
                columns = [d[0] for d in cursor.description or []]
                rows = cursor.fetchmany(limit + 1)
            finally:
                con.close()
            return {"columns": columns, "rows": [list(r) for r in rows[:limit]],
                    "truncated": len(rows) > limit}
        try:
            return await asyncio.to_thread(work)
        except duckdb.Error as exc:
            raise ToolError(str(exc)) from None

    return mcp
