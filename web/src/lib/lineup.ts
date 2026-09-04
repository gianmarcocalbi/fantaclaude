import type { BoardPayload } from "@/api/types";

export type Slot = { cls: string; player: SquadMember | null; half: boolean };
export type SquadMember = BoardPayload["my_squad"][number];

/** The slots a module puts on the pitch.
 *
 * `module_demand` is fractional because the guides read the same formation
 * differently — a 3-4-1-2 is 1.5 C to some and 1 to others. Rounding each
 * class to its nearest whole slot reproduces the modal reading; a class left
 * on a half is shown as one, marked, because it is a shirt that exists in
 * some readings and not others. Total is capped at eleven. */
export function slotsFor(board: BoardPayload, module: string): { cls: string; half: boolean }[] {
  const demand = board.module_demand?.[module] ?? {};
  const out: { cls: string; half: boolean }[] = [];
  for (const [cls, n] of Object.entries(demand)) {
    const whole = Math.floor(n + 1e-9);
    for (let i = 0; i < whole; i++) out.push({ cls, half: false });
    if (n - whole > 1e-9) out.push({ cls, half: true });
  }
  // Whole slots before half ones, so an eleven-man cap drops the uncertain shirt.
  out.sort((a, b) => Number(a.half) - Number(b.half));
  return out.slice(0, 11);
}

/** Maximum bipartite matching (Kuhn's) between slots and my squad.
 *
 * Greedy filling gets this wrong: a three-role player taken for the first
 * slot he fits can leave a single-role team-mate with nowhere to go. Kuhn's
 * augmenting paths give the true maximum, so an empty slot in the result is
 * one the squad genuinely cannot cover — not an artifact of the order. */
export function fillModule(board: BoardPayload, module: string): Slot[] {
  const slots = slotsFor(board, module);
  const squad = board.my_squad ?? [];
  const takenBy: (number | null)[] = slots.map(() => null);   // slot -> squad index

  const tryAssign = (p: number, seen: boolean[]): boolean => {
    for (let s = 0; s < slots.length; s++) {
      if (seen[s] || !squad[p].roles.includes(slots[s].cls)) continue;
      seen[s] = true;
      if (takenBy[s] === null || tryAssign(takenBy[s]!, seen)) {
        takenBy[s] = p;
        return true;
      }
    }
    return false;
  };
  // Most constrained first only affects which equally-sized matching we land
  // on, never its size — it just reads better: specialists keep their shirt.
  const order = squad.map((_, i) => i).sort((a, b) => squad[a].roles.length - squad[b].roles.length);
  for (const p of order) tryAssign(p, slots.map(() => false));

  return slots.map((s, i) => ({ ...s, player: takenBy[i] === null ? null : squad[takenBy[i]!] }));
}
