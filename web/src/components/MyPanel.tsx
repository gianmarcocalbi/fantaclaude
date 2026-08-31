import { Card } from "@/components/ui/card";
import type { BoardPayload } from "@/api/types";

export function MyPanel({ board }: { board: BoardPayload }) {
  const me = board.me;
  const completion = Object.entries(board.composition).filter(([, n]) => n > 0)
    .map(([c, n]) => `${c} ${n}·${board.credits_by_class[c] ?? 0}`).join(", ");
  return (
    <Card className="p-3 bg-neutral-900 border-neutral-600 text-sm space-y-1">
      <div className="flex justify-between items-baseline">
        <span className="font-semibold">{me.label}</span>
        <span className="text-3xl font-bold tabular-nums">{me.credits}<span className="text-sm text-neutral-500">cr</span></span>
      </div>
      <p className="text-neutral-400">
        {me.picks.length} picks · gk {me.goalkeepers} · mov {me.outfield}
        {me.missing_goalkeepers + me.missing_outfield > 0 &&
          ` · still needed: gk ${me.missing_goalkeepers}, mov ${me.missing_outfield}`}
      </p>
      <p className="text-neutral-400">reserve {board.reserve} · budget {board.budget} · completion {completion}</p>
      {board.targets_departed.length > 0 && (
        <p className="text-amber-400">departed from the target at {board.targets_departed.join(", ")}</p>
      )}
      {board.adjustments.count > 0 && (
        <p className="text-neutral-500">{board.adjustments.applied}/{board.adjustments.count} adjustments applied</p>
      )}
    </Card>
  );
}
