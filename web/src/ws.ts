import { useEffect, useRef, useState } from "react";
import type { BoardPayload, HelloPayload, WsMessage } from "@/api/types";

export interface Live {
  hello: HelloPayload | null;
  board: BoardPayload | null;
  feed: string;
  events: string[];
  connected: boolean;
}

const EVENTS_CAP = 200;
const RETRY_INITIAL_MS = 1000;
const RETRY_MAX_MS = 10000;

/** One WebSocket, reconnecting with backoff; a REST /api/hello fetch paints
 * the first frame even if the socket is slow. The server holds the state
 * (live-event requirement 1): reconnects simply re-pull `hello`. */
export function useLive(): Live {
  const [state, setState] = useState<Live>({ hello: null, board: null, feed: "offline", events: [], connected: false });
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
          if (msg.type === "hello") return { ...s, hello: msg.hello, board: msg.hello.board ?? s.board, feed: msg.hello.feed };
          if (msg.type === "board") return { ...s, board: msg.board, events: [...msg.events, ...s.events].slice(0, EVENTS_CAP) };
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
    fetch("/api/hello").then(r => (r.ok ? r.json() : null)).then(h => {
      if (h) setState(s => (s.hello ? s : { ...s, hello: h, board: h.board ?? s.board, feed: h.feed }));
    }).catch(() => { /* the socket will bring it */ });
    return () => {
      closed = true;
      if (retryTimer !== null) clearTimeout(retryTimer);
      ws?.close();
    };
  }, []);
  return state;
}
