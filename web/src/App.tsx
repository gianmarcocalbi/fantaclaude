import { useLive } from "./ws";
import { MappingGate } from "./components/MappingGate";
import { StatusBar } from "./components/StatusBar";
import { Problems } from "./components/Problems";

export default function App() {
  const live = useLive();
  if (!live.hello) return <div className="min-h-screen bg-neutral-950 text-neutral-400 p-8">connecting to asta serve&hellip;</div>;
  if (live.hello.phase === "pending" || !live.board) return <MappingGate hello={live.hello} connected={live.connected} />;
  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <StatusBar hello={live.hello} board={live.board} feed={live.feed} connected={live.connected} />
      <Problems board={live.board} />
      <main className="p-3 text-neutral-400">board components land in Task 11</main>
    </div>
  );
}
