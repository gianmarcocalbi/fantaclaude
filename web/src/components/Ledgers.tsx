import { useState } from "react";
import { Card } from "@/components/ui/card";
import type { BoardPayload, Ledger } from "@/api/types";

/** The server sends the room in team_id order — the session's seating order,
 * which is the one order that says nothing about the auction. Credits is the
 * default here instead: who can still outbid you is the question this panel
 * is actually asked during a lot. `seat` puts the original order back. */
type Key = "seat" | "credits" | "picks";

const VALUE: Record<Key, (t: Ledger) => number> = {
  seat: t => t.team_id,
  credits: t => t.credits,
  picks: t => t.picks.length,
};

/** Ascending for the seating order, descending for the two that are amounts —
 * the interesting end of a quantity is the big end. */
const DEFAULT_DESC: Record<Key, boolean> = { seat: false, credits: true, picks: true };

/** Every team's credits from picks[], never from the feed's budget field —
 * the ⚠ marks picks the pinned run cannot name (credits counted, roles not). */
export function Ledgers({ board }: { board: BoardPayload }) {
  const [key, setKey] = useState<Key>("credits");
  const [desc, setDesc] = useState(true);

  const click = (k: Key) => {
    if (k === key) setDesc(d => !d);
    else { setKey(k); setDesc(DEFAULT_DESC[k]); }
  };

  const rows = [...board.teams].sort((a, b) => {
    const d = VALUE[key](a) - VALUE[key](b);
    return (desc ? -d : d) || a.team_id - b.team_id;      // seat breaks every tie, so the order is stable
  });

  const Head = ({ k, label, align }: { k: Key; label: string; align: string }) => (
    <th
      className={`${align} font-normal`}
      aria-sort={key === k ? (desc ? "descending" : "ascending") : "none"}
    >
      <button
        onClick={() => click(k)}
        className={`cursor-pointer hover:text-neutral-300 ${key === k ? "text-neutral-300" : ""}`}
        title={`sort by ${label}`}
      >
        {label}{key === k ? (desc ? " ↓" : " ↑") : ""}
      </button>
    </th>
  );

  return (
    <Card className="p-2 bg-neutral-900 border-neutral-800 text-sm">
      <h3 className="font-semibold text-neutral-300 mb-1">The room</h3>
      <table className="w-full">
        <thead>
          <tr className="text-neutral-600 text-xs">
            <Head k="seat" label="team" align="text-left" />
            <Head k="credits" label="cr" align="text-right" />
            <Head k="picks" label="picks" align="text-right" />
            <th className="text-right font-normal">gk/mov</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(t => (
            <tr key={t.team_id} className={t.team_id === board.me.team_id ? "text-emerald-400" : ""}>
              <td className="py-0.5">{t.label}{t.nick ? ` (${t.nick})` : ""}{t.unknown > 0 ? " ⚠" : ""}</td>
              <td className={`py-0.5 text-right tabular-nums ${t.credits < 0 ? "text-red-400" : ""}`}>{t.credits}</td>
              <td className="py-0.5 text-right tabular-nums">{t.picks.length}</td>
              <td className="py-0.5 text-right tabular-nums">{t.goalkeepers}/{t.outfield}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
