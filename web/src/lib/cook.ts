// Pure helpers for cook mode (S6, KONZEPT §5.2 / T1). No DOM — unit-tested.

const LIST_MARKER = /^\s*(?:\d+[.)]|[-*])\s+/;

// Split a recipe's steps_md into individual steps: one per non-empty line/paragraph, leading
// list markers ("1.", "-", …) stripped.
export function parseSteps(stepsMd: string): string[] {
  return stepsMd
    .split(/\n+/)
    .map((line) => line.replace(LIST_MARKER, "").trim())
    .filter((line) => line.length > 0);
}

const LEADING_QTY = /^(\s*)(\d+\/\d+|\d+(?:[.,]\d+)?)/;

function formatQty(value: number): string {
  const rounded = Math.round(value * 100) / 100;
  return Number.isInteger(rounded) ? String(rounded) : String(rounded).replace(".", ",");
}

// Scale the leading quantity of an ingredient line by a factor ("250 g Mehl" ×2 -> "500 g Mehl";
// "1/2 TL Salz" ×2 -> "1 TL Salz"). Lines without a leading number are returned unchanged.
export function scaleLine(rawText: string, factor: number): string {
  const match = rawText.match(LEADING_QTY);
  if (!match) return rawText;
  const numText = match[2];
  let value: number;
  if (numText.includes("/")) {
    const [a, b] = numText.split("/").map(Number);
    value = b ? a / b : 0;
  } else {
    value = Number(numText.replace(",", "."));
  }
  return rawText.replace(LEADING_QTY, `${match[1]}${formatQty(value * factor)}`);
}

const DURATION = /(\d+)\s*(?:minuten|minute|min\b|min\.)/i;

// Detect a "X Minuten/Min" duration in a step (for the tap-to-start timer); null if none.
export function findDurationMinutes(text: string): number | null {
  const match = text.match(DURATION);
  return match ? Number(match[1]) : null;
}
