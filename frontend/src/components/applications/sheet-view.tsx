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
  Loader2,
  Plus,
  Search,
  SquareArrowOutUpRight,
  X,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";

import { ReadOnlyNote } from "@/components/shared/read-only";
import { Tooltip } from "@/components/ui/overlays";
import { EmptyState, Input, Skeleton } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { APPLICATION_STATUS_LABELS } from "@/lib/format";
import {
  useArchiveApplication,
  useCreateApplication,
  useUpdateApplication,
} from "@/lib/queries";
import type { ApplicationSheet, SheetRow } from "@/lib/types";

/** The three columns the sheet shows, in order. */
const FIELDS = ["applied_date", "company_name", "job_url"] as const;
type Field = (typeof FIELDS)[number];

const COLUMNS: { field: Field; label: string; width: string }[] = [
  { field: "applied_date", label: "Date", width: "w-40" },
  { field: "company_name", label: "Company", width: "w-[26rem]" },
  { field: "job_url", label: "Job description link", width: "" },
];

/** Sentinel row id for the blank "type here to add" row. */
const NEW_ROW = "__new__";

/**
 * A new row has no job title, because the sheet does not show one. Rather than
 * refuse the row, it is stored with this placeholder and can be named later on
 * the detail page.
 */
const UNTITLED = "Untitled role";

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
}: {
  sheet: ApplicationSheet | undefined;
  loading?: boolean;
  personId: string | null;
  search: string;
  onSearchChange: (value: string) => void;
  includeArchived: boolean;
  onIncludeArchivedChange: (value: boolean) => void;
}) {
  const createApplication = useCreateApplication();
  const updateApplication = useUpdateApplication();
  const archiveApplication = useArchiveApplication();

  const [editing, setEditing] = React.useState<Cell | null>(null);
  const [draft, setDraft] = React.useState("");
  const [newRow, setNewRow] = React.useState<Record<Field, string>>({
    applied_date: "",
    company_name: "",
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

  // Spreadsheet gutter numbers, counted through the day bands.
  const rowNumbers = React.useMemo(
    () => new Map(flatRows.map((row, index) => [row.id, index + 1])),
    [flatRows],
  );

  // Focusing is imperative DOM work, not derived state — an effect is right.
  React.useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  function beginEdit(row: SheetRow, field: Field) {
    if (!canEdit) return;
    setEditing({ rowId: row.id, field });
    setDraft(
      field === "applied_date"
        ? (row.applied_date ?? "")
        : field === "company_name"
          ? row.company_name
          : (row.job_url ?? ""),
    );
  }

  function currentValue(row: SheetRow, field: Field): string {
    if (field === "applied_date") return row.applied_date ?? "";
    if (field === "company_name") return row.company_name;
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

    try {
      await updateApplication.mutateAsync({
        id: row.id,
        body: {
          [field]:
            field === "job_url" ? (next || null) : field === "applied_date" ? (next || null) : next,
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

  async function commitNewRow(values: Record<Field, string>) {
    const company = values.company_name.trim();
    // A date or a link alone is not an application; wait for a company.
    if (!company) return false;

    try {
      await createApplication.mutateAsync({
        person_id: personId,
        company_name: company,
        job_title: UNTITLED,
        applied_date: values.applied_date || undefined,
        job_url: withProtocol(values.job_url) || undefined,
      });
      setNewRow({ applied_date: "", company_name: "", job_url: "" });
      toast.success(`${company} added`);
      return true;
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : "Could not add that application.",
      );
      return false;
    }
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
      const created = await commitNewRow(values);
      if (created) {
        setEditing({ rowId: NEW_ROW, field: FIELDS[0] });
        setDraft("");
        return;
      }
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
    <div className="flex flex-col">
      {/* Toolbar */}
      <div className="mb-2 flex flex-wrap items-center gap-2">
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

        {saving ? (
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            Saving
          </span>
        ) : null}
        {!canEdit ? <ReadOnlyNote /> : null}
      </div>

      {/* Grid */}
      <div className="overflow-x-auto rounded-lg border border-border bg-surface">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-surface-muted/60">
              <th
                scope="col"
                className="w-10 border-b border-r border-border px-1 py-1.5 text-[11px] font-medium text-subtle-foreground"
              >
                #
              </th>
              {COLUMNS.map((column) => (
                <th
                  key={column.field}
                  scope="col"
                  className={cn(
                    "border-b border-r border-border px-2 py-1.5 text-left text-xs font-semibold text-muted-foreground",
                    column.width,
                  )}
                >
                  {column.label}
                </th>
              ))}
              <th
                scope="col"
                className="w-20 border-b border-border px-1 py-1.5 text-[11px] font-medium text-subtle-foreground"
              >
                <span className="sr-only">Row actions</span>
              </th>
            </tr>
          </thead>

          <tbody>
            {sheet.days.length === 0 && !canEdit ? (
              <tr>
                <td colSpan={5} className="p-0">
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
                    colSpan={5}
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

                {day.rows.map((row) => (
                    <tr
                      key={row.id}
                      className={cn(
                        "group hover:bg-surface-hover",
                        row.is_archived && "opacity-55",
                      )}
                    >
                      <td className="border-b border-r border-border px-1 text-center align-middle text-[11px] tabular-nums text-subtle-foreground">
                        {rowNumbers.get(row.id)}
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

            {/* The blank row: type across it to add an application. */}
            {canEdit ? (
              <tr className="bg-surface">
                <td className="border-b border-r border-border px-1 text-center align-middle text-subtle-foreground">
                  <Plus className="mx-auto size-3" />
                </td>
                {COLUMNS.map((column, index) => (
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
                      placeholder={
                        index === 1
                          ? "Type a company to add a row…"
                          : index === 0
                            ? "today"
                            : "https://…"
                      }
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
                      onBlur={() => handleBlur(null, column.field)}
                      className="h-8 w-full bg-transparent px-2 text-sm text-foreground placeholder:text-subtle-foreground focus:bg-primary/5 focus:outline-none focus:ring-1 focus:ring-inset focus:ring-primary"
                      aria-label={`New application — ${column.label}`}
                    />
                  </td>
                ))}
                <td className="border-b border-border" />
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

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
      <span className="flex items-center gap-1.5">
        <span className="truncate">{row.company_name}</span>
        {row.job_title && row.job_title !== UNTITLED ? (
          <span className="truncate text-xs text-subtle-foreground">
            {row.job_title}
          </span>
        ) : null}
        {row.is_archived ? (
          <span className="shrink-0 rounded bg-surface-muted px-1 text-[10px] text-muted-foreground">
            archived
          </span>
        ) : null}
      </span>
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

  if (!canEdit) {
    return (
      <div
        className="flex h-8 items-center px-2"
        title={
          field === "company_name"
            ? `${row.job_title} · ${APPLICATION_STATUS_LABELS[row.status]}`
            : undefined
        }
      >
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
      title={
        field === "company_name"
          ? `${row.job_title} · ${APPLICATION_STATUS_LABELS[row.status]}`
          : undefined
      }
    >
      {content}
    </button>
  );
}
