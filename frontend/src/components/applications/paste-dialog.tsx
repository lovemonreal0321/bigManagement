"use client";

/**
 * Confirming a block of rows pasted out of a spreadsheet.
 *
 * Pasting fifty rows straight into the database would be quick and very hard to
 * undo, so the paste is shown first: which column went where, what will be
 * created, and what was skipped. Cancel costs nothing.
 */

import { ClipboardPaste, TriangleAlert } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { Dialog, DialogContent, DialogFooter } from "@/components/ui/overlays";
import { Alert, Button } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { useBulkCreateApplications } from "@/lib/queries";
import type { ParsedPaste } from "@/lib/paste-grid";

const PREVIEW_ROWS = 8;

export function PasteDialog({
  parsed,
  personId,
  personName,
  onClose,
}: {
  parsed: ParsedPaste | null;
  personId: string | null;
  personName: string;
  onClose: () => void;
}) {
  return (
    <Dialog open={Boolean(parsed)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        title={`Paste ${parsed?.rows.length ?? 0} application${
          parsed?.rows.length === 1 ? "" : "s"
        }`}
        size="lg"
      >
        {parsed ? (
          <PasteForm
            parsed={parsed}
            personId={personId}
            personName={personName}
            onClose={onClose}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function PasteForm({
  parsed,
  personId,
  personName,
  onClose,
}: {
  parsed: ParsedPaste;
  personId: string | null;
  personName: string;
  onClose: () => void;
}) {
  const bulkCreate = useBulkCreateApplications();
  const [error, setError] = React.useState<string | null>(null);

  const shown = parsed.rows.slice(0, PREVIEW_ROWS);
  const hidden = parsed.rows.length - shown.length;
  const undated = parsed.rows.filter((row) => !row.applied_date).length;

  async function submit() {
    if (!personId) return;
    setError(null);
    try {
      const result = await bulkCreate.mutateAsync({
        person_id: personId,
        rows: parsed.rows,
      });
      toast.success(
        `${result.created} application${result.created === 1 ? "" : "s"} added`,
      );
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not add those rows.",
      );
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        These will be added to <strong className="text-foreground">{personName}</strong>.{" "}
        {parsed.usedHeader
          ? "The first row was read as column headings."
          : "Columns were matched left to right from the cell you pasted into."}
      </p>

      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-surface-muted/60">
              <th className="w-10 border-b border-border px-2 py-1.5 text-[11px] font-medium text-subtle-foreground">
                #
              </th>
              <th className="border-b border-border px-2 py-1.5 text-left text-xs font-semibold text-muted-foreground">
                Date
              </th>
              <th className="border-b border-border px-2 py-1.5 text-left text-xs font-semibold text-muted-foreground">
                Company
              </th>
              <th className="border-b border-border px-2 py-1.5 text-left text-xs font-semibold text-muted-foreground">
                Job description link
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((row, index) => (
              <tr key={index} className="border-b border-border last:border-b-0">
                <td className="px-2 py-1 text-center text-[11px] tabular-nums text-subtle-foreground">
                  {index + 1}
                </td>
                <td className="px-2 py-1 tabular-nums text-foreground">
                  {row.applied_date ?? (
                    <span className="text-subtle-foreground">today</span>
                  )}
                </td>
                <td className="max-w-[16rem] truncate px-2 py-1 text-foreground">
                  {row.company_name}
                </td>
                <td className="max-w-[18rem] truncate px-2 py-1 text-muted-foreground">
                  {row.job_url ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {hidden > 0 ? (
        <p className="text-xs text-muted-foreground">
          …and {hidden} more row{hidden === 1 ? "" : "s"}.
        </p>
      ) : null}

      {parsed.skipped > 0 ? (
        <Alert tone="warn" title="Some rows were skipped">
          {parsed.skipped} row{parsed.skipped === 1 ? " had" : "s had"} no company
          name, so {parsed.skipped === 1 ? "it" : "they"} cannot become an
          application.
        </Alert>
      ) : null}

      {undated > 0 ? (
        <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <TriangleAlert className="mt-0.5 size-3 shrink-0" />
          {undated} row{undated === 1 ? "" : "s"} had no usable date and will be
          dated today. The job title is set to &ldquo;Untitled role&rdquo; — the
          sheet has no column for it.
        </p>
      ) : null}

      {error ? (
        <Alert tone="danger" title="Could not add those rows">
          {error}
        </Alert>
      ) : null}

      <DialogFooter>
        <Button type="button" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button
          type="button"
          variant="primary"
          loading={bulkCreate.isPending}
          disabled={parsed.rows.length === 0 || !personId}
          onClick={() => void submit()}
        >
          <ClipboardPaste />
          Add {parsed.rows.length} application
          {parsed.rows.length === 1 ? "" : "s"}
        </Button>
      </DialogFooter>
    </div>
  );
}
