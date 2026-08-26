"use client";

/**
 * Choosing what a calendar event belongs to.
 *
 * One search box over two things at once: applications, and the interviews
 * already recorded against them. Searching interviews matters for a later
 * round — "the Anthropic recruiter screen" is how people refer to where they
 * are in a process, not by the application row behind it. Picking either
 * resolves to the same application; picking an interview additionally offers
 * to attach the event to that exact round.
 */

import { Briefcase, CalendarClock, Check, Search, X } from "lucide-react";
import * as React from "react";

import { StatusBadge } from "@/components/shared/badges";
import { Input, Skeleton } from "@/components/ui/primitives";
import { formatDate, formatDateOnly } from "@/lib/format";
import { useApplications, useInterviewSearch } from "@/lib/queries";
import type { Application, InterviewSearchResult } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface LinkTarget {
  applicationId: string;
  companyName: string;
  jobTitle: string;
  /** Set when an interview was picked rather than an application. */
  stage?: InterviewSearchResult;
  /** The round a following interview would take. */
  nextRoundNumber: number;
}

function Highlight({ text, query }: { text: string; query: string }) {
  const needle = query.trim();
  if (!needle) return <>{text}</>;
  const at = text.toLowerCase().indexOf(needle.toLowerCase());
  if (at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <mark className="bg-primary/20 text-foreground">
        {text.slice(at, at + needle.length)}
      </mark>
      {text.slice(at + needle.length)}
    </>
  );
}

export function LinkTargetPicker({
  personId,
  personName,
  value,
  onChange,
  autoFocus,
}: {
  personId: string;
  personName?: string;
  value: LinkTarget | null;
  onChange: (target: LinkTarget | null) => void;
  autoFocus?: boolean;
}) {
  const [query, setQuery] = React.useState("");
  const [debounced, setDebounced] = React.useState("");

  React.useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query.trim()), 200);
    return () => window.clearTimeout(timer);
  }, [query]);

  const applications = useApplications([personId], {
    q: debounced || undefined,
    limit: 15,
    sort: "last_activity",
  });
  const interviews = useInterviewSearch([personId], debounced);

  // Interviews first: if one matches, it is almost always the more specific
  // answer, and it carries the round number the next stage should take.
  const interviewResults = (interviews.data ?? []).slice(0, 8);
  const applicationResults = (applications.data?.items ?? []).slice(0, 10);
  const loading = applications.isLoading || interviews.isLoading;
  const empty =
    !loading && interviewResults.length === 0 && applicationResults.length === 0;

  function pickApplication(application: Application) {
    // Without an interview picked we do not know the round; the form asks the
    // server-derived number only when an interview is chosen, so start at 1.
    const match = (interviews.data ?? []).find(
      (row) => row.application_id === application.id,
    );
    onChange({
      applicationId: application.id,
      companyName: application.company_name,
      jobTitle: application.job_title,
      nextRoundNumber: match?.next_round_number ?? 1,
    });
  }

  function pickInterview(stage: InterviewSearchResult) {
    onChange({
      applicationId: stage.application_id,
      companyName: stage.company_name,
      jobTitle: stage.job_title,
      stage,
      nextRoundNumber: stage.next_round_number,
    });
  }

  if (value) {
    return (
      <div className="flex items-start gap-2 rounded-md border border-primary bg-primary/5 p-2.5">
        <Check className="mt-0.5 size-4 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground">
            {value.companyName}
          </p>
          <p className="truncate text-xs text-muted-foreground">
            {value.jobTitle}
            {value.stage ? ` · via ${value.stage.stage_badge}` : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={() => onChange(null)}
          className="rounded p-1 text-subtle-foreground hover:bg-surface-hover hover:text-foreground"
          aria-label="Choose something else"
        >
          <X className="size-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-subtle-foreground" />
        <Input
          value={query}
          autoFocus={autoFocus}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={
            personName
              ? `Search ${personName}'s applications and interviews…`
              : "Search applications and interviews…"
          }
          className="h-9 pl-8 text-sm"
          aria-label="Search applications and interviews"
        />
      </div>

      <div className="mt-1.5 max-h-64 overflow-y-auto rounded-md border border-border">
        {loading ? (
          <div className="space-y-1 p-2">
            <Skeleton className="h-9" />
            <Skeleton className="h-9" />
          </div>
        ) : empty ? (
          <p className="px-3 py-6 text-center text-xs text-muted-foreground">
            {debounced
              ? `Nothing matches “${debounced}”.`
              : "Nothing recorded for this person yet."}
          </p>
        ) : (
          <>
            {interviewResults.length > 0 ? (
              <Section label="Interviews already recorded">
                {interviewResults.map((stage) => (
                  <button
                    key={stage.stage_id}
                    type="button"
                    onClick={() => pickInterview(stage)}
                    className="flex w-full items-center gap-2 border-b border-border px-2.5 py-1.5 text-left last:border-b-0 hover:bg-surface-hover"
                  >
                    <CalendarClock className="size-3.5 shrink-0 text-subtle-foreground" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm text-foreground">
                        <Highlight text={stage.company_name} query={debounced} />
                        <span className="ml-1.5 rounded bg-surface-muted px-1 text-[11px] text-muted-foreground">
                          {stage.stage_badge}
                        </span>
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        <Highlight text={stage.stage_name} query={debounced} />
                        {stage.scheduled_start
                          ? ` · ${formatDate(stage.scheduled_start)}`
                          : ""}
                        {stage.outcome !== "pending" ? ` · ${stage.outcome}` : ""}
                      </p>
                    </div>
                  </button>
                ))}
              </Section>
            ) : null}

            {applicationResults.length > 0 ? (
              <Section label="Applications">
                {applicationResults.map((application) => (
                  <button
                    key={application.id}
                    type="button"
                    onClick={() => pickApplication(application)}
                    className="flex w-full items-center gap-2 border-b border-border px-2.5 py-1.5 text-left last:border-b-0 hover:bg-surface-hover"
                  >
                    <Briefcase className="size-3.5 shrink-0 text-subtle-foreground" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm text-foreground">
                        <Highlight
                          text={application.company_name}
                          query={debounced}
                        />
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        <Highlight text={application.job_title} query={debounced} />
                        {application.applied_date
                          ? ` · ${formatDateOnly(application.applied_date)}`
                          : ""}
                      </p>
                    </div>
                    <StatusBadge status={application.status} />
                  </button>
                ))}
              </Section>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("border-b border-border last:border-b-0")}>
      <p className="bg-surface-muted/60 px-2.5 py-1 text-[11px] font-medium uppercase tracking-wide text-subtle-foreground">
        {label}
      </p>
      {children}
    </div>
  );
}
