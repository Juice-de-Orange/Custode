// A compact single-series "change over time" mark for the KPI dashboard (dataviz: sparkline form —
// no axes/legend/grid; the title + hero number name the series, the table below is the accessible
// data view). One hue via currentColor so it is theme-aware (set text-laurus / dark:text-laurus-dark
// on a wrapper). SVG only → no raster weight, respects the bundle budget.

const VB_W = 240;
const VB_H = 48;
const PAD = 4; // inset so the 2px stroke + end dot never clip at the edges

export function Sparkline({
  values,
  label,
  className = "",
}: {
  /** Chronological (oldest → newest); the last point gets the end marker. */
  values: number[];
  /** Accessible summary — the exact values live in the sibling table. */
  label: string;
  className?: string;
}) {
  if (values.length === 0) return null;

  const n = values.length;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min;

  const x = (i: number) => (n === 1 ? VB_W / 2 : PAD + (i / (n - 1)) * (VB_W - 2 * PAD));
  // Flat series (range 0) sits on the vertical centre rather than dividing by zero.
  const y = (v: number) => (range === 0 ? VB_H / 2 : PAD + (1 - (v - min) / range) * (VB_H - 2 * PAD));

  const pts = values.map((v, i) => `${x(i).toFixed(2)},${y(v).toFixed(2)}`);
  const baseline = VB_H - PAD;
  const areaPath = `M ${x(0).toFixed(2)},${baseline} L ${pts.join(" L ")} L ${x(n - 1).toFixed(2)},${baseline} Z`;

  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${VB_W} ${VB_H}`}
      preserveAspectRatio="xMidYMid meet"
      className={`h-auto w-full text-laurus dark:text-laurus-dark ${className}`}
    >
      {/* Soft area for shape, then the line, then the latest-point marker. */}
      <path d={areaPath} fill="currentColor" fillOpacity={0.12} stroke="none" />
      {n > 1 ? (
        <polyline
          points={pts.join(" ")}
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      ) : null}
      <circle cx={x(n - 1)} cy={y(values[n - 1])} r={3} fill="currentColor" />
    </svg>
  );
}
