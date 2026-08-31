import { Card } from "@/components/ui/card";

export function EventLog({ events }: { events: string[] }) {
  return (
    <Card className="p-2 bg-neutral-900 border-neutral-800 text-xs">
      <h3 className="font-semibold text-neutral-300 mb-1 text-sm">Log</h3>
      <ul className="space-y-0.5 max-h-64 overflow-y-auto">
        {events.length === 0 && <li className="text-neutral-600">nothing yet</li>}
        {events.map((e, i) => <li key={events.length - i} className="text-neutral-400">{e}</li>)}
      </ul>
    </Card>
  );
}
