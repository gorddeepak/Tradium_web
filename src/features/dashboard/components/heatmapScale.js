/* The colour ramp shared by both heatmaps. cap is a caller-supplied parameter,
   not a constant — the two pages saturate at different magnitudes. */

/* The midpoint is light so dark tile labels still pass contrast. */
const NEGATIVE = [0xef, 0x43, 0x43]; // --negative, hsl(0 84% 60%)
const NEUTRAL = [0xd1, 0xd5, 0xdb]; // hsl(220 13% 84%)
const POSITIVE = [0x16, 0xa2, 0x49]; // --positive, hsl(142 76% 36%)

// Where rows land when Yahoo can't resolve a sector, or when the backfill
// hasn't reached them yet. One visible bucket beats silently dropping them.
export const UNCATEGORIZED = "Uncategorized";

/* --accent as a literal — var() doesn't work inside SVG attributes. */
export const HIGHLIGHT = "#0051ff";

/* Passed to the library as `colorScale`, which calls it with the leaf's change
   AND the `cap` prop — so this never closes over a cap of its own. */
export function rampColor(change, cap) {
  // sqrt so small moves pull away from grey quickly; linear leaves everything
  // within a few percent of flat looking identical.
  const t = Math.sqrt(Math.min(Math.abs(change) / cap, 1));
  const pole = change < 0 ? NEGATIVE : POSITIVE;
  const [r, g, b] = NEUTRAL.map((v, i) => Math.round(v + (pole[i] - v) * t));
  return `rgb(${r} ${g} ${b})`;
}
