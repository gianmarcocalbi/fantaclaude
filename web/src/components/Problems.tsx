import type { BoardPayload } from "@/api/types";

/** Conflicts and problems are surfaced, never absorbed (spec: "loudly at
 * connect, before bidding opens" — and kept on screen after it). */
export function Problems({ board }: { board: BoardPayload }) {
  const rows = [
    ...board.league_conflicts.map(text => ({ kind: "SESSION ≠ LEAGUE", text })),
    ...board.problems.map(text => ({ kind: "problem", text })),
  ];
  if (rows.length === 0) return null;
  return (
    <div className="px-3 py-1 space-y-1">
      {rows.map((r, i) => (
        <p key={i} className="text-amber-400 text-xs border border-amber-800 rounded px-2 py-1">
          <span className="font-semibold">{r.kind}:</span> {r.text}
        </p>
      ))}
    </div>
  );
}
