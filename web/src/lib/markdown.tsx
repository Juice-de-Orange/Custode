import type { ReactNode } from "react";

// A deliberately small Markdown subset for operator-provided legal texts (imprint, privacy
// policy — docs/operations.md "Legal pages"). It builds React elements, never HTML strings, so a
// text file can not inject markup or script. Supported: `#`/`##`/`###` headings, paragraphs
// (blank line between them; a single line break stays a line break — addresses), `-`/`*` lists,
// `**bold**`, `*italic*` and `[text](url)` links to http(s) or mailto/tel. Everything else is
// shown as plain text.

const SAFE_LINK = /^(https?:\/\/|mailto:|tel:)/i;
const INLINE = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|\[[^\]]+\]\([^)\s]+\))/g;

function inline(text: string, keyBase: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    const key = `${keyBase}-${i}`;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      return <em key={key}>{part.slice(1, -1)}</em>;
    }
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(part);
    if (link) {
      const [, label, href] = link;
      return SAFE_LINK.test(href) ? (
        <a key={key} href={href} className="text-laurus underline dark:text-laurus-dark" rel="noopener noreferrer">
          {label}
        </a>
      ) : (
        label
      );
    }
    return part;
  });
}

function lines(text: string, keyBase: string): ReactNode[] {
  return text.split("\n").flatMap((line, i) => {
    const nodes = inline(line, `${keyBase}-${i}`);
    return i === 0 ? nodes : [<br key={`${keyBase}-br-${i}`} />, ...nodes];
  });
}

type Block = { kind: "h1" | "h2" | "ul" | "p"; rows: string[] };

/** Group lines into blocks: a heading line stands alone, consecutive list lines form a list,
 *  other consecutive lines a paragraph; a blank line ends a list or paragraph. */
function parse(source: string): Block[] {
  const blocks: Block[] = [];
  let open: Block | null = null;
  for (const line of source.replace(/\r\n?/g, "\n").split("\n")) {
    const heading = /^(#{1,3})\s+(.*)$/.exec(line.trim());
    const item = /^\s*[-*]\s+(.*)$/.exec(line);
    if (!line.trim()) {
      open = null;
    } else if (heading) {
      blocks.push({ kind: heading[1].length === 1 ? "h1" : "h2", rows: [heading[2]] });
      open = null;
    } else if (item) {
      if (open?.kind !== "ul") blocks.push((open = { kind: "ul", rows: [] }));
      open.rows.push(item[1]);
    } else {
      if (open?.kind !== "p") blocks.push((open = { kind: "p", rows: [] }));
      open.rows.push(line.trim());
    }
  }
  return blocks;
}

export function Markdown({ source }: { source: string }) {
  return (
    <>
      {parse(source).map((block, b) => {
        const key = `b${b}`;
        switch (block.kind) {
          case "h1":
            return (
              <h2 key={key} className="font-display text-xl">
                {inline(block.rows[0], key)}
              </h2>
            );
          case "h2":
            return (
              <h3 key={key} className="text-base font-semibold text-tinte dark:text-kalk">
                {inline(block.rows[0], key)}
              </h3>
            );
          case "ul":
            return (
              <ul key={key} className="list-disc space-y-1 pl-5 text-sm text-stein-text">
                {block.rows.map((row, r) => (
                  <li key={`${key}-${r}`}>{inline(row, `${key}-${r}`)}</li>
                ))}
              </ul>
            );
          default:
            return (
              <p key={key} className="text-sm text-stein-text">
                {lines(block.rows.join("\n"), key)}
              </p>
            );
        }
      })}
    </>
  );
}
