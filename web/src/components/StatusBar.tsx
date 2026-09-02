import type { BoardPayload, HelloPayload } from "@/api/types";

const DOT: Record<string, string> = {
  live: "bg-emerald-500", reconnecting: "bg-amber-500", offline: "bg-red-500",
  replay: "bg-sky-500", state: "bg-sky-500",
};

/** Feed status is always visible (spec): a silently dead feed and a quiet
 * auction look identical from across the table. */
export function StatusBar({ hello, board, feed, connected }: {
  hello: HelloPayload; board: BoardPayload; feed: string; connected: boolean;
}) {
  const s = board.settings;
  return (
    <header className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2 border-b border-neutral-800 text-sm sticky top-0 bg-neutral-950 z-10">
      <span className={`inline-block w-2.5 h-2.5 rounded-full ${DOT[feed] ?? "bg-neutral-500"}`} title={`feed: ${feed}`} />
      <span className="font-semibold">{hello.session_code ?? hello.mode}</span>
      <span className="text-neutral-400">{feed}{connected ? "" : " · socket reconnecting"}</span>
      <span className="text-neutral-400">{board.run_id} · {board.scenario}</span>
      <span className="text-neutral-400">
        {s.budget}cr · gk {s.goalkeepers[0]}-{s.goalkeepers[1]} · roster {s.size[0]}-{s.size[1]} · {s.team_count} teams ({s.source})
      </span>
      <span className="ml-auto text-neutral-400 tabular-nums">
        market {board.market_credits}cr · inflation {board.inflation.toFixed(2)}
      </span>
    </header>
  );
}
