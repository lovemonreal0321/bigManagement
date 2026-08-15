"use client";

/**
 * "Created by AI" feed (the undo half of auto-create).
 *
 * Every record the model created is listed here with what it read, how sure it
 * was, and a one-click undo that removes exactly what it added. Items below the
 * confidence threshold appear as suggestions to accept instead.
 */

import {
  Check,
  ChevronDown,
  Mail,
  RotateCcw,
  Sparkles,
  Undo2,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";

import { PersonAvatar, StageBadge } from "@/components/shared/badges";
import {
  Alert,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  Skeleton,
} from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { formatCountdown, formatDate, formatTime } from "@/lib/format";
import { usePersonFilter } from "@/lib/person-filter";
import {
  useAiExtraction,
  useAiExtractions,
  useAiStatus,
  useApplyExtraction,
  useRunEnrichment,
  useUndoExtraction,
} from "@/lib/queries";
import type { AiExtraction } from "@/lib/types";
import { cn } from "@/lib/utils";

function confidenceLabel(value: number): { text: string; tone: string } {
  if (value >= 0.85) return { text: "High confidence", tone: "text-status-success" };
  if (value >= 0.6) return { text: "Fair confidence", tone: "text-status-warn" };
  return { text: "Low confidence", tone: "text-muted-foreground" };
}

function EvidencePanel({ extractionId }: { extractionId: string }) {
  const { data, isLoading } = useAiExtraction(extractionId);

  if (isLoading) return <Skeleton className="mt-2 h-20" />;
  if (!data) return null;

  return (
    <div className="mt-2 space-y-2 rounded-md border border-border bg-surface-muted/40 p-2.5">
      {data.reasoning ? (
        <p className="text-[11px] leading-snug text-muted-foreground">
          <span className="font-medium text-foreground">Why: </span>
          {data.reasoning}
        </p>
      ) : null}

      {data.messages.length === 0 ? (
        <p className="text-[11px] text-subtle-foreground">
          No matching emails — this came from the calendar event alone.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {data.messages.map((message) => (
            <li key={message.id} className="text-[11px]">
              <div className="flex items-center gap-1.5">
                <Mail className="size-3 shrink-0 text-subtle-foreground" />
                <span className="truncate font-medium text-foreground">
                  {message.subject || "(no subject)"}
                </span>
              </div>
              <p className="pl-4.5 text-subtle-foreground">
                {message.from_name || message.from_address}
                {message.sent_at ? ` · ${formatDate(message.sent_at)}` : ""}
                {message.match_reasons?.length
                  ? ` · ${message.match_reasons[0]}`
                  : ""}
              </p>
            </li>
          ))}
        </ul>
      )}

      <p className="text-[10px] text-subtle-foreground">
        {data.model ? `${data.model} · ` : ""}
        {data.tokens_used} tokens
      </p>
    </div>
  );
}

function ExtractionRow({ extraction }: { extraction: AiExtraction }) {
  const [expanded, setExpanded] = React.useState(false);
  const undo = useUndoExtraction();
  const apply = useApplyExtraction();
  const confidence = confidenceLabel(extraction.confidence);
  const isSuggestion = extraction.status === "suggested";
  const isUndone = extraction.status === "undone";

  async function run(action: "undo" | "apply") {
    try {
      if (action === "undo") {
        await undo.mutateAsync(extraction.id);
        toast.success("Undone — the records it created were removed");
      } else {
        await apply.mutateAsync(extraction.id);
        toast.success("Applied");
      }
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Could not update that.",
      );
    }
  }

  return (
    <li className={cn("px-4 py-3", isUndone && "opacity-60")}>
      <div className="flex flex-wrap items-start gap-2">
        <PersonAvatar
          color={extraction.person_color || "#64748b"}
          initials={extraction.person_initials || "?"}
          title={extraction.person_name}
          size="lg"
        />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="truncate text-sm font-medium text-foreground">
              {extraction.company_name ?? extraction.event_title ?? "Interview"}
            </span>
            {extraction.stage_badge ? (
              <StageBadge badge={extraction.stage_badge} />
            ) : null}
            {isSuggestion ? (
              <span className="rounded bg-status-warn-bg px-1.5 py-0.5 text-[11px] font-medium text-status-warn">
                Needs review
              </span>
            ) : isUndone ? (
              <span className="rounded bg-surface-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
                Undone
              </span>
            ) : (
              <span className="flex items-center gap-1 rounded bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">
                <Sparkles className="size-3" />
                {extraction.linked_existing_application
                  ? "Round added"
                  : "Created"}
              </span>
            )}
          </div>

          <p className="truncate text-xs text-muted-foreground">
            {extraction.job_title ?? "Role not specified"}
            {extraction.event_starts_at
              ? ` · ${formatDate(extraction.event_starts_at)} ${formatTime(
                  extraction.event_starts_at,
                )}`
              : ""}
          </p>

          <p className="mt-0.5 text-[11px] text-subtle-foreground">
            <span className={confidence.tone}>{confidence.text}</span>
            {" · "}
            {extraction.message_count === 0
              ? "calendar only"
              : `${extraction.message_count} email${
                  extraction.message_count === 1 ? "" : "s"
                } read`}
            {" · "}
            {formatCountdown(extraction.created_at)}
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-1">
          {extraction.created_application_id || extraction.created_stage_id ? (
            <Button asChild size="xs" variant="ghost">
              <Link
                href={`/applications/${extraction.created_application_id ?? ""}`}
              >
                Open
              </Link>
            </Button>
          ) : null}

          {isSuggestion ? (
            <Button
              size="xs"
              variant="primary"
              loading={apply.isPending}
              onClick={() => run("apply")}
            >
              <Check />
              Accept
            </Button>
          ) : null}

          {extraction.is_undoable ? (
            <Button
              size="xs"
              variant="secondary"
              loading={undo.isPending}
              onClick={() => run("undo")}
            >
              <Undo2 />
              Undo
            </Button>
          ) : null}

          <Button
            size="icon-sm"
            variant="ghost"
            aria-label="Show what the AI read"
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            <ChevronDown
              className={cn("transition-transform", expanded && "rotate-180")}
            />
          </Button>
        </div>
      </div>

      {expanded ? <EvidencePanel extractionId={extraction.id} /> : null}
    </li>
  );
}

