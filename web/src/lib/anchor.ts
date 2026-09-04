import type { BoardPayload, PriceRow } from "@/api/types";

/** What a multi-role player would be worth in a class he is *not* pinned to.
 *
 * `pin_class` gives every player exactly one class, chosen from league-wide
 * module demand when the run was written, and never reconsidered as my roster
 * fills (model/demand.py: "the exact matching for the player on the block is
 * the auction's job"). So once a class is full, a player pinned there shows a
 * band of 0 even when another of his roles is one the completion still buys.
 *
 * This never invents a price. It reads the band the pricer *did* compute for
 * the nearest-valued player who is correctly pinned to that other class, and
 * offers it as a comparable. It is an anchor, labelled as one — the pricer
 * remains the only thing that computes a number.
 */
export type Anchor = { cls: string; band: number; via: string };

/** His value as the board priced him. The server used to send the band from
 * the pricer (which saw the adjustment layer) but `value_p50` straight off the
 * run (which did not), and this helper re-applied the factor. Since 2026-09-04
 * the row's `value_p50` already carries the adjustment (advisor.Board._row),
 * so applying `value_factor` again here would double-count it. Kept as the one
 * accessor everything on screen reads a value through. */
export function adjustedValue(row: PriceRow, _board: BoardPayload): number {
  return row.value_p50;
}

/** class -> its unsold players, by value ascending, with the band each got. */
export function anchorIndex(board: BoardPayload): Map<string, PriceRow[]> {
  const byClass = new Map<string, PriceRow[]>();
  for (const r of Object.values(board.prices)) {
    const rows = byClass.get(r.role_class) ?? [];
    rows.push(r);
    byClass.set(r.role_class, rows);
  }
  for (const rows of byClass.values()) rows.sort((a, b) => adjustedValue(a, board) - adjustedValue(b, board));
  return byClass;
}

/** The best comparable across every role he holds but is not pinned to, or
 * null when none beats the band he already has. Only classes the completion
 * is still buying count — a class it has finished is no better than his own. */
export function anchorFor(row: PriceRow, board: BoardPayload, index: Map<string, PriceRow[]>): Anchor | null {
  let best: Anchor | null = null;
  for (const cls of row.roles) {
    if (cls === row.role_class) continue;
    if ((board.composition[cls] ?? 0) <= 0) continue;
    const peers = index.get(cls);
    if (!peers || peers.length === 0) continue;
    // nearest value, binary search over the ascending values
    const mine = adjustedValue(row, board);
    let lo = 0, hi = peers.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (adjustedValue(peers[mid], board) < mine) lo = mid + 1; else hi = mid;
    }
    const near = [peers[lo], peers[Math.max(0, lo - 1)]]
      .sort((a, b) => Math.abs(adjustedValue(a, board) - mine) - Math.abs(adjustedValue(b, board) - mine))[0];
    if (!near) continue;
    if (!best || near.band.p50 > best.band) best = { cls, band: near.band.p50, via: near.name };
  }
  // Only worth showing when it says something his own band does not.
  return best && best.band > row.band.p50 ? best : null;
}
