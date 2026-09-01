import { useLive } from "./ws";
import { MappingGate } from "./components/MappingGate";
import { StatusBar } from "./components/StatusBar";
import { Problems } from "./components/Problems";
import { LotPanel } from "./components/LotPanel";
import { TierBoard } from "./components/TierBoard";
import { MyPanel } from "./components/MyPanel";
import { AdjustForm } from "./components/AdjustForm";
import { Ledgers } from "./components/Ledgers";
import { EventLog } from "./components/EventLog";

export default function App() {
  const live = useLive();
  // No hello and a reason for it: say the reason. Rendering "connecting…"
  // forever over a server that already answered 400 is the one outcome that
  // tells the operator nothing at all, mid-auction, with the answer sitting
  // in a terminal they are not looking at.
  if (!live.hello && live.error) {
    return (
      <div className="min-h-screen bg-neutral-950 p-8 text-neutral-300">
        <div className="max-w-2xl space-y-3">
          <h1 className="text-lg font-semibold text-red-400">asta serve cannot open the board</h1>
          <p className="whitespace-pre-wrap font-mono text-sm text-neutral-200">{live.error}</p>
          <p className="text-sm text-neutral-500">
            The serving terminal has the same message. Fix the source and restart <code>asta serve</code>;
            this page reconnects on its own. The printed tier board is the backstop meanwhile.
          </p>
        </div>
      </div>
    );
  }
  if (!live.hello) return <div className="min-h-screen bg-neutral-950 text-neutral-400 p-8">connecting to asta serve&hellip;</div>;
  if (live.hello.phase === "pending" || !live.board) return <MappingGate hello={live.hello} connected={live.connected} />;
  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <StatusBar hello={live.hello} board={live.board} feed={live.feed} connected={live.connected} />
      <Problems board={live.board} />
      <main className="grid grid-cols-12 gap-3 p-3">
        <section className="col-span-12 lg:col-span-8 space-y-3">
          <LotPanel board={live.board} />
          <TierBoard board={live.board} />
        </section>
        <aside className="col-span-12 lg:col-span-4 space-y-3">
          <MyPanel board={live.board} />
          <AdjustForm board={live.board} />
          <Ledgers board={live.board} />
          <EventLog events={live.events} />
        </aside>
      </main>
    </div>
  );
}