export function AiReviewFeed({ limit = 15 }: { limit?: number }) {
  const { queryIds } = usePersonFilter();
  const { data: status } = useAiStatus();
  const { data: extractions, isLoading } = useAiExtractions(queryIds, limit);
  const enrich = useRunEnrichment(queryIds);

  async function runNow() {
    try {
      const summary = await enrich.mutateAsync({});
      if (summary.errors.length > 0) {
        toast.error(summary.errors[0]);
      } else if (summary.processed === 0) {
        toast.info("No new interview-shaped events to look at.");
      } else {
        toast.success(
          `Read ${summary.processed} event${summary.processed === 1 ? "" : "s"} — ` +
            `${summary.applied} filled in, ${summary.suggested} to review`,
        );
      }
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Could not run enrichment.",
      );
    }
  }

  const rows = extractions ?? [];
  const notReady = status && !status.configured;

  return (
    <Card>
      <CardHeader
        title="Created by AI"
        description="Interviews filled in from your calendar and the emails about them."
        action={
          <Button
            size="xs"
            variant="secondary"
            loading={enrich.isPending}
            disabled={Boolean(notReady)}
            onClick={runNow}
            title={notReady ? status?.setup_hint ?? undefined : undefined}
          >
            <RotateCcw />
            Check now
          </Button>
        }
      />

      {notReady ? (
        <CardBody>
          <Alert tone="info" title="AI enrichment is not set up yet">
            {status?.setup_hint}
            <div className="mt-2">
              <Button asChild size="xs" variant="secondary">
                <Link href="/settings">Open settings</Link>
              </Button>
            </div>
          </Alert>
        </CardBody>
      ) : isLoading ? (
        <CardBody className="space-y-2">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-16" />
          ))}
        </CardBody>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Sparkles}
          title="Nothing filled in yet"
          description="When an interview lands on a connected calendar, the emails about it are read and the application is filled in here."
          action={
            <Button size="sm" variant="secondary" onClick={runNow} loading={enrich.isPending}>
              Check now
            </Button>
          }
        />
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((extraction) => (
            <ExtractionRow key={extraction.id} extraction={extraction} />
          ))}
        </ul>
      )}
    </Card>
  );
}
