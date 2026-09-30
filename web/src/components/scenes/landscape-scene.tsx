// A calm „golden hour" landscape silhouette (ADR-0075: Silhouetten + thematische Hintergründe).
// Layered hills + a low sun + pines, drawn entirely from the --scene-* CSS variables so it switches
// to a night palette automatically in dark mode. Decorative (aria-hidden); pair with a scrim
// (.scrim-b) wherever text sits on top so contrast stays AA. Pure vector — no raster weight.
export function LandscapeScene({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 800 360"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id="scene-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--scene-sky-1)" />
          <stop offset="100%" stopColor="var(--scene-sky-2)" />
        </linearGradient>
      </defs>
      <rect width="800" height="360" fill="url(#scene-sky)" />
      <circle cx="618" cy="128" r="46" fill="var(--scene-sun)" opacity="0.9" />
      {/* far ridge */}
      <path
        d="M0 220 C150 172 300 202 450 176 S700 150 800 186 L800 360 L0 360 Z"
        fill="var(--scene-hill-far)"
      />
      {/* mid ridge */}
      <path
        d="M0 270 C180 232 340 276 520 246 S760 262 800 250 L800 360 L0 360 Z"
        fill="var(--scene-hill-mid)"
      />
      {/* pines standing against the mid ridge */}
      <g fill="var(--scene-hill-near)">
        <path d="M90 308 L77 308 L90 266 L103 308 Z" />
        <path d="M142 308 L131 308 L142 274 L153 308 Z" />
        <path d="M636 300 L622 300 L636 256 L650 300 Z" />
      </g>
      {/* near ridge */}
      <path
        d="M0 316 C200 292 420 332 600 306 S780 320 800 312 L800 360 L0 360 Z"
        fill="var(--scene-hill-near)"
      />
    </svg>
  );
}
