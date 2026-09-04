import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { band } from "@/lib/format";
import { NotPlaying } from "@/components/NotPlaying";
import type { BoardPayload } from "@/api/types";

/** The lot on the block, auto-focused from the feed's selectedPlayerId: the
 * band is the decision, the room's estimate is only the moment to stop. */
export function LotPanel({ board }: { board: BoardPayload }) {
  const lot = board.lot;
  if (!lot) return <Card className="p-4 bg-neutral-900 border-neutral-800 text-neutral-500">no lot on the block</Card>;
  const pressure = board.lot_pressure;
  // The lot carries its own fvm; falling back to his tier row keeps the figure
  // on screen when the panel is newer than the server serving it, and costs
  // nothing once it is not. A sold lot leaves the pool, so only the lot's own
  // value covers that case -- which is why it is on the lot at all.
  const fvm = board.lot?.fvm || board.prices[String(lot.player_id)]?.fvm || 0;
  return (
    <Card className="p-4 bg-neutral-900 border-neutral-600">
      <div className="flex items-baseline gap-3 flex-wrap">
        <h2 className="text-2xl font-bold">{lot.name}</h2>
        <NotPlaying row={lot} />
        <span className="text-neutral-400">{lot.team_short} · {lot.roles.join("/")} → {lot.role_class} · t{lot.tier}</span>
        {lot.sold_to !== null && <Badge variant="destructive">sold to team {lot.sold_to}</Badge>}
      </div>
      <div className="mt-2 flex items-end gap-8">
        <div>
          <div className="text-xs text-neutral-500">max price (p50 [p25–p75])</div>
          <div className="text-5xl font-bold tabular-nums">{band(lot.band)}</div>
        </div>
        <div>
          <div className="text-xs text-neutral-500">expected</div>
          <div className="text-2xl tabular-nums">{lot.expected_price ?? "—"}</div>
        </div>
        {pressure && (
          <div>
            <div className="text-xs text-neutral-500">room likely to</div>
            <div className="text-2xl tabular-nums">{pressure.estimate}</div>
          </div>
        )}
        {fvm > 0 && (
          <div>
            <div className="text-xs text-neutral-500">listone fvm</div>
            <div className="text-2xl tabular-nums text-sky-300/80">{fvm}</div>
          </div>
        )}
      </div>
      {pressure && pressure.bidders.length > 0 && (
        <ul className="mt-3 text-sm space-y-1">
          {pressure.bidders.map(b => (
            <li key={b.team_id} className="text-neutral-300">
              <span className={b.intent === "keen" ? "text-red-400" : b.intent === "reluctant" ? "text-emerald-400" : "text-neutral-400"}>
                {b.intent}
              </span>{" "}
              {b.label}{b.nick ? ` (${b.nick})` : ""} up to <span className="tabular-nums font-semibold">{b.ceiling}</span>
              <span className="text-neutral-500"> · {b.credits}cr, depth {b.depth}{b.reasons.length > 0 ? ` · ${b.reasons.join(", ")}` : ""}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
