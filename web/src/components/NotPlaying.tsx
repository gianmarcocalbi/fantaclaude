/** "He has not played this season."
 *
 * The projection's presenze rate is a ratio over the seasons a player
 * *appeared in* — analysis/projection.py skips a season line with
 * `presenze <= 0` — so no amount of not playing can lower it. A man who was a
 * regular last season is projected forward as one even with zero minutes to
 * his name. This badge is the missing evidence, carried beside the value and
 * never folded into it: the board still says what it says, and you can see the
 * one fact it could not take into account.
 *
 * It is deliberately not a judgement. Two rounds is a thin sample and an
 * injured starter looks exactly like a benched one. */
export function NotPlaying({ row }: { row: { apps?: number; name: string } }) {
  if ((row.apps ?? 0) > 0) return null;
  return (
    <span
      className="ml-1 rounded bg-red-500/20 px-1 text-red-300"
      title={`${row.name} has no appearance this season. The projection cannot see this: its presenze rate is a ratio over the seasons he played, so not playing never lowers it. Thin evidence — an injured starter looks the same as a dropped one.`}
    >
      0 apps
    </span>
  );
}
