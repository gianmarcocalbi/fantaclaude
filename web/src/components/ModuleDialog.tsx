import { Dialog } from "radix-ui";
import { fillModule } from "@/lib/lineup";
import type { BoardPayload } from "@/api/types";

/** One formation, and how far the squad you own gets through it.
 *
 * The lineup is a maximum matching (lib/lineup.ts), so a red slot is one the
 * squad genuinely cannot cover under *this* module — never an artifact of the
 * order players were tried in. Switching module re-runs it, which is the
 * point: the same fifteen players fill 4-3-3 and 3-5-2 differently, and the
 * gap you must buy is whichever the formations you actually intend to play
 * leave open. */
export function ModuleDialog({ board, module, onPick, onClose }: {
  board: BoardPayload;
  module: string | null;
  onPick: (m: string) => void;
  onClose: () => void;
}) {
  if (!module) return null;
  const slots = fillModule(board, module);
  const filled = slots.filter(s => s.player).length;
  const holes = slots.filter(s => !s.player);
  return (
    <Dialog.Root open onOpenChange={o => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/70" />
        <Dialog.Content className="fixed left-1/2 top-1/2 max-h-[85vh] w-[min(40rem,92vw)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-neutral-700 bg-neutral-900 p-5 text-neutral-100 shadow-xl focus:outline-none">
          <Dialog.Title className="text-2xl font-bold">{module}</Dialog.Title>
          <Dialog.Description className="text-sm text-neutral-400">
            {filled} of {slots.length} shirts covered by the {board.my_squad?.length ?? 0} players you own.
          </Dialog.Description>

          <div className="mt-3 flex flex-wrap gap-1.5">
            {(board.modules ?? []).map(m => (
              <button
                key={m}
                onClick={() => onPick(m)}
                aria-pressed={m === module}
                className={`rounded px-2 py-0.5 text-sm tabular-nums ${
                  m === module ? "bg-neutral-100 font-semibold text-neutral-900" : "bg-neutral-800 text-neutral-300 hover:bg-neutral-700"
                }`}
              >
                {m}
              </button>
            ))}
          </div>

          <table className="mt-4 w-full text-sm">
            <tbody>
              {slots.map((s, i) => (
                <tr key={i} className={s.player ? "" : "text-red-300"}>
                  <td className="w-12 py-0.5 text-neutral-500">
                    {s.cls}{s.half && <span className="text-neutral-700" title="this shirt exists in some readings of the formation and not others"> ½</span>}
                  </td>
                  <td className="py-0.5">
                    {s.player
                      ? <>{s.player.name} <span className="text-neutral-600">{s.player.team_short}</span></>
                      : <span className="italic">empty — nobody you own can fill it</span>}
                  </td>
                  <td className="py-0.5 text-right text-xs text-neutral-600">
                    {s.player ? s.player.roles.join("/") : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <p className="mt-3 text-sm text-neutral-400">
            {holes.length === 0
              ? "You can field this formation today."
              : <>Missing <span className="font-semibold text-red-300">{holes.map(h => h.cls).join(", ")}</span> — buy those and this module opens up.</>}
          </p>

          <Dialog.Close className="absolute right-3 top-3 rounded px-2 py-1 text-neutral-500 hover:bg-neutral-800 hover:text-neutral-200" aria-label="close">✕</Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
