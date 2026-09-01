import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { AdjustResult, BoardPayload, RefreshResult } from "@/api/types";

/** Every reachable error on /api/adjust and /api/refresh (PhaseError 409,
 * UsageError 422, AdjustmentsError/SessionError 400, plus the inline 422)
 * answers `{"detail": <string>}` -- not FastAPI's own array-shaped
 * HTTPValidationError, which this form's state cannot trigger (that needs a
 * body that fails pydantic parsing before the handler runs). So this is its
 * own narrow shape, checked at runtime, rather than a generated one. */
type ApiErrorBody = { detail: string };
const hasStringDetail = (x: unknown): x is ApiErrorBody =>
  typeof x === "object" && x !== null && typeof (x as { detail?: unknown }).detail === "string";

/** The error body is *not* always JSON: an exception none of the four handlers
 * in app.py names (an OSError out of write_state, say) is FastAPI's own
 * PlainTextResponse("Internal Server Error"). A bare `await resp.json()`
 * there rejects unhandled and the screen says nothing at all — the one thing
 * this form must never do, since it is used all night. */
const refusal = async (resp: Response): Promise<string> => {
  try {
    const body: unknown = await resp.json();
    if (hasStringDetail(body)) return body.detail;
  } catch { /* a non-JSON error body keeps the status message */ }
  return `refused (${resp.status})`;
};

/** The dashboard's third of the one adjustments file: value / exclude /
 * target, always with a reason, POSTed to the one writer (the server).
 * The refresh button is the hand-edited-file case (live-event req. 6). */
export function AdjustForm({ board }: { board: BoardPayload }) {
  const [type, setType] = useState<"exclude" | "value" | "target">("exclude");
  const [player, setPlayer] = useState("");
  const [factor, setFactor] = useState("0.85");
  const [cls, setCls] = useState("Dc");
  const [count, setCount] = useState("4");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const classes = [...new Set(Object.values(board.prices).map(r => r.role_class))].sort();

  const submit = async () => {
    if (busy) return;
    setBusy(true);                                    // a double-click would append two entries to adjustments.yml
    setNote(null);
    const body: Record<string, unknown> = { type, reason };
    if (type === "target") { body["class"] = cls; body.count = Number(count); }
    else body.player = player;
    if (type === "value") body.factor = Number(factor);
    try {
      const resp = await fetch("/api/adjust", {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
      });
      if (resp.ok) {
        const out: AdjustResult = await resp.json();
        setNote(`applied: ${out.described}`);
        setPlayer(""); setReason("");
        return;
      }
      setNote(await refusal(resp));
    } catch (e) {                                     // a dead server: say so, never fail silently
      setNote(`the server did not answer: ${String(e)} — is \`asta serve\` still up?`);
    } finally {
      setBusy(false);
    }
  };
  const refresh = async () => {
    if (busy) return;
    setBusy(true);
    setNote(null);
    try {
      const resp = await fetch("/api/refresh", { method: "POST" });
      if (resp.ok) {
        const out: RefreshResult = await resp.json();   // typed against the 200 contract; no field is read yet
        void out;
        setNote("refreshed from adjustments.yml and the dossiers");
        return;
      }
      setNote(await refusal(resp));
    } catch (e) {
      setNote(`the server did not answer: ${String(e)} — is \`asta serve\` still up?`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-3 bg-neutral-900 border-neutral-800 text-sm space-y-2">
      <h3 className="font-semibold text-neutral-300">Adjust</h3>
      <div className="flex gap-2">
        {(["exclude", "value", "target"] as const).map(t => (
          <Button key={t} size="sm" variant={type === t ? "default" : "outline"} onClick={() => setType(t)}>
            {t}
          </Button>
        ))}
      </div>
      {type !== "target" ? (
        <>
          <Input list="adjust-players" value={player} onChange={e => setPlayer(e.target.value)}
                 placeholder='player, the listone way ("Martinez L.")' />
          <datalist id="adjust-players">
            {Object.values(board.prices).map(r => <option key={r.player_id} value={r.name} />)}
          </datalist>
        </>
      ) : (
        <div className="flex gap-2">
          <select value={cls} onChange={e => setCls(e.target.value)}
                  className="bg-neutral-950 border border-neutral-700 rounded px-2 py-1">
            {classes.map(c => <option key={c}>{c}</option>)}
          </select>
          <Input className="w-20" type="number" min="0" value={count} onChange={e => setCount(e.target.value)} />
        </div>
      )}
      {type === "value" && (
        <Input className="w-24" type="number" step="0.05" min="0.05" max="2"
               value={factor} onChange={e => setFactor(e.target.value)} />
      )}
      <Input value={reason} onChange={e => setReason(e.target.value)}
             placeholder="reason — the auction record explains itself" />
      <div className="flex gap-2">
        <Button size="sm" onClick={submit} disabled={busy || !reason || (type !== "target" && !player)}>
          {busy ? "…" : "apply"}
        </Button>
        <Button size="sm" variant="outline" onClick={refresh} disabled={busy}
                title="reread adjustments.yml and the dossiers, re-price everything">refresh</Button>
      </div>
      {note && <p className="text-neutral-400">{note}</p>}
    </Card>
  );
}
