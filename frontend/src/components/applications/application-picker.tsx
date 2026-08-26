"use client";

/**
 * Find an application by typing, rather than scrolling a dropdown.
 *
 * The select this replaced held the first hundred applications in whatever
 * order the API returned them, which stops being usable at exactly the point a
 * job search gets interesting. Search runs on the server — the same matcher the
 * sheet uses, so it covers company, job title, notes, location and person, not
 * just a prefix of the company name.
 */

import { Check, Search, X } from "lucide-react";
import * as React from "react";

import { StatusBadge } from "@/components/shared/badges";
import { Input, Skeleton } from "@/components/ui/primitives";
import { formatDateOnly } from "@/lib/format";
import { useApplications } from "@/lib/queries";
import type { Application } from "@/lib/types";
import { cn } from "@/lib/utils";

const RESULT_LIMIT = 25;

/** Bold the part of `text` that the query matched, so scanning is quick. */
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

export function ApplicationPicker({
  personId,
  personName,
  value,
  onChange,
  autoFocus,
}: {
  /** Only this person's applications — an interview belongs to one of them. */
  personId: string;
  personName?: string;
  value: string;
  onChange: (applicationId: string, application: Application | null) => void;
  autoFocus?: boolean;
}) {
  const [query, setQuery] = React.useState("");
  const [debounced, setDebounced] = React.useState("");
  const [active, setActive] = React.useState(0);
  const [chosen, setChosen] = React.useState<Application | null>(null);
  const listRef = React.useRef<HTMLUListElement | null>(null);

  React.useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query.trim()), 200);
    return () => window.clearTimeout(timer);
  }, [query]);

  const { data, isLoading, isFetching } = useApplications([personId], {
    q: debounced || undefined,
    limit: RESULT_LIMIT,
    sort: "last_activity",
  });
  const results = React.useMemo(() => data?.items ?? [], [data]);

  // A shorter list can leave the cursor past the end.
  const activeIndex = Math.min(active, Math.max(results.length - 1, 0));

  function pick(application: Application) {
    setChosen(application);
    onChange(application.id, application);
  }

  function clear() {
    setChosen(null);
    onChange("", null);
    setQuery("");
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const next =
        event.key === "ArrowDown"
          ? Math.min(activeIndex + 1, results.length - 1)
          : Math.max(activeIndex - 1, 0);
      setActive(next);
      listRef.current
        ?.querySelectorAll("li")
        [next]?.scrollIntoView({ block: "nearest" });
      return;
    }
    if (event.key === "Enter") {
      // Enter is for the list, not the surrounding form, while choosing.
      event.preventDefault();
      const application = results[activeIndex];
      if (application) pick(application);
    }
  }

  // Once something is chosen the search collapses into a summary of it.
  if (value && chosen) {
    return (
      <div className="flex items-start gap-2 rounded-md border border-primary bg-primary/5 p-2.5">
        <Check className="mt-0.5 size-4 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground">
            {chosen.company_name}
          </p>
          <p className="truncate text-xs text-muted-foreground">
            {chosen.job_title}
            {chosen.applied_date
              ? ` · applied ${formatDateOnly(chosen.applied_date)}`
              : ""}
          </p>
        </div>
        <StatusBadge status={chosen.status} />
        <button
          type="button"
          onClick={clear}
          className="rounded p-1 text-subtle-foreground hover:bg-surface-hover hover:text-foreground"
          aria-label="Choose a different application"
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
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
          onKeyDown={handleKeyDown}
          placeholder={
            personName
              ? `Search ${personName}'s applications…`
              : "Search applications — company, role, notes…"
          }
          className="h-9 pl-8 text-sm"
          role="combobox"
          aria-expanded
          aria-controls="application-picker-results"
          aria-label="Search applications"
        />
      </div>

      <ul
        id="application-picker-results"
        ref={listRef}
        role="listbox"
        aria-label="Matching applications"
        className="mt-1.5 max-h-56 overflow-y-auto rounded-md border border-border"
      >
        {isLoading ? (
          <li className="space-y-1 p-2">
            <Skeleton className="h-9" />
            <Skeleton className="h-9" />
          </li>
        ) : results.length === 0 ? (
          <li className="px-3 py-6 text-center text-xs text-muted-foreground">
            {debounced
              ? `Nothing matches “${debounced}”.`
              : "No applications for this person yet."}
          </li>
        ) : (
          results.map((application, index) => (
            <li key={application.id}>
              <button
                type="button"
                role="option"
                aria-selected={index === activeIndex}
                onMouseEnter={() => setActive(index)}
                onClick={() => pick(application)}
                className={cn(
                  "flex w-full items-center gap-2 border-b border-border px-2.5 py-1.5 text-left last:border-b-0",
                  index === activeIndex ? "bg-surface-hover" : "hover:bg-surface-hover",
                )}
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-foreground">
                    <Highlight text={application.company_name} query={debounced} />
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
            </li>
          ))
        )}
      </ul>

      <p className="mt-1 text-[11px] text-subtle-foreground">
        {isFetching && debounced
          ? "Searching…"
          : results.length === RESULT_LIMIT
            ? `Showing the first ${RESULT_LIMIT} — keep typing to narrow.`
            : "↑ ↓ to move, Enter to choose."}
      </p>
    </div>
  );
}
