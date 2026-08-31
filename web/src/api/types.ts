import type { components } from "./schema";

export type BoardPayload = components["schemas"]["BoardPayload"];
export type HelloPayload = components["schemas"]["HelloPayload"];
export type PriceRow = components["schemas"]["PriceRowOut"];
export type Ledger = components["schemas"]["LedgerOut"];
export type Pressure = components["schemas"]["PressureOut"];
export type Lot = components["schemas"]["LotOut"];
export type AdjustResult = components["schemas"]["AdjustResult"];
export type RefreshResult = components["schemas"]["RefreshResult"];

/** The WebSocket envelope. Hand-written: the socket carries the same
 * generated payloads, only this thin union is ours. */
export type WsMessage =
  | { type: "hello"; hello: HelloPayload }
  | { type: "board"; board: BoardPayload; events: string[] }
  | { type: "feed"; status: string };
