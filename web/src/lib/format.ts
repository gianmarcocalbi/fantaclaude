export const band = (b: { p25: number; p50: number; p75: number } | null | undefined): string =>
  b ? `${b.p50} [${b.p25}–${b.p75}]` : "—";
