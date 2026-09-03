"use client";

/**
 * The spreadsheet view of applications.
 *
 * Rows grouped under the day they were applied, with a count on the band, and
 * three editable columns: date, company, job link. Oldest day at the top, so
 * the newest row sits at the bottom next to the blank row you type into.
 *
 * The person tab bar lives in the page, shared with the list and pipeline
 * views (see `components/shared/person-tabs.tsx`).
 *
 * Deliberately narrow. Everything richer — status, interviews, follow-ups,
 * notes — lives on the detail page, one click away from the row.
 */

import {
  Archive,
  ArchiveRestore,
  ArrowUpRight,
  CalendarDays,
  Loader2,
  Plus,
  Search,
  SquareArrowOutUpRight,
  TriangleAlert,
  Undo2,
  X,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";

import { ReadOnlyNote } from "@/components/shared/read-only";
import { Tooltip } from "@/components/ui/overlays";
import { Button, EmptyState, Input, Skeleton } from "@/components/ui/primitives";
import { PasteDialog } from "@/components/applications/paste-dialog";
import { ApiError } from "@/lib/api";
import { parsePaste, type ParsedPaste } from "@/lib/paste-grid";
import { cn } from "@/lib/utils";
import { APPLICATION_STATUS_LABELS } from "@/lib/format";
import {
  useArchiveApplication,
  useBulkDeleteApplications,
  useCreateApplication,
  useUpdateApplication,
} from "@/lib/queries";
import { useUndo, useUndoShortcut } from "@/lib/undo";
import type { ApplicationSheet, SheetRow } from "@/lib/types";

/** The three columns the sheet shows, in order. */
const FIELDS = [
  "applied_date",
  "company_name",
  "job_title",
  "job_url",
] as const;
type Field = (typeof FIELDS)[number];

const COLUMNS: { field: Field; label: string; width: string }[] = [
  { field: "applied_date", label: "Date", width: "w-36" },
  { field: "company_name", label: "Company", width: "w-64" },
  { field: "job_title", label: "Position", width: "w-64" },
  { field: "job_url", label: "Job description link", width: "" },
];

/**
 * Whether this row shares a posting with another.
 *
 * Written defensively: an older backend does not send `duplicate_of` at all,
 * and a version skew during a deploy should not white-screen the sheet over a
 * decoration.
 */
function isDuplicate(row: SheetRow): boolean {
  return (row.duplicate_of?.length ?? 0) > 0;
}

/** Keyed by field, not position — the column order has changed once already. */
const NEW_ROW_PLACEHOLDERS: Record<Field, string> = {
  applied_date: "today",
  company_name: "Type a company to add a row…",
  job_title: "Position",
  job_url: "https://…",
};

/** Column names in prose, for undo labels. */
const COLUMN_LABELS: Record<Field, string> = {
  applied_date: "Date",
  company_name: "Company",
  job_title: "Position",
  job_url: "Job link",
};

/** Sentinel row id for the blank "type here to add" row. */
const NEW_ROW = "__new__";

/**
 * A new row has no job title, because the sheet does not show one. Rather than
 * refuse the row, it is stored with this placeholder and can be named later on
 * the detail page.
 */
const UNTITLED = "Untitled role";

/**
 * How long the blank row waits, after company and link are both filled, before
 * saving itself. Long enough not to fire mid-URL, short enough to feel like the
 * row appeared on its own.
 */
const AUTO_ADD_DELAY_MS = 1200;

/**
 * How much of a position is shown before it is cut short.
 *
 * Long titles ("Senior Staff Software Engineer, Platform Infrastructure") push
 * every other column off the screen on a sheet that is mostly being scanned
 * for companies and dates. The full text stays in the cell's tooltip and in the
 * input the moment the cell is opened, so nothing is lost.
 */
const TITLE_LIMIT = 20;

function shorten(value: string): string {
  const trimmed = value.trim();
  if (trimmed.length <= TITLE_LIMIT) return trimmed;

  // Cut at the last word that fits, so "ML Infrastructure Engineer" ends at
  // "ML Infrastructure…" rather than "ML Infrastructure En…". A single very
  // long word has no boundary to find, so it is cut where it falls.
  const clipped = trimmed.slice(0, TITLE_LIMIT);
  const lastSpace = clipped.lastIndexOf(" ");
  const cut = lastSpace >= TITLE_LIMIT * 0.6 ? clipped.slice(0, lastSpace) : clipped;
  return `${cut.trimEnd()}…`;
}

/** Whether this row has a position someone actually gave it. */
function hasTitle(row: SheetRow): boolean {
  return Boolean(row.job_title) && row.job_title !== UNTITLED;
}

type Cell = { rowId: string; field: Field };

const sameCell = (a: Cell | null, b: Cell | null) =>
  a?.rowId === b?.rowId && a?.field === b?.field;

/** `https://boards.greenhouse.io/acme/jobs/1` → `boards.greenhouse.io` */
function linkLabel(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function withProtocol(url: string): string {
  const trimmed = url.trim();
  if (!trimmed) return "";
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}

export function SheetView({
  sheet,
  loading,
  personId,
  search,
  onSearchChange,
  includeArchived,
  onIncludeArchivedChange,
  day,
  onDayChange,
  today,
}: {
  sheet: ApplicationSheet | undefined;
  loading?: boolean;
  personId: string | null;
  search: string;
  onSearchChange: (value: string) => void;
  includeArchived: boolean;
  onIncludeArchivedChange: (value: boolean) => void;
  /** The day being shown, or `null` for every day. */
  day: string | null;
  onDayChange: (day: string | null) => void;
  /** Today in this person's timezone, not the viewer's. */
  today: string;
}) {
  const createApplication = useCreateApplication();
  const updateApplication = useUpdateApplication();
  const archiveApplication = useArchiveApplication();
  const bulkDelete = useBulkDeleteApplications();
  const { push: pushUndo, undoLast, canUndo, lastLabel, isUndoing } = useUndo();

  const runUndo = React.useCallback(async () => {
    try {
      const entry = await undoLast();
      if (entry) toast.success(`Undone — ${entry.label}`);
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Could not undo that.",
      );
    }
  }, [undoLast]);

  // Ctrl+Z, but never while a cell is being typed into — that field has its
  // own undo and stealing it would be worse than not offering the shortcut.
  useUndoShortcut(runUndo, canUndo);


  const [editing, setEditing] = React.useState<Cell | null>(null);
  const [draft, setDraft] = React.useState("");
  const [newRow, setNewRow] = React.useState<Record<Field, string>>({
    applied_date: "",
    company_name: "",
    job_title: "",
    job_url: "",
  });
  const inputRef = React.useRef<HTMLInputElement | null>(null);
  const saving =
    createApplication.isPending ||
    updateApplication.isPending ||
    archiveApplication.isPending;

  const canEdit = sheet?.can_edit ?? false;

  // Row order as displayed, so Enter can move down across day boundaries.
  const flatRows = React.useMemo(
    () => (sheet?.days ?? []).flatMap((day) => day.rows),
    [sheet],
  );

  // Numbering restarts at 1 under each day band, so it reads as "the 3rd
  // application that day" and lines up with the count on the band itself.

  // Focusing is imperative DOM work, not derived state — an effect is right.
  React.useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  /**
   * What the blank row currently holds. The cell being typed into lives in
   * `draft` rather than `newRow`, so both have to be merged to know whether
   * the row is complete.
   */
  const pendingNew = React.useMemo<Record<Field, string>>(
    () =>
      editing?.rowId === NEW_ROW
        ? { ...newRow, [editing.field]: draft }
        : newRow,
    [newRow, editing, draft],
  );

  // Blur handlers fire before their own `setNewRow` has flushed, so they read
  // the row from here rather than from state.
  const pendingRef = React.useRef(pendingNew);
  React.useEffect(() => {
    pendingRef.current = pendingNew;
  }, [pendingNew]);

  // One create at a time: the auto-add timer, Enter and blur can otherwise
  // race and post the same row twice.
  const creatingRef = React.useRef(false);

  // A pasted block waits here until the user confirms it.
  const [pasted, setPasted] = React.useState<ParsedPaste | null>(null);

  /**
   * Intercept a paste that carries more than one cell.
   *
   * A plain single-value paste is left to the browser — it should behave like
   * typing. Anything with a tab or a newline came from a spreadsheet and is
   * offered as a block instead.
   */
  function handlePaste(event: React.ClipboardEvent, field: Field) {
    const text = event.clipboardData.getData("text/plain");
    if (!text || !/[\t\n]/.test(text)) return;

    event.preventDefault();
    const parsed = parsePaste(text, field);
    if (parsed.rows.length === 0) {
      toast.error(
        parsed.skipped > 0
          ? "Those rows have no company name, so there is nothing to add."
          : "Nothing recognisable to paste.",
      );
      return;
    }
    setPasted(parsed);
  }

  function beginEdit(row: SheetRow, field: Field) {
    if (!canEdit) return;
    setEditing({ rowId: row.id, field });
    setDraft(currentValue(row, field));
  }

  function currentValue(row: SheetRow, field: Field): string {
    if (field === "applied_date") return row.applied_date ?? "";
    if (field === "company_name") return row.company_name;
    // Opening a cell that is only holding the placeholder gives an empty box.
    // Nobody typed "Untitled role", so nobody should have to delete it.
    if (field === "job_title") return hasTitle(row) ? row.job_title : "";
    return row.job_url ?? "";
  }

  async function commit(row: SheetRow, field: Field, value: string) {
    const before = currentValue(row, field);
    const next = field === "job_url" ? withProtocol(value) : value.trim();
    if (next === before) return true;

    if (field === "company_name" && !next) {
      toast.error("A row needs a company name.");
      return false;
    }
    // The API requires a title. Clearing the cell is allowed — it falls back to
    // the placeholder rather than refusing the edit.
    const stored = field === "job_title" && !next ? UNTITLED : next;

    try {
      await updateApplication.mutateAsync({
        id: row.id,
        body: {
          [field]:
            field === "job_url" || field === "applied_date"
              ? stored || null
              : stored,
        },
      });
      pushUndo({
        label: `${COLUMN_LABELS[field]} on ${row.company_name}`,
        undo: async () => {
          await updateApplication.mutateAsync({
            id: row.id,
            body: { [field]: before || null },
          });
        },
      });
      return true;
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Could not save that cell.",
      );
      return false;
    }
  }

  async function commitNewRow(
    values: Record<Field, string>,
    options: { focusAfter?: Field | null } = {},
  ) {
    const company = values.company_name.trim();
    // A date or a link alone is not an application; wait for a company.
    if (!company) return false;
    if (creatingRef.current) return false;

    creatingRef.current = true;
    try {
      const created = await createApplication.mutateAsync({
        person_id: personId,
        company_name: company,
        job_title: values.job_title.trim() || UNTITLED,
        applied_date: values.applied_date || undefined,
        job_url: withProtocol(values.job_url) || undefined,
      });
      pushUndo({
        label: `added ${company}`,
        undo: async () => {
          await bulkDelete.mutateAsync([(created as { id: string }).id]);
        },
      });
      const empty = {
        applied_date: "",
        company_name: "",
        job_title: "",
        job_url: "",
      };
      setNewRow(empty);
      pendingRef.current = empty;
      setDraft("");
      // A fresh blank row is now waiting; put the cursor where the next entry
      // starts, or nowhere if the user has already moved on.
      setEditing(
        options.focusAfter ? { rowId: NEW_ROW, field: options.focusAfter } : null,
      );
      toast.success(`${company} added`);
      return true;
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : "Could not add that application.",
      );
      return false;
    } finally {
      creatingRef.current = false;
    }
  }

  // `commitNewRow` is rebuilt every render, so the auto-add timer reaches it
  // through a ref — otherwise the effect below would re-arm continuously.
  const commitRef = React.useRef(commitNewRow);
  React.useEffect(() => {
    commitRef.current = commitNewRow;
  });

  /** Both the fields the user types are filled, so the row can save itself. */
  const autoAddArmed =
    canEdit &&
    pendingNew.company_name.trim().length > 0 &&
    pendingNew.job_url.trim().length > 0;

  // Fill in company and link and the row commits on its own — no Enter. Enter
  // still works and is immediate; this is for the common case of typing across
  // the row and moving on.
  React.useEffect(() => {
    if (!autoAddArmed) return;
    const timer = window.setTimeout(() => {
      void commitRef.current(pendingRef.current, { focusAfter: "company_name" });
    }, AUTO_ADD_DELAY_MS);
    return () => window.clearTimeout(timer);
    // Every keystroke restarts the wait, so a pause is what triggers it.
  }, [
    autoAddArmed,
    pendingNew.applied_date,
    pendingNew.company_name,
    pendingNew.job_url,
  ]);

  /** Focus left the blank row entirely — save what was typed rather than lose it. */
  async function commitOnLeave() {
    if (creatingRef.current) return;
    if (!pendingRef.current.company_name.trim()) return;
    await commitRef.current(pendingRef.current, { focusAfter: null });
  }

  /** Enter → same column, next row. Tab → next column, wrapping to the row below. */
  function move(rowId: string, field: Field, direction: "down" | "next") {
    const index = flatRows.findIndex((r) => r.id === rowId);
    const fieldIndex = FIELDS.indexOf(field);

    if (direction === "next" && fieldIndex < FIELDS.length - 1) {
      const nextField = FIELDS[fieldIndex + 1];
      if (rowId === NEW_ROW) {
        setEditing({ rowId: NEW_ROW, field: nextField });
        setDraft(newRow[nextField]);
      } else {
        beginEdit(flatRows[index], nextField);
      }
      return;
    }

    const target = FIELDS[direction === "next" ? 0 : fieldIndex];
    const nextRow = index >= 0 ? flatRows[index + 1] : undefined;
    if (nextRow) {
      beginEdit(nextRow, target);
    } else {
      // Past the last row is the blank one — the natural place to keep typing.
      setEditing({ rowId: NEW_ROW, field: target });
      setDraft(newRow[target]);
    }
  }

  function cancel() {
    setEditing(null);
    setDraft("");
  }

  async function toggleArchive(row: SheetRow) {
    try {
      await archiveApplication.mutateAsync({
        id: row.id,
        restore: row.is_archived,
      });
      pushUndo({
        label: row.is_archived
          ? `restored ${row.company_name}`
          : `archived ${row.company_name}`,
        undo: async () => {
          await archiveApplication.mutateAsync({
            id: row.id,
            restore: !row.is_archived,
          });
        },
      });
      toast.success(
        row.is_archived
          ? `${row.company_name} restored`
          : `${row.company_name} archived`,
      );
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : "Could not archive that application.",
      );
    }
  }

  async function handleKeyDown(
    event: React.KeyboardEvent<HTMLInputElement>,
    row: SheetRow | null,
    field: Field,
  ) {
    if (event.key === "Escape") {
      event.preventDefault();
      cancel();
      return;
    }
    if (event.key !== "Enter" && event.key !== "Tab") return;

    event.preventDefault();
    const direction = event.key === "Enter" ? "down" : "next";

    if (row) {
      const saved = await commit(row, field, draft);
      if (!saved) return;
      move(row.id, field, direction);
      return;
    }

    const values = { ...newRow, [field]: draft };
    setNewRow(values);
    // Tabbing between the blank row's own cells should not create anything
    // yet — only Enter, or leaving the last column, commits it.
    const shouldCommit =
      direction === "down" || FIELDS.indexOf(field) === FIELDS.length - 1;
    if (shouldCommit && values.company_name.trim()) {
      await commitNewRow(values, { focusAfter: FIELDS[0] });
      return;
    }
    move(NEW_ROW, field, direction);
  }

  async function handleBlur(row: SheetRow | null, field: Field) {
    if (row) {
      await commit(row, field, draft);
      cancel();
      return;
    }
    const values = { ...newRow, [field]: draft };
    setNewRow(values);
    cancel();
  }

  // ------------------------------------------------------------------ render

  if (loading && !sheet) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-10" />
        <Skeleton className="h-72" />
      </div>
    );
  }

  if (!sheet || sheet.tabs.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-surface">
        <EmptyState
          title="No people to show"
          description="Applications are grouped by person here. Add someone on the People page, or widen the person filter."
        />
      </div>
    );
  }

  return (
    // The sheet fills whatever height the page hands it, and only the grid
    // inside it scrolls. Two hundred rows in a day is an ordinary volume here,
    // and scrolling the page to reach them took the controls with it.
    <div className="flex h-full min-h-0 flex-col">
      {/* Toolbar */}
      <div className="mb-2 flex shrink-0 flex-wrap items-center gap-2">
        {/* Showing one day keeps the blank row within reach; without it a long
            sheet has to be scrolled to the bottom before anything can be
            added. */}
        <div className="flex shrink-0 items-center gap-1 rounded-md border border-border p-0.5">
          <button
            type="button"
            onClick={() => onDayChange(today)}
            aria-pressed={day === today}
            className={cn(
              "rounded px-2 py-1 text-xs font-medium transition-colors",
              day === today
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-surface-hover hover:text-foreground",
            )}
          >
            Today
          </button>
          <button
            type="button"
            onClick={() => onDayChange(null)}
            aria-pressed={day === null}
            className={cn(
              "rounded px-2 py-1 text-xs font-medium transition-colors",
              day === null
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-surface-hover hover:text-foreground",
            )}
          >
            All
          </button>
          <label className="relative inline-flex items-center">
            <span className="sr-only">Show a specific day</span>
            <CalendarDays
              className={cn(
                "pointer-events-none absolute left-1.5 size-3.5",
                day && day !== today
                  ? "text-primary-foreground"
                  : "text-muted-foreground",
              )}
            />
            <input
              type="date"
              value={day ?? ""}
              onChange={(event) => onDayChange(event.target.value || null)}
              className={cn(
                "h-[26px] w-[8.5rem] rounded bg-transparent pl-6 pr-1 text-xs focus:outline-none focus:ring-1 focus:ring-inset focus:ring-ring",
                day && day !== today
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground",
              )}
            />
          </label>
        </div>

        <div className="relative min-w-56 flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-subtle-foreground" />
          <Input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Search this sheet — company, job title, notes…"
            className="h-8 pl-8 pr-8 text-xs"
            aria-label="Search the sheet"
          />
          {search ? (
            <button
              type="button"
              onClick={() => onSearchChange("")}
              aria-label="Clear the search"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-subtle-foreground hover:text-foreground"
            >
              <X className="size-3.5" />
            </button>
          ) : null}
        </div>

        <p className="text-xs text-muted-foreground" aria-live="polite">
          {search ? (
            <>
              <span className="font-medium text-foreground">{sheet.matched}</span>{" "}
              of {sheet.total} matching
              {/* A search deliberately ignores the day filter — you rarely
                  remember which day you filed a given company. */}
              {sheet.search_ignored_day ? " across all days" : null}
            </>
          ) : sheet.day ? (
            <>
              <span className="font-medium text-foreground">{sheet.matched}</span>{" "}
              on this day · {sheet.total} in total
            </>
          ) : (
            <>
              <span className="font-medium text-foreground">{sheet.total}</span>{" "}
              application{sheet.total === 1 ? "" : "s"}
              {sheet.busiest_day_count > 1 ? (
                <> · busiest day {sheet.busiest_day_count}</>
              ) : null}
            </>
          )}
        </p>

        <label className="inline-flex shrink-0 cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(event) => onIncludeArchivedChange(event.target.checked)}
            className="size-3.5 accent-[var(--primary)]"
          />
          Show archived
        </label>

        {canUndo || isUndoing ? (
          <Button
            size="xs"
            variant="secondary"
            onClick={() => void runUndo()}
            loading={isUndoing}
            title={lastLabel ? `Undo — ${lastLabel}` : "Undo"}
          >
            <Undo2 />
            Undo
          </Button>
        ) : null}

        {saving ? (
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            Saving
          </span>
        ) : null}
        {!canEdit ? <ReadOnlyNote /> : null}
      </div>

      {/* Grid */}
      <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border bg-surface">
        <table className="w-full border-collapse text-sm">
          {/* Sticky on the cells rather than the row: `position: sticky` on a
              `thead` is not honoured everywhere, and the background has to be
              opaque or the rows show through as they pass under it. */}
          <thead>
            <tr>
              <th
                scope="col"
                className="sticky top-0 z-10 w-10 border-b border-r border-border bg-surface-muted px-1 py-1.5 text-[11px] font-medium text-subtle-foreground"
              >
                #
              </th>
              {COLUMNS.map((column) => (
                <th
                  key={column.field}
                  scope="col"
                  className={cn(
                    "sticky top-0 z-10 border-b border-r border-border bg-surface-muted px-2 py-1.5 text-left text-xs font-semibold text-muted-foreground",
                    column.width,
                  )}
                >
                  {column.label}
                </th>
              ))}
              <th
                scope="col"
                className="sticky top-0 z-10 w-20 border-b border-border bg-surface-muted px-1 py-1.5 text-[11px] font-medium text-subtle-foreground"
              >
                <span className="sr-only">Row actions</span>
              </th>
            </tr>
          </thead>

          <tbody>
            {sheet.days.length === 0 && !canEdit ? (
              <tr>
                <td colSpan={COLUMNS.length + 2} className="p-0">
                  <EmptyState
                    title={search ? "Nothing matches that" : "No applications yet"}
                    description={
                      search
                        ? "Try fewer letters, or clear the search."
                        : "This sheet is empty."
                    }
                  />
                </td>
              </tr>
            ) : null}

            {sheet.days.map((day) => (
              <React.Fragment key={day.date ?? "undated"}>
                {/* Day band — the per-day count the user asked for */}
                <tr>
                  <th
                    scope="colgroup"
                    colSpan={COLUMNS.length + 2}
                    className="border-b border-border bg-surface-muted/80 px-2 py-1 text-left"
                  >
                    <span className="text-xs font-semibold text-foreground">
                      {day.label}
                    </span>
                    {/* Spaces around the separator are real text, not just a
                        margin: adjacent inline spans concatenate for screen
                        readers and copied text, which would otherwise turn
                        "2026" + "1 application" into "20261". */}
                    <span className="text-xs text-subtle-foreground">
                      {" · "}
                    </span>
                    <span className="text-xs font-normal text-muted-foreground">
                      {day.count} application{day.count === 1 ? "" : "s"}
                    </span>
                  </th>
                </tr>

                {day.rows.map((row, index) => (
                    <tr
                      key={row.id}
                      className={cn(
                        "group hover:bg-surface-hover",
                        row.is_archived && "opacity-55",
                        // Applying twice to the same posting is easy when rows
                        // arrive by paste; the row says so rather than leaving
                        // it to be noticed.
                        isDuplicate(row) &&
                          "bg-status-danger-bg/40 hover:bg-status-danger-bg/60",
                      )}
                    >
                      <td className="border-b border-r border-border px-1 text-center align-middle text-[11px] tabular-nums text-subtle-foreground">
                        {isDuplicate(row) ? (
                          <Tooltip
                            content={
                              row.duplicate_note ??
                              "Another row points at this same job posting."
                            }
                          >
                            <span
                              className="inline-flex text-status-danger"
                              aria-label={`Duplicate job link — ${
                                row.duplicate_note ?? "same posting as another row"
                              }`}
                            >
                              <TriangleAlert className="size-3.5" />
                            </span>
                          </Tooltip>
                        ) : (
                          index + 1
                        )}
                      </td>

                      {COLUMNS.map((column) => (
                        <td
                          key={column.field}
                          className="border-b border-r border-border p-0 align-middle"
                        >
                          <SheetCell
                            row={row}
                            field={column.field}
                            editing={sameCell(editing, {
                              rowId: row.id,
                              field: column.field,
                            })}
                            canEdit={canEdit}
                            draft={draft}
                            inputRef={inputRef}
                            onDraftChange={setDraft}
                            onBeginEdit={() => beginEdit(row, column.field)}
                            onKeyDown={(event) =>
                              handleKeyDown(event, row, column.field)
                            }
                            onPaste={(event) => handlePaste(event, column.field)}
                            onBlur={() => handleBlur(row, column.field)}
                          />
                        </td>
                      ))}

                      <td className="border-b border-border px-1 align-middle">
                        <div className="flex items-center justify-center gap-0.5">
                          <Tooltip content="Open the full application">
                            <Link
                              href={`/applications/${row.id}`}
                              className="inline-flex rounded p-1 text-subtle-foreground opacity-0 transition-opacity hover:bg-surface-hover hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
                              aria-label={`Open ${row.company_name}`}
                            >
                              <SquareArrowOutUpRight className="size-3.5" />
                            </Link>
                          </Tooltip>
                          {canEdit ? (
                            <Tooltip
                              content={
                                row.is_archived
                                  ? "Restore this application"
                                  : "Archive this application"
                              }
                            >
                              <button
                                type="button"
                                onClick={() => void toggleArchive(row)}
                                aria-label={`${row.is_archived ? "Restore" : "Archive"} ${row.company_name}`}
                                className="inline-flex rounded p-1 text-subtle-foreground opacity-0 transition-opacity hover:bg-surface-hover hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
                              >
                                {row.is_archived ? (
                                  <ArchiveRestore className="size-3.5" />
                                ) : (
                                  <Archive className="size-3.5" />
                                )}
                              </button>
                            </Tooltip>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                ))}
              </React.Fragment>
            ))}

            {/* The blank row: type across it to add an application. It saves
                itself once company and link are filled, and also when focus
                leaves the row, so typed text is never silently dropped. */}
            {canEdit ? (
              <tr
                className="bg-surface"
                onBlur={(event) => {
                  // Moving between this row's own cells is not leaving it.
                  if (event.currentTarget.contains(event.relatedTarget as Node | null)) {
                    return;
                  }
                  void commitOnLeave();
                }}
              >
                <td className="border-b border-r border-border px-1 text-center align-middle text-subtle-foreground">
                  <Plus className="mx-auto size-3" />
                </td>
                {COLUMNS.map((column) => (
                  <td
                    key={column.field}
                    className="border-b border-r border-border p-0 align-middle"
                  >
                    <input
                      value={
                        sameCell(editing, { rowId: NEW_ROW, field: column.field })
                          ? draft
                          : newRow[column.field]
                      }
                      type={column.field === "applied_date" ? "date" : "text"}
                      placeholder={NEW_ROW_PLACEHOLDERS[column.field]}
                      ref={
                        sameCell(editing, { rowId: NEW_ROW, field: column.field })
                          ? inputRef
                          : undefined
                      }
                      onFocus={() => {
                        setEditing({ rowId: NEW_ROW, field: column.field });
                        setDraft(newRow[column.field]);
                      }}
                      onChange={(event) => setDraft(event.target.value)}
                      onKeyDown={(event) => handleKeyDown(event, null, column.field)}
                      onPaste={(event) => handlePaste(event, column.field)}
                      onBlur={() => handleBlur(null, column.field)}
                      className="h-8 w-full bg-transparent px-2 text-sm text-foreground placeholder:text-subtle-foreground focus:bg-primary/5 focus:outline-none focus:ring-1 focus:ring-inset focus:ring-primary"
                      aria-label={`New application — ${column.label}`}
                    />
                  </td>
                ))}
                <td className="border-b border-border px-1 align-middle">
                  {autoAddArmed ? (
                    <span className="flex items-center justify-center gap-1 text-[11px] text-muted-foreground">
                      <span className="size-1.5 animate-pulse rounded-full bg-primary" />
                      Adding
                    </span>
                  ) : null}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <PasteDialog
        parsed={pasted}
        personId={personId}
        personName={
          sheet.tabs.find((tab) => tab.person_id === (personId ?? sheet.person_id))
            ?.name ?? "this person"
        }
        onClose={() => setPasted(null)}
      />

    </div>
  );
}

// --------------------------------------------------------------------------

function SheetCell({
  row,
  field,
  editing,
  canEdit,
  draft,
  inputRef,
  onDraftChange,
  onBeginEdit,
  onKeyDown,
  onPaste,
  onBlur,
}: {
  row: SheetRow;
  field: Field;
  editing: boolean;
  canEdit: boolean;
  draft: string;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onDraftChange: (value: string) => void;
  onBeginEdit: () => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLInputElement>) => void;
  onPaste: (event: React.ClipboardEvent<HTMLInputElement>) => void;
  onBlur: () => void;
}) {
  if (editing) {
    return (
      <input
        ref={inputRef}
        type={field === "applied_date" ? "date" : "text"}
        value={draft}
        onChange={(event) => onDraftChange(event.target.value)}
        onKeyDown={onKeyDown}
        onPaste={onPaste}
        onBlur={onBlur}
        className="h-8 w-full bg-primary/5 px-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-inset focus:ring-primary"
        aria-label={`${field.replace(/_/g, " ")} for ${row.company_name}`}
      />
    );
  }

  const content =
    field === "applied_date" ? (
      <span className="tabular-nums">{row.applied_date ?? "—"}</span>
    ) : field === "company_name" ? (
      // The company cell shows the company. The position has its own column,
      // and repeating it here in small type only made both harder to scan.
      <span className="flex items-center gap-1.5">
        <span className="truncate">{row.company_name}</span>
        {row.is_archived ? (
          <span className="shrink-0 rounded bg-surface-muted px-1 text-[10px] text-muted-foreground">
            archived
          </span>
        ) : null}
      </span>
    ) : field === "job_title" ? (
      hasTitle(row) ? (
        <span className="truncate">{shorten(row.job_title)}</span>
      ) : (
        // The placeholder is what the row was stored with, not something
        // anyone typed, so it reads as an empty cell waiting to be filled.
        <span className="text-subtle-foreground">{UNTITLED}</span>
      )
    ) : row.job_url ? (
      <a
        href={row.job_url}
        target="_blank"
        rel="noreferrer"
        onClick={(event) => event.stopPropagation()}
        className="inline-flex max-w-full items-center gap-1 truncate text-primary hover:underline"
      >
        <span className="truncate">{linkLabel(row.job_url)}</span>
        <ArrowUpRight className="size-3 shrink-0" />
      </a>
    ) : (
      <span className="text-subtle-foreground">—</span>
    );

  const title =
    field === "company_name"
      ? APPLICATION_STATUS_LABELS[row.status]
      : field === "job_title" && hasTitle(row)
        ? row.job_title
        : undefined;

  if (!canEdit) {
    return (
      <div className="flex h-8 items-center px-2" title={title}>
        {content}
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={onBeginEdit}
      onFocus={onBeginEdit}
      className="flex h-8 w-full items-center px-2 text-left focus:outline-none focus:ring-1 focus:ring-inset focus:ring-primary"
      title={title}
    >
      {content}
    </button>
  );
}
