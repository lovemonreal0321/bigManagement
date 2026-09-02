/**
 * Parsing a block of cells pasted out of a spreadsheet.
 *
 * Google Sheets, Excel and Numbers all put tab-separated text on the clipboard:
 * tabs between columns, newlines between rows, and any cell containing a tab or
 * newline wrapped in double quotes with `""` for a literal quote. That is CSV's
 * quoting rules with a tab delimiter, so it needs a real parser rather than
 * `split("\t")` — a pasted job description containing a comma or a line break
 * would otherwise shear the row apart.
 */

/** The columns the sheet can accept from a paste, in display order. */
export const PASTE_FIELDS = [
  "applied_date",
  "company_name",
  "job_title",
  "job_url",
] as const;
export type PasteField = (typeof PASTE_FIELDS)[number];

export interface PastedRow {
  applied_date: string | null;
  company_name: string;
  job_title: string | null;
  job_url: string | null;
}

export interface ParsedPaste {
  rows: PastedRow[];
  /** Which source column supplied each field, for the preview to explain. */
  mapping: Record<PasteField, number | null>;
  /** True when the first line was consumed as a header rather than data. */
  usedHeader: boolean;
  /** Rows dropped for having no company name. */
  skipped: number;
}

/** Split tab-separated clipboard text, honouring quoted cells. */
export function parseDelimited(text: string, delimiter = "\t"): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;

  for (let i = 0; i < text.length; i++) {
    const char = text[i];

    if (quoted) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i++;
        } else {
          quoted = false;
        }
      } else {
        cell += char;
      }
      continue;
    }

    if (char === '"' && cell === "") {
      quoted = true;
    } else if (char === delimiter) {
      row.push(cell);
      cell = "";
    } else if (char === "\r") {
      // Swallow; the \n that follows ends the row.
    } else if (char === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }

  if (cell !== "" || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }

  // A trailing newline leaves one empty row behind.
  return rows.filter((r) => r.some((value) => value.trim() !== ""));
}

const HEADER_PATTERNS: Record<PasteField, RegExp> = {
  applied_date: /^(applied|date|applied\s*date|day|when)$/i,
  company_name: /^(company|company\s*name|employer|organisation|organization)$/i,
  job_title: /^(position|title|job\s*title|role|job|job\s*name)$/i,
  job_url: /^(link|url|job\s*link|job\s*url|posting|job\s*description|jd)$/i,
};

function detectHeader(cells: string[]): Record<PasteField, number | null> | null {
  const mapping: Record<PasteField, number | null> = {
    applied_date: null,
    company_name: null,
    job_title: null,
    job_url: null,
  };
  let hits = 0;

  cells.forEach((raw, index) => {
    const value = raw.trim();
    for (const field of PASTE_FIELDS) {
      if (mapping[field] === null && HEADER_PATTERNS[field].test(value)) {
        mapping[field] = index;
        hits++;
        return;
      }
    }
  });

  // A header has to name the one column that actually matters, or it is data.
  return mapping.company_name !== null && hits >= 1 ? mapping : null;
}

/**
 * Which source column is which, when there is no header row to say so.
 *
 * Filling rightward from the cursor is what a spreadsheet does, and it is wrong
 * here often enough to matter: the blank row's first typeable cell is Company,
 * so pasting a Date/Company/Position/Link block into the obvious place shifted
 * every column left by one — the date became the company, the company became
 * the position, and the position became a link to nowhere.
 *
 * Dates and links announce themselves, so those two columns are found by
 * looking at the data. Whatever is left is text, and text fills rightward from
 * the cursor as before.
 */
function inferMapping(
  body: string[][],
  startColumn: PasteField,
  width: number,
): Record<PasteField, number | null> {
  const mapping: Record<PasteField, number | null> = {
    applied_date: null,
    company_name: null,
    job_title: null,
    job_url: null,
  };

  /** The leftmost unclaimed column where the values mostly look like this. */
  const find = (
    test: (value: string) => boolean,
    claimed: Set<number>,
  ): number | null => {
    for (let index = 0; index < width; index++) {
      if (claimed.has(index)) continue;
      let filled = 0;
      let hits = 0;
      for (const cells of body) {
        const value = (cells[index] ?? "").trim();
        if (!value) continue;
        filled++;
        if (test(value)) hits++;
      }
      // A clear majority, not merely one lucky row: a company called "Meta.ai"
      // should not turn its column into the link column.
      if (filled > 0 && hits / filled >= 0.6) return index;
    }
    return null;
  };

  const claimed = new Set<number>();

  // Dates first. A dotted date can look like a hostname, so resolving it before
  // links keeps it out of the link column.
  const dateColumn = find((value) => normaliseDate(value) !== null, claimed);
  if (dateColumn !== null) {
    mapping.applied_date = dateColumn;
    claimed.add(dateColumn);
  }

  const urlColumn = find(looksLikeUrl, claimed);
  if (urlColumn !== null) {
    mapping.job_url = urlColumn;
    claimed.add(urlColumn);
  }

  // The remainder is prose. It fills the still-unclaimed fields rightward from
  // whichever column the cursor was in.
  let field = PASTE_FIELDS.indexOf(startColumn);
  for (let index = 0; index < width; index++) {
    if (claimed.has(index)) continue;
    while (field < PASTE_FIELDS.length && mapping[PASTE_FIELDS[field]] !== null) {
      field++;
    }
    if (field >= PASTE_FIELDS.length) break;
    mapping[PASTE_FIELDS[field]] = index;
    field++;
  }

  return mapping;
}

