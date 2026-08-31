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
