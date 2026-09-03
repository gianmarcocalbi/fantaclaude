import { useMemo, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { band } from "@/lib/format";
import { Legend } from "@/components/Legend";
import { PlayerDialog } from "@/components/PlayerDialog";
import { NotPlaying } from "@/components/NotPlaying";
import { adjustedValue, anchorFor, anchorIndex } from "@/lib/anchor";
import type { BoardPayload, PriceRow } from "@/api/types";

const CLASS_ORDER = ["Por", "Ds", "Dd", "Dc", "B", "E", "M", "C", "W", "T", "A", "Pc"];
const TOP = 8;

type SortKey = "band" | "fvm";

/** The board's own order: what you may pay, then the model's valuation. */
const byBand = (board: BoardPayload) => (a: PriceRow, b: PriceRow) =>
  b.band.p50 - a.band.p50 || adjustedValue(b, board) - adjustedValue(a, board);

/** The listone's order. It falls back to the board's own key so that ties --
 * and a server still serving rows without an fvm -- degrade to the default
 * order rather than to whatever order the object happened to be built in. */
const byFvm = (board: BoardPayload) => (a: PriceRow, b: PriceRow) =>
  (b.fvm ?? 0) - (a.fvm ?? 0) || byBand(board)(a, b);

/** The band's tone against what the room will pay. Colour is a second reading
 * of digits that are already on screen, never the only one. */
function bandTone(row: PriceRow): string {
  if (row.band.p50 <= 0) return "text-neutral-600";              // not in the plan at any price
  const room = row.pressure ? row.pressure.estimate : row.expected_price;
  return row.band.p50 > room ? "text-emerald-400" : "text-amber-400";
}

/** Per class, the unsold top by max price — the on-screen twin of the
 * printed tier board. The row of the selected lot is highlighted. */
export function TierBoard({ board }: { board: BoardPayload }) {
  const [sort, setSort] = useState<SortKey>("band");
  // The id, never the row: the board is re-sent on every auction event, so a
  // dialog left open during a lot has to re-read the live row rather than
  // hold the one that was on screen when it was clicked.
  const [openId, setOpenId] = useState<number | null>(null);
  const index = useMemo(() => anchorIndex(board), [board]);
  const byClass = new Map<string, PriceRow[]>();
  for (const row of Object.values(board.prices)) {
    const rows = byClass.get(row.role_class) ?? [];
    rows.push(row);
    byClass.set(row.role_class, rows);
  }
  const ordered = [
    ...CLASS_ORDER.filter(c => byClass.has(c)),
    ...[...byClass.keys()].filter(c => !CLASS_ORDER.includes(c)).sort(),
  ];
  // Classes the completion still buys come first, in CLASS_ORDER, so a live
  // panel never moves for any reason except its class closing. The finished
  // ones fall to the bottom *reversed*: CLASS_ORDER runs goalkeeper-outwards,
  // so reversing it puts the class that closed most recently nearest the live
  // ones and pushes Por -- done first and least likely to be looked at again --
  // to the very end.
  const planned = (c: string) => (board.composition[c] ?? 0) > 0;
  const classes = [...ordered.filter(planned), ...ordered.filter(c => !planned(c)).reverse()];
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-end gap-2 text-xs text-neutral-600">
        {/* The sort runs before the top-8 slice, so it changes *which* players
            each panel shows, not only their order: by fvm a panel is the
            listone's most valuable unsold, which is a different question from
            the one the band answers. */}
        <span>sort</span>
        <Button
          size="xs"
          variant={sort === "band" ? "secondary" : "ghost"}
          aria-pressed={sort === "band"}
          onClick={() => setSort("band")}
          title="what you may pay, then the model's valuation — the board's own order"
        >
          max price
        </Button>
        <Button
          size="xs"
          variant={sort === "fvm" ? "secondary" : "ghost"}
          aria-pressed={sort === "fvm"}
          onClick={() => setSort("fvm")}
          title="the listone's own market value (Gazzetta FVM, Mantra)"
        >
          fvm
        </Button>
      </div>
      <div className="grid grid-cols-2 xl:grid-cols-3 gap-3">
        {classes.map(cls => {
          const all = byClass.get(cls) ?? [];
          const rows = [...all].sort(sort === "fvm" ? byFvm(board) : byBand(board)).slice(0, TOP);
          // What the completion plans to still buy here, and with what. It is a
          // plan, never a rule: a class with none planned may still be one the
          // pricer *could* take from (j_max > 0) that it simply prefers not to
          // fund. "closed" claimed more than that and was wrong.
          const envelope = board.credits_by_class[cls] ?? 0;
          const want = board.composition[cls] ?? 0;
          return (
            <Card key={cls} className="p-2 bg-neutral-900 border-neutral-800">
              <h3 className="font-semibold text-neutral-300 mb-1">
                {cls} <span className="text-neutral-600 text-xs">· {all.length} unsold</span>
                {want > 0
                  ? <span className="text-neutral-600 text-xs" title={`the completion plans ${want} more here, with ${envelope} credits`}> · take {want} · {envelope}cr</span>
                  : <span className="text-amber-500/70 text-xs" title="the completion buys none here — either the class is full or its credits are better spent elsewhere. Not a rule: a 1-credit body may still be takeable."> · none planned</span>}
                {/* What the pricer cannot count: players who hold this role but
                    were pinned to another class. A "take 2" beside "have 4" is
                    the composition asking for something you can already field. */}
                <span
                  className={`text-xs ${(board.my_coverage?.[cls] ?? 0) === 0 ? "text-red-300" : "text-neutral-600"}`}
                  title={`you own ${board.my_coverage?.[cls] ?? 0} player(s) who can field as ${cls} — counted by role, not by the class the pricer pinned them to`}
                > · have {board.my_coverage?.[cls] ?? 0}</span>
              </h3>
              <table className="w-full text-sm">
                <tbody>
                  {rows.map(r => (
                    <tr
                      key={r.player_id}
                      role="button"
                      tabIndex={0}
                      onClick={() => setOpenId(r.player_id)}
                      onKeyDown={e => {
                        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpenId(r.player_id); }
                      }}
                      title={`${r.name} — open`}
                      className={`cursor-pointer hover:bg-neutral-800/70 focus-visible:outline focus-visible:outline-1 focus-visible:outline-neutral-500 ${r.player_id === board.selected ? "bg-neutral-700/50" : ""}`}
                    >
                      <td className="py-0.5 pr-1 text-neutral-600 tabular-nums">t{r.tier}</td>
                      <td className="py-0.5 pr-2 truncate max-w-40" title={r.name}>
                        {r.name} <span className="text-neutral-600">{r.team_short}</span>
                        <NotPlaying row={r} />
                      </td>
                      <td className={`py-0.5 text-right tabular-nums whitespace-nowrap ${bandTone(r)}`}>
                        {band(r.band)}
                        {(() => {
                          // He is pinned to one class; if another of his roles is one
                          // the completion still buys, show what the pricer paid for
                          // his nearest equal there. See lib/anchor.ts.
                          const a = anchorFor(r, board, index);
                          return a ? (
                            <span
                              className="ml-1 rounded bg-fuchsia-500/15 px-1 text-fuchsia-300"
                              title={`pinned to ${r.role_class}, but he can play ${a.cls}, which the completion is still buying. The pricer paid ${a.band} for ${a.via}, his nearest equal in ${a.cls}. A comparable, not his price.`}
                            >
                              {a.cls} {a.band}
                            </span>
                          ) : null;
                        })()}
                      </td>
                      <td className={`py-0.5 pl-2 text-right tabular-nums ${sort === "fvm" ? "text-sky-300" : "text-sky-300/60"}`} title="listone FVM (Mantra)">
                        {r.fvm || ""}
                      </td>
                      <td className="py-0.5 pl-2 text-right tabular-nums text-neutral-500" title="room likely to">
                        {r.pressure ? r.pressure.estimate : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          );
        })}
      </div>
      <Legend />
      <PlayerDialog
        row={openId === null ? null : board.prices[String(openId)] ?? null}
        board={board}
        onClose={() => setOpenId(null)}
      />
    </div>
  );
}
