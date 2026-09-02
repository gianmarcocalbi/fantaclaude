import { Card } from "@/components/ui/card";
import type { BoardPayload } from "@/api/types";

/** Every team's credits from picks[], never from the feed's budget field —
 * the ⚠ marks picks the pinned run cannot name (credits counted, roles not). */
export function Ledgers({ board }: { board: BoardPayload }) {
  return (
    <Card className="p-2 bg-neutral-900 border-neutral-800 text-sm">
      <h3 className="font-semibold text-neutral-300 mb-1">The room</h3>
      <table className="w-full">
        <thead>
          <tr className="text-neutral-600 text-xs">
            <th className="text-left font-normal">team</th>
            <th className="text-right font-normal">cr</th>
            <th className="text-right font-normal">picks</th>
            <th className="text-right font-normal">gk/mov</th>
          </tr>
        </thead>
        <tbody>
          {board.teams.map(t => (
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
