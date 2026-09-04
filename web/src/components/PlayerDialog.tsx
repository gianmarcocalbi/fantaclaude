import { Dialog } from "radix-ui";
import { Badge } from "@/components/ui/badge";
import { band } from "@/lib/format";
import { adjustedValue, anchorFor, anchorIndex } from "@/lib/anchor";
import { NotPlaying } from "@/components/NotPlaying";
import type { BoardPayload, PriceRow } from "@/api/types";

/** The Mantra roles, spelled out. The codes stay primary everywhere on this
 * page — they are what the listone and the board speak — so the words are
 * secondary, for the one screen where a player is being read rather than
 * scanned. */
const ROLE_NAMES: Record<string, string> = {
  Por: "portiere",
  Dd: "difensore destro",
  Ds: "difensore sinistro",
  Dc: "difensore centrale",
  B: "braccetto",
  E: "esterno",
  M: "mediano",
  C: "centrocampista",
  T: "trequartista",
  W: "ala",
  A: "attaccante",
  Pc: "punta centrale",
};

function Figure({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <div className="text-xs text-neutral-500">{label}</div>
      <div className={`text-2xl tabular-nums ${tone}`}>{value}</div>
    </div>
  );
}

/** Everything the board already knows about one player, on demand.
 *
 * It reads only the board payload — the same row the tier board drew — so it
 * never asks the server for anything and cannot disagree with the panel it
 * was opened from. The pricer's own trace (walk/buy values, the completion)
 * lives behind `asta explain`; this is the room-facing half. */
export function PlayerDialog({ row, board, onClose }: {
  row: PriceRow | null;
  board: BoardPayload;
  onClose: () => void;
}) {
  if (!row) return null;
  const factor = board.adjustments.value_factor[String(row.player_id)];
  const excluded = board.adjustments.excluded.includes(row.player_id);
  const room = row.pressure ? row.pressure.estimate : row.expected_price;
  const anchor = anchorFor(row, board, anchorIndex(board));
  const headroom = row.band.p50 - room;
  return (
    <Dialog.Root open onOpenChange={open => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/70" />
        <Dialog.Content className="fixed left-1/2 top-1/2 max-h-[85vh] w-[min(44rem,92vw)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-neutral-700 bg-neutral-900 p-5 text-neutral-100 shadow-xl focus:outline-none">
          <div className="flex items-baseline gap-3 flex-wrap">
            <Dialog.Title className="text-2xl font-bold">{row.name}</Dialog.Title>
            <span className="text-neutral-400">{row.team_short} · t{row.tier}</span>
            {excluded && <Badge variant="destructive">excluded</Badge>}
            {factor !== undefined && <Badge variant="secondary">adjusted ×{factor}</Badge>}
            <NotPlaying row={row} />
          </div>
          <Dialog.Description className="sr-only">
            Prices, roles and bidding pressure for {row.name}.
          </Dialog.Description>

          <div className="mt-4">
            <div className="text-xs text-neutral-500">
              roles — every Mantra slot he can fill{row.roles.length > 1 && `, ${row.roles.length} of them`}
            </div>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {row.roles.map(r => (
                <span
                  key={r}
                  title={ROLE_NAMES[r] ?? r}
                  className={`rounded px-2 py-0.5 text-sm ${
                    r === row.role_class
                      ? "bg-neutral-100 font-semibold text-neutral-900"
                      : "bg-neutral-800 text-neutral-300"
                  }`}
                >
                  {r} <span className={r === row.role_class ? "text-neutral-600" : "text-neutral-500"}>{ROLE_NAMES[r] ?? ""}</span>
                </span>
              ))}
            </div>
            <div className="mt-1 text-xs text-neutral-600">
              priced as <span className="text-neutral-400">{row.role_class}</span> — the class the board picks by
              demand{row.roles.length > 1 && "; the others are lineup options, and each one beyond the first adds to his value"}
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-end gap-8">
            <div>
              <div className="text-xs text-neutral-500">max price (p50 [p25–p75])</div>
              <div className={`text-4xl font-bold tabular-nums ${
                row.band.p50 <= 0 ? "text-neutral-600" : headroom > 0 ? "text-emerald-400" : "text-amber-400"
              }`}>{band(row.band)}</div>
            </div>
            <Figure label="expected" value={String(row.expected_price)} />
            <Figure label="room likely to" value={row.pressure ? String(row.pressure.estimate) : "—"} />
            <Figure label="apps this season" value={String(row.apps ?? 0)} tone={(row.apps ?? 0) === 0 ? "text-red-300" : ""} />
            <Figure label="listone fvm" value={row.fvm ? String(row.fvm) : "—"} tone="text-sky-300/80" />
            <Figure
              label={factor === undefined ? "model value" : `model value (×${factor})`}
              value={adjustedValue(row, board).toFixed(0)}
            />
          </div>

          {anchor && (
            <p className="mt-3 rounded border border-fuchsia-500/30 bg-fuchsia-500/10 p-2 text-sm text-fuchsia-200">
              He is priced as <span className="font-semibold">{row.role_class}</span>, but he can play{" "}
              <span className="font-semibold">{anchor.cls}</span> — a class the completion is still buying. The pricer
              paid <span className="font-semibold tabular-nums">{anchor.band}</span> for {anchor.via}, his nearest
              equal in {anchor.cls}. Treat that as the ceiling, not the {row.band.p50} above: each player is pinned to
              one class for pricing and the pin does not follow your roster.
            </p>
          )}
          <p className="mt-3 text-sm text-neutral-400">
            {row.band.p50 <= 0
              ? "Not in the plan: the class is either full or its credits are committed elsewhere. If the class is still open, he is a 1-credit body and nothing more."
              : headroom > 0
                ? <>You have <span className="font-semibold text-emerald-400">{headroom}</span> of headroom over what the room is expected to pay.</>
                : <>The room is expected to reach <span className="font-semibold text-amber-400">{room}</span>, at or above your ceiling — let him go.</>}
          </p>

          {row.pressure && row.pressure.bidders.length > 0 && (
            <>
              <div className="mt-4 text-xs text-neutral-500">who can still bid, and how deep</div>
              <ul className="mt-1 space-y-1 text-sm">
                {row.pressure.bidders.map(b => (
                  <li key={b.team_id} className="text-neutral-300">
                    <span className={b.intent === "keen" ? "text-red-400" : b.intent === "reluctant" ? "text-emerald-400" : "text-neutral-400"}>
                      {b.intent}
                    </span>{" "}
                    {b.label}{b.nick ? ` (${b.nick})` : ""} up to <span className="tabular-nums font-semibold">{b.ceiling}</span>
                    <span className="text-neutral-500"> · {b.credits}cr, depth {b.depth}{b.reasons.length > 0 ? ` · ${b.reasons.join(", ")}` : ""}</span>
                  </li>
                ))}
              </ul>
            </>
          )}

          <Dialog.Close className="absolute right-3 top-3 rounded px-2 py-1 text-neutral-500 hover:bg-neutral-800 hover:text-neutral-200" aria-label="close">
            ✕
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
