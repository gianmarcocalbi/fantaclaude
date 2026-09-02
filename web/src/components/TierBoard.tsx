import { Card } from "@/components/ui/card";
import { band } from "@/lib/format";
import type { BoardPayload, PriceRow } from "@/api/types";

const CLASS_ORDER = ["Por", "Ds", "Dd", "Dc", "B", "E", "M", "C", "W", "T", "A", "Pc"];
const TOP = 8;

/** Per class, the unsold top by max price — the on-screen twin of the
 * printed tier board. The row of the selected lot is highlighted. */
export function TierBoard({ board }: { board: BoardPayload }) {
  const byClass = new Map<string, PriceRow[]>();
  for (const row of Object.values(board.prices)) {
    const rows = byClass.get(row.role_class) ?? [];
    rows.push(row);
    byClass.set(row.role_class, rows);
  }
  const classes = [
    ...CLASS_ORDER.filter(c => byClass.has(c)),
    ...[...byClass.keys()].filter(c => !CLASS_ORDER.includes(c)).sort(),
  ];
  return (
    <div className="grid grid-cols-2 xl:grid-cols-3 gap-3">
      {classes.map(cls => {
        const all = byClass.get(cls) ?? [];
        const rows = [...all].sort((a, b) => b.band.p50 - a.band.p50 || b.value_p50 - a.value_p50).slice(0, TOP);
        return (
          <Card key={cls} className="p-2 bg-neutral-900 border-neutral-800">
            <h3 className="font-semibold text-neutral-300 mb-1">
              {cls} <span className="text-neutral-600 text-xs">· {all.length} unsold</span>
            </h3>
            <table className="w-full text-sm">
              <tbody>
                {rows.map(r => (
                  <tr key={r.player_id} className={r.player_id === board.selected ? "bg-neutral-700/50" : ""}>
                    <td className="py-0.5 pr-1 text-neutral-600 tabular-nums">t{r.tier}</td>
                    <td className="py-0.5 pr-2 truncate max-w-40" title={r.name}>{r.name} <span className="text-neutral-600">{r.team_short}</span></td>
                    <td className="py-0.5 text-right tabular-nums whitespace-nowrap">{band(r.band)}</td>
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
  );
}
