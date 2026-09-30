import { defineConfig } from "@vite-pwa/assets-generator/config";

// PWA icon pipeline (ADR-0078). Single source: public/favicon.svg (the keeper's-arch keyhole on
// the laurus-green tile). Generated PNGs are COMMITTED to public/ — regenerate with
// `npm run generate:pwa-assets` whenever the favicon/logo changes.
//
// Why per-type treatment matters:
//  - transparent 192/512 ("any" icons): the rounded green tile as-is, tiny padding.
//  - maskable 512: the source scaled into the ~40 % safe zone on a full-bleed #2f5d3a field
//    (Android adaptive icons crop up to a circle — nothing may live near the edges). The tile's
//    rounded corners vanish against the identical green background.
//  - apple-touch-icon 180: same full-bleed treatment, fully OPAQUE — iOS masks the icon itself
//    and renders transparency as black.
export default defineConfig({
  images: ["public/favicon.svg"],
  preset: {
    transparent: {
      sizes: [192, 512],
      padding: 0.05,
    },
    maskable: {
      sizes: [512],
      padding: 0.3,
      resizeOptions: { background: "#2f5d3a" },
    },
    apple: {
      sizes: [180],
      padding: 0.3,
      resizeOptions: { background: "#2f5d3a" },
    },
  },
});
