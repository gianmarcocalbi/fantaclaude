import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { HelloPayload } from "@/api/types";

const KEY = (code: string | null) => `fantaclaude-mapping-${code ?? "session"}`;

/** The two identity joins the feed cannot supply (spec): which team is mine,
 * and which dossier each rival maps to. Asked at every connect; this
 * browser's localStorage pre-fills the last answer — the server persists
 * nothing of it, so a lost cache costs one screen of re-selection. */
export function MappingGate({ hello, connected }: { hello: HelloPayload; connected: boolean }) {
  const [mine, setMine] = useState<number | null>(hello.mapping?.mine ?? null);
  const [nicks, setNicks] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(KEY(hello.session_code)) ?? "null");
      if (saved) { setMine(saved.mine); setNicks(saved.nicks ?? {}); }
    } catch { /* pre-fill only */ }
  }, [hello.session_code]);

  const submit = async () => {
    if (mine === null) { setError("pick your team"); return; }
    setError(null);
    const clean = Object.fromEntries(Object.entries(nicks).filter(([id, v]) => v && Number(id) !== mine));
    let resp: Response;
    try {
      resp = await fetch("/api/mapping", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ mine, nicks: clean }),
      });
    } catch (e) {                 // a dead server rejects the fetch itself; say so rather than nothing
      setError(`the server did not answer: ${String(e)} — is \`asta serve\` still up?`);
      return;
    }
    if (!resp.ok) {
      let detail = `mapping refused (${resp.status})`;
      try { detail = (await resp.json()).detail ?? detail; } catch { /* a non-JSON error body keeps the status message */ }
      setError(detail);
      return;
    }
    try { localStorage.setItem(KEY(hello.session_code), JSON.stringify({ mine, nicks: clean })); } catch { /* fine */ }
    setSubmitted(true);
  };

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 p-8">
      <Card className="max-w-2xl mx-auto p-6 space-y-4 bg-neutral-900 border-neutral-700">
        <div className="flex items-center justify-between gap-4">
          <h1 className="text-xl font-semibold">Who is who?</h1>
          <span className="flex items-center gap-1.5 text-xs text-neutral-400">
            <span className={`inline-block w-2 h-2 rounded-full ${connected ? "bg-emerald-500" : "bg-amber-500"}`} title={`socket: ${connected ? "connected" : "reconnecting"}`} />
            {connected ? "socket connected" : "socket reconnecting"}
          </span>
        </div>
        <p className="text-sm text-neutral-400">{hello.run}</p>
        {hello.league_conflicts.map(c => (
          <p key={c} className="text-amber-400 text-sm border border-amber-700 rounded p-2">SESSION &ne; LEAGUE: {c}</p>
        ))}
        {hello.note && <p className="text-amber-400 text-sm">{hello.note}</p>}
        {hello.teams.length === 0 && (
          <p className="text-neutral-400">waiting for the first snapshot&hellip; (feed: {hello.feed})</p>
        )}
        <table className="w-full text-sm">
          <tbody>
            {hello.teams.map(t => (
              <tr key={t.team_id} className="border-b border-neutral-800">
                <td className="py-2 pr-2">
                  <input type="radio" name="mine" checked={mine === t.team_id} onChange={() => setMine(t.team_id)} />
                </td>
                <td className="py-2 pr-4">{t.label} <span className="text-neutral-500">(team {t.team_id})</span></td>
                <td className="py-2">
                  <select
                    className="bg-neutral-950 border border-neutral-700 rounded px-2 py-1 w-full disabled:opacity-40"
                    value={nicks[t.team_id] ?? ""} disabled={mine === t.team_id}
                    onChange={e => setNicks({ ...nicks, [t.team_id]: e.target.value })}>
                    <option value="">&mdash; no dossier &mdash;</option>
                    {hello.participants.map(n => <option key={n} value={n}>{n}</option>)}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {error && <p className="text-red-400 text-sm">{error}</p>}
        {submitted && !connected && (
          <p className="text-amber-400 text-sm border border-amber-700 rounded p-2">
            mapping saved &mdash; waiting for the socket to reconnect before the board opens
          </p>
        )}
        <Button onClick={submit} disabled={hello.teams.length === 0}>Open the board</Button>
        <p className="text-xs text-neutral-500">
          The radio is my team; each rival can point at a dossier under kb/league/participants.
          Skipping the dossiers only costs the pressure model its priors.
        </p>
      </Card>
    </div>
  );
}
