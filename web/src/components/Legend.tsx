/** What the tier board's four columns mean, folded away until asked for.
 *
 * A plain <details>: it is foldable, keyboard-reachable and screen-reader
 * correct without a dependency, and the board is the one place on this page
 * where a number's meaning is not self-evident — three of the four columns
 * are prices measured against different things.
 *
 * The colour is a second encoding of the band, never the only one: the digits
 * carry the same fact for anyone who cannot separate the hues. */
export function Legend() {
  return (
    <details className="group rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm">
      <summary className="cursor-pointer list-none text-neutral-500 hover:text-neutral-300 select-none">
        <span className="inline-block transition-transform group-open:rotate-90">›</span> how to read this board
      </summary>
      <dl className="mt-3 grid gap-x-4 gap-y-2 sm:grid-cols-[auto_1fr] text-neutral-400">
        <dt className="tabular-nums text-neutral-600">t2</dt>
        <dd>
          <span className="text-neutral-300">tier</span> — value-gap groups inside the role class, cut where the
          class's value curve drops most. t1 is the top group; the tail all lands in the last tier.
        </dd>

        <dt className="tabular-nums text-emerald-400">42 [31–55]</dt>
        <dd>
          <span className="text-neutral-300">your max price</span> — p50, with p25–p75 around it. The only number
          here that is a decision.
          <span className="mt-1 block text-neutral-500">
            <span className="text-emerald-400">green</span> the room's price is below your ceiling — headroom, bid ·{" "}
            <span className="text-amber-400">amber</span> the room outbids you — let him go ·{" "}
            <span className="text-neutral-600">grey</span> not in the plan
          </span>
        </dd>

        <dt className="tabular-nums text-sky-300/70">fvm</dt>
        <dd>
          <span className="text-neutral-300">the listone's own market value</span> (Gazzetta FVM, Mantra). Reference
          only — it is not what you should pay and it is not the model's valuation.
        </dd>

        <dt className="tabular-nums text-neutral-500">room</dt>
        <dd>
          <span className="text-neutral-300">what the room will push it to</span> — the expected price plus whatever
          the live bidders' appetite adds. Your edge is the gap between this and your max.
        </dd>

        <dt className="tabular-nums text-red-300">0 apps</dt>
        <dd>
          <span className="text-neutral-300">he has not played this season</span>. The projection cannot see this: its
          presenze rate is a ratio over the seasons he <em>appeared in</em>, so not playing never lowers it, and last
          season's regular is projected forward on zero minutes. Shown beside the value, never folded into it. Thin
          evidence — an injured starter looks the same as a dropped one.
        </dd>

        <dt className="tabular-nums text-fuchsia-300">T 88</dt>
        <dd>
          <span className="text-neutral-300">what he is worth in another of his roles</span>. Every player is pinned to
          one class for pricing, and the pin is fixed when the run is written — it never follows your roster. So a
          player whose class is full reads 0 even when a role he also holds is one you are still buying. This badge is
          the band the pricer <em>did</em> pay for his nearest equal in that class: a comparable, not his price.
        </dd>

        <dt className="tabular-nums text-neutral-600">0 [0–0]</dt>
        <dd>
          <span className="text-neutral-300">two different things</span>, told apart by the class header.{" "}
          <span className="text-neutral-300">take N · Ncr</span> means the completion is still buying here, and a 0
          band is <span className="text-neutral-300">take him at 1, not 2</span>.{" "}
          <span className="text-neutral-300">none planned</span> means it buys nobody here — either the class is full
          or its credits go further elsewhere. That is a plan, not a rule: occupancy is counted by the class each
          player was <em>pinned</em> to, which can differ from the roles he can actually field.
        </dd>
      </dl>
    </details>
  );
}