const MONTH_NAME =
  /\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b/i;

/** `2026-08-19`, `19/08/2026`, `8/19/2026`, `19 Aug 2026` → `2026-08-19`. */
export function normaliseDate(raw: string): string | null {
  const value = raw.trim();
  if (!value) return null;

  const iso = value.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (iso) return `${iso[1]}-${iso[2].padStart(2, "0")}-${iso[3].padStart(2, "0")}`;

  // Ambiguous slash/dot forms. Day-first unless the first number cannot be a
  // day, which is the reading most of the world uses; an American sheet with
  // 3/14 still resolves correctly because 14 cannot be a month.
  const parts = value.match(/^(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})$/);
  if (parts) {
    const [, a, b, year] = parts;
    let day = Number(a);
    let month = Number(b);
    if (day > 12 && month <= 12) {
      // already day-first
    } else if (month > 12 && day <= 12) {
      [day, month] = [month, day];
    }
    if (month < 1 || month > 12 || day < 1 || day > 31) return null;
    const full = year.length === 2 ? `20${year}` : year;
    return `${full}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  }

  // Anything else is a month-name form ("19 Aug 2026", "Aug 19, 2026"), and
  // only those. `new Date` accepts a startling amount of nonsense — it reads
  // `boards.greenhouse.io/acme/1` as a date in 2001 — so it is only consulted
  // for text that names a month.
  if (!MONTH_NAME.test(value)) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  const year = parsed.getFullYear();
  if (year < 1970 || year > 2200) return null;
  return `${year}-${String(parsed.getMonth() + 1).padStart(2, "0")}-${String(
    parsed.getDate(),
  ).padStart(2, "0")}`;
}

/**
 * Text that is actually a link.
 *
 * The host has to end in a real TLD, which is what keeps `19.08.2026` from
 * reading as a domain — the dotted-date form is common in European sheets and
 * would otherwise be classified as the link column.
 */
const URL_LIKE = /^(?:https?:\/\/)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:[:/?#]\S*)?$/i;

export function looksLikeUrl(raw: string): boolean {
  const value = raw.trim();
  if (!value || /\s/.test(value)) return false;
  return URL_LIKE.test(value);
}

function normaliseUrl(raw: string): string | null {
  const value = raw.trim();
  if (!value) return null;
  // Anything that is not a link is dropped rather than prefixed. Gluing
  // `https://` onto a job title produced `https://Senior Engineer`, a link that
  // goes nowhere and looks deliberate.
  if (!looksLikeUrl(value)) return null;
  return /^https?:\/\//i.test(value) ? value : `https://${value}`;
}

/**
 * Turn clipboard text into rows ready for the bulk endpoint.
 *
 * `startColumn` is the sheet column the cursor was in. Without a header row,
 * pasted columns fill rightward from there — the same thing a spreadsheet does.
 */
export function parsePaste(text: string, startColumn: PasteField): ParsedPaste {
  const grid = parseDelimited(text);
  if (grid.length === 0) {
    return {
      rows: [],
      mapping: {
        applied_date: null,
        company_name: null,
        job_title: null,
        job_url: null,
      },
      usedHeader: false,
      skipped: 0,
    };
  }

  const header = detectHeader(grid[0]);
  const body = header ? grid.slice(1) : grid;

  const width = Math.max(...grid.map((cells) => cells.length));
  const mapping = header ?? inferMapping(body, startColumn, width);

  const rows: PastedRow[] = [];
  let skipped = 0;

  for (const cells of body) {
    const read = (field: PasteField) => {
      const index = mapping[field];
      return index === null || index === undefined ? "" : (cells[index] ?? "");
    };

    const company = read("company_name").trim();
    if (!company) {
      skipped++;
      continue;
    }
    rows.push({
      company_name: company.slice(0, 255),
      job_title: read("job_title").trim().slice(0, 255) || null,
      applied_date: normaliseDate(read("applied_date")),
      job_url: normaliseUrl(read("job_url")),
    });
  }

  return { rows, mapping, usedHeader: Boolean(header), skipped };
}
