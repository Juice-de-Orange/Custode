// Onboarding presets (P8-S2, Roadmap Phase 8). Curated, bilingual household starter kits: a set of
// rooms + typical task templates per household type (solo / family / shared flat). Applying one seeds
// the fresh household via the normal tasks endpoints (POST rooms, then templates), so the names land
// in the user's language — same approach as the starter recipes (lib/starters.ts).

type Bilingual = { de: string; en: string };

type PresetRoom = {
  slug: string; // local reference so a template can point at a room before its server id exists
  name: Bilingual;
  icon: string;
  decay_days: number; // heatmap freshness window (1..3650)
};

type PresetTemplate = {
  title: Bilingual;
  points: number;
  room?: string; // PresetRoom.slug, or undefined for a household-wide chore
  outdoor?: boolean;
  rotation?: "fair" | "fixed" | "open";
};

export type PresetId = "solo" | "family" | "shared";

type Preset = {
  id: PresetId;
  rooms: PresetRoom[];
  templates: PresetTemplate[];
};

export type LocalizedPreset = {
  id: PresetId;
  rooms: { slug: string; name: string; icon: string; decay_days: number }[];
  templates: {
    title: string;
    points: number;
    room?: string;
    outdoor: boolean;
    rotation: "fair" | "fixed" | "open";
  }[];
};

const KITCHEN: PresetRoom = { slug: "kitchen", name: { de: "Küche", en: "Kitchen" }, icon: "🍳", decay_days: 3 };
const BATH: PresetRoom = { slug: "bath", name: { de: "Bad", en: "Bathroom" }, icon: "🛁", decay_days: 7 };
const LIVING: PresetRoom = { slug: "living", name: { de: "Wohnzimmer", en: "Living room" }, icon: "🛋️", decay_days: 7 };

export const PRESETS: Preset[] = [
  {
    id: "solo",
    rooms: [
      KITCHEN,
      BATH,
      LIVING,
      { slug: "bedroom", name: { de: "Schlafzimmer", en: "Bedroom" }, icon: "🛏️", decay_days: 14 },
    ],
    templates: [
      { title: { de: "Müll rausbringen", en: "Take out the rubbish" }, points: 5 },
      { title: { de: "Wäsche waschen", en: "Do the laundry" }, points: 10 },
      { title: { de: "Küche aufräumen", en: "Tidy the kitchen" }, points: 8, room: "kitchen" },
      { title: { de: "Bad putzen", en: "Clean the bathroom" }, points: 15, room: "bath" },
      { title: { de: "Staubsaugen", en: "Vacuum" }, points: 10, room: "living" },
    ],
  },
  {
    id: "family",
    rooms: [
      KITCHEN,
      BATH,
      LIVING,
      { slug: "kids", name: { de: "Kinderzimmer", en: "Kids' room" }, icon: "🧸", decay_days: 7 },
      { slug: "garden", name: { de: "Garten", en: "Garden" }, icon: "🌳", decay_days: 14 },
    ],
    templates: [
      { title: { de: "Müll & Altglas", en: "Rubbish & recycling" }, points: 5, room: "kitchen" },
      { title: { de: "Tisch decken", en: "Set the table" }, points: 3, room: "kitchen" },
      { title: { de: "Spülmaschine ausräumen", en: "Empty the dishwasher" }, points: 4, room: "kitchen" },
      { title: { de: "Bad putzen", en: "Clean the bathroom" }, points: 15, room: "bath" },
      { title: { de: "Staubsaugen", en: "Vacuum" }, points: 10, room: "living" },
      { title: { de: "Wäsche waschen", en: "Do the laundry" }, points: 10 },
      { title: { de: "Kinderzimmer aufräumen", en: "Tidy the kids' room" }, points: 6, room: "kids" },
      { title: { de: "Rasen mähen", en: "Mow the lawn" }, points: 20, room: "garden", outdoor: true },
    ],
  },
  {
    id: "shared",
    rooms: [
      { ...KITCHEN, decay_days: 2 },
      { ...BATH, decay_days: 5 },
      { slug: "common", name: { de: "Gemeinschaftsraum", en: "Common room" }, icon: "👥", decay_days: 7 },
      { slug: "hallway", name: { de: "Flur", en: "Hallway" }, icon: "🚪", decay_days: 14 },
    ],
    // Shared chores rotate fairly (KONZEPT — WG-Putzplan): rotation "fair".
    templates: [
      { title: { de: "Müll & Altglas", en: "Rubbish & recycling" }, points: 5, room: "kitchen", rotation: "fair" },
      { title: { de: "Küche putzen", en: "Clean the kitchen" }, points: 12, room: "kitchen", rotation: "fair" },
      { title: { de: "Spülmaschine", en: "Dishwasher" }, points: 4, room: "kitchen", rotation: "fair" },
      { title: { de: "Bad putzen", en: "Clean the bathroom" }, points: 15, room: "bath", rotation: "fair" },
      { title: { de: "Gemeinschaftsraum aufräumen", en: "Tidy the common room" }, points: 10, room: "common", rotation: "fair" },
      { title: { de: "Flur & Treppe wischen", en: "Mop hallway & stairs" }, points: 8, room: "hallway", rotation: "fair" },
    ],
  },
];

export function localizePreset(preset: Preset, locale: string): LocalizedPreset {
  const lang: "de" | "en" = locale.startsWith("en") ? "en" : "de";
  return {
    id: preset.id,
    rooms: preset.rooms.map((room) => ({
      slug: room.slug,
      name: room.name[lang],
      icon: room.icon,
      decay_days: room.decay_days,
    })),
    templates: preset.templates.map((tpl) => ({
      title: tpl.title[lang],
      points: tpl.points,
      room: tpl.room,
      outdoor: tpl.outdoor ?? false,
      rotation: tpl.rotation ?? "open",
    })),
  };
}
