import { useEffect, useRef, useState } from "react";
import type { BoardPayload, HelloPayload, WsMessage } from "@/api/types";

export interface Live {
  hello: HelloPayload | null;
  board: BoardPayload | null;
  feed: string;
  events: string[];
  connected: boolean;
  /** Why there is no board, when the server can say. `/api/hello` answering
   * 400 used to be discarded here, so the screen sat on "connecting to asta
   * serve…" for good while the reason went only to the serving terminal. */
  error: string | null;
}

const EVENTS_CAP = 200;
const RETRY_INITIAL_MS = 1000;
const RETRY_MAX_MS = 10000;

/** The `detail` of a FastAPI error body, or null. Guarded on purpose: a
 * non-JSON body (a proxy's HTML error page) must not throw here, or the
 * failure the fetch was reporting is replaced by an unhandled rejection. */
function detailOf(body: unknown): string | null {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = (body as Record<string, unknown>).detail;
    if (typeof detail === "string") return detail;
  }
  return null;
}

/** One WebSocket, reconnecting with backoff; a REST /api/hello fetch paints
 * the first frame even if the socket is slow. The server holds the state
 * (live-event requirement 1): reconnects simply re-pull `hello`. */
export function useLive(): Live {
  const [state, setState] = useState<Live>({
    hello: null, board: null, feed: "offline", events: [], connected: false, error: null,
  });
  const retry = useRef(RETRY_INITIAL_MS);
  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    const connect = () => {
      if (closed) return;
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
      ws.onopen = () => { retry.current = RETRY_INITIAL_MS; setState(s => ({ ...s, connected: true })); };
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data) as WsMessage;
        setState(s => {
          // A board frame can arrive before the hello — the server subscribes
          // before it sends one, so that a sale knocked down mid-connect is
          // not lost. Held until the hello lands; App renders on `hello`.
          if (msg.type === "hello") return { ...s, hello: msg.hello, board: msg.hello.board ?? s.board, feed: msg.hello.feed, error: null };
          if (msg.type === "board") return { ...s, board: msg.board, events: [...msg.events, ...s.events].slice(0, EVENTS_CAP) };
          if (msg.type === "error") return { ...s, error: msg.error };
          return { ...s, feed: msg.status };
        });
      };
      ws.onclose = () => {
        setState(s => ({ ...s, connected: false }));
        if (!closed) {
          retryTimer = setTimeout(connect, retry.current);
          retry.current = Math.min(retry.current * 2, RETRY_MAX_MS);
        }
      };
    };
    connect();
    fetch("/api/hello").then(async (r): Promise<{ hello: HelloPayload | null; error: string | null }> => {
      if (r.ok) return { hello: (await r.json()) as HelloPayload, error: null };
      let body: unknown = null;
      try { body = await r.json(); } catch { /* a non-JSON body is not a reason to throw */ }
      return { hello: null, error: detailOf(body) ?? `asta serve answered ${r.status} for /api/hello` };
    }).then(({ hello, error }) => {
      setState(s => {
        if (hello) return s.hello ? s : { ...s, hello, board: hello.board ?? s.board, feed: hello.feed, error: null };
        return s.hello ? s : { ...s, error: s.error ?? error };
      });
    }).catch(() => { /* the socket will bring it */ });
    return () => {
      closed = true;
      if (retryTimer !== null) clearTimeout(retryTimer);
      ws?.close();
    };
  }, []);
  return state;
}
