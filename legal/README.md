# Legal pages of your instance

Put the imprint and the privacy policy of **your** instance in this folder as Markdown files.
The `web` container serves them under `/legal/`, and the app shows them on its "Imprint" and
"Privacy" pages (footer links). Without a file the page says that the operator has not provided
one yet.

| File | Shown on |
|---|---|
| `imprint.md` | Imprint (`/impressum`) |
| `privacy.md` | Privacy (`/datenschutz`) |
| `imprint.<lang>.md`, `privacy.<lang>.md` | the same page when the app runs in that language (`de`, `en`); wins over the file without a language |

Files here are ignored by git (`.gitignore`), so `git pull` never overwrites them. To keep them
elsewhere, set `CUSTODE_LEGAL_DIR` in `.env` to that folder. Changes show up on the next page
load; no rebuild or restart is needed.

Markdown subset: `#`, `##`, `###` headings, paragraphs (a single line break stays a line break,
for addresses), `-` lists, `**bold**`, `*italic*`, `[text](https://…)` / `mailto:` / `tel:` links.
No HTML.

`privacy.example.md` is a starting point that describes what Custode itself processes. It is not
legal advice: check it against your setup (which optional modules you enable, where you host,
who your processors are) before you publish it. Details: `docs/operations.md`, "Legal pages".
