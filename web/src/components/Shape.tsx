import { useState } from "react";
import { Card } from "@/components/ui/card";
import { ModuleDialog } from "@/components/ModuleDialog";
import { fillModule } from "@/lib/lineup";
import type { BoardPayload } from "@/api/types";

const CLASS_ORDER = ["Por", "Dc", "Ds", "Dd", "B", "E", "M", "C", "W", "T", "A", "Pc"];

/** The squad against the league's formations.
 *
 * `role_demand[cls][k]` is the share of the league's modules that start a k-th
 * player of that class — so the first number is "how often this class is on
 * the pitch at all", and where it collapses is where the bench begins.
 * `my_coverage[cls]` counts the players I own who hold that role *at all*,
 * which is what a Mantra lineup actually draws from.
 *
 * The pricer cannot use the second number: it counts a squad by the single
 * class it pinned each player to, so a man who can play three roles fills one
 * quota and leaves two looking empty. That is why this panel exists beside the
 * completion rather than inside it — the composition says what the optimiser
 * plans to buy, this says what you could already field. */
export function Shape({ board }: { board: BoardPayload }) {
  const [module, setModule] = useState<string | null>(null);
  const demand = board.role_demand ?? {};
  const mine = board.my_coverage ?? {};
  const classes = CLASS_ORDER.filter(c => demand[c]?.length);
  if (classes.length === 0) return null;
  return (
    <Card className="p-2 bg-neutral-900 border-neutral-800 text-sm">
      <h3 className="font-semibold text-neutral-300 mb-1">
        Shape <span className="text-neutral-600 text-xs">· starters the modules ask for, against what you own</span>
      </h3>
      <table className="w-full">
        <thead>
          <tr className="text-neutral-600 text-xs">
            <th className="text-left font-normal">role</th>
            <th className="text-right font-normal" title="share of the league's modules that start a 1st / 2nd / 3rd of this class">starts 1st · 2nd · 3rd</th>
            <th className="text-right font-normal" title="players you own who hold this role at all">have</th>
            <th className="text-right font-normal" title="what the completion still plans to buy">buy</th>
          </tr>
        </thead>
        <tbody>
          {classes.map(cls => {
            const d = demand[cls] ?? [];
            const have = mine[cls] ?? 0;
            const buy = board.composition[cls] ?? 0;
            // A class the modules genuinely start, that you cannot field at all,
            // is the hole worth money — louder than any band on the board.
            const hole = (d[0] ?? 0) >= 0.5 && have === 0;
            return (
              <tr key={cls} className={hole ? "text-red-300" : ""}>
                <td className="py-0.5">{cls}</td>
                <td className="py-0.5 text-right tabular-nums text-neutral-500">
                  {d.slice(0, 3).map(v => v.toFixed(2)).join(" · ")}
                </td>
                <td className={`py-0.5 text-right tabular-nums ${have === 0 ? "text-red-300" : "text-neutral-200"}`}>{have}</td>
                <td className="py-0.5 text-right tabular-nums text-neutral-500">{buy || "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {board.modules && board.modules.length > 0 && (
        <div className="mt-2">
          <div className="text-xs text-neutral-600">modules — click one to see how you fill it</div>
          <div className="mt-1 flex flex-wrap gap-1">
            {board.modules.map(m => {
              // The chip carries its own verdict: how many of the eleven shirts
              // the squad covers today. Complete formations read green, so the
              // shape you are closest to fielding is visible without opening one.
              const slots = fillModule(board, m);
              const filled = slots.filter(s => s.player).length;
              const ok = filled === slots.length;
              return (
                <button
                  key={m}
                  onClick={() => setModule(m)}
                  title={`${filled} of ${slots.length} shirts covered — click for the lineup`}
                  className={`rounded px-1.5 py-0.5 text-xs tabular-nums hover:bg-neutral-700 ${
                    ok ? "bg-emerald-500/20 text-emerald-300" : "bg-neutral-800 text-neutral-400"
                  }`}
                >
                  {m} <span className={ok ? "text-emerald-400/70" : "text-neutral-600"}>{filled}/{slots.length}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}
      <ModuleDialog board={board} module={module} onPick={setModule} onClose={() => setModule(null)} />
    </Card>
  );
}
