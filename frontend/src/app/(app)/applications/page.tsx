"use client";

import { Briefcase, Filter, LayoutGrid, List, Search, X } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { PipelineBoard } from "@/components/applications/pipeline-board";
import { QuickAddDialog } from "@/components/applications/quick-add";
import {
  PersonAvatar,
  PriorityBadge,
  StageBadge,
  StatusBadge,
} from "@/components/shared/badges";
import { PageHeader } from "@/components/shared/page-header";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
  Tabs,
  TabsList,
  TabsTrigger,
} from "@/components/ui/overlays";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Input,
  Skeleton,
} from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import {
  APPLICATION_STATUS_LABELS,
  formatDate,
  formatDaysAgo,
  formatSalary,
  WORK_MODE_LABELS,
} from "@/lib/format";
import { usePersonFilter } from "@/lib/person-filter";
import {
  useApplications,
  useFilterOptions,
  useInterviewTypes,
  usePipeline,
} from "@/lib/queries";
import {
  APPLICATION_STATUSES,
  WORK_MODES,
  type Application,
} from "@/lib/types";

type ViewMode = "list" | "pipeline";

export default function ApplicationsPage() {
  const searchParams = useSearchParams();
  const { queryIds } = usePersonFilter();
  const { data: filterOptions } = useFilterOptions();
  const { data: types } = useInterviewTypes();

  const [view, setView] = React.useState<ViewMode>(
    searchParams.get("view") === "pipeline" ? "pipeline" : "list",
  );
  const [search, setSearch] = React.useState("");
  const [debounced, setDebounced] = React.useState("");
  const [statuses, setStatuses] = React.useState<string[]>(() => {
    const status = searchParams.get("status");
    return status ? [status] : [];
  });
  const [columns, setColumns] = React.useState<string[]>(() => {
    const column = searchParams.get("column");
    return column ? [column] : [];
  });
  const [workModes, setWorkModes] = React.useState<string[]>([]);
  const [sources, setSources] = React.useState<string[]>([]);
  const [typeKeys, setTypeKeys] = React.useState<string[]>([]);
  const [outcomes, setOutcomes] = React.useState<string[]>(() => {
    const outcome = searchParams.get("outcome");
    return outcome ? [outcome] : [];
  });
  const [hasUpcoming, setHasUpcoming] = React.useState(false);
  const [hasOverdue, setHasOverdue] = React.useState(false);
  const [includeArchived, setIncludeArchived] = React.useState(false);
  const [quickAddOpen, setQuickAddOpen] = React.useState(false);

  // Debounce so typing does not fire a request per keystroke.
  React.useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  const filters = {
    q: debounced || undefined,
    status: statuses.length ? statuses : undefined,
    column: columns.length ? columns : undefined,
    work_mode: workModes.length ? workModes : undefined,
    source: sources.length ? sources : undefined,
    type_key: typeKeys.length ? typeKeys : undefined,
    outcome: outcomes.length ? outcomes : undefined,
    has_upcoming_interview: hasUpcoming || undefined,
    has_overdue_follow_up: hasOverdue || undefined,
    include_archived: includeArchived || undefined,
    limit: 100,
  };

  const list = useApplications(queryIds, filters);
  const pipeline = usePipeline(queryIds, debounced);

  const activeFilterCount =
    statuses.length +
    columns.length +
    workModes.length +
    sources.length +
    typeKeys.length +
    outcomes.length +
    (hasUpcoming ? 1 : 0) +
    (hasOverdue ? 1 : 0) +
    (includeArchived ? 1 : 0);

  function clearFilters() {
    setStatuses([]);
    setColumns([]);
    setWorkModes([]);
    setSources([]);
    setTypeKeys([]);
    setOutcomes([]);
    setHasUpcoming(false);
    setHasOverdue(false);
    setIncludeArchived(false);
  }

  const toggler =
    (setter: React.Dispatch<React.SetStateAction<string[]>>) =>
    (value: string) =>
      setter((current) =>
        current.includes(value)
          ? current.filter((item) => item !== value)
          : [...current, value],
      );

  return (
    <div>
      <PageHeader
        title="Applications"
        description={
          view === "pipeline"
            ? "Drag a card to change its stage."
            : `${list.data?.total ?? 0} application${
                list.data?.total === 1 ? "" : "s"
              }`
        }
        actions={
          <>
            <Tabs
              value={view}
              onValueChange={(value) => setView(value as ViewMode)}
            >
              <TabsList>
                <TabsTrigger value="list">
                  <List className="mr-1 inline size-3.5" />
                  List
                </TabsTrigger>
                <TabsTrigger value="pipeline">
                  <LayoutGrid className="mr-1 inline size-3.5" />
                  Pipeline
                </TabsTrigger>
              </TabsList>
            </Tabs>
            <Button
              size="sm"
              variant="primary"
              onClick={() => setQuickAddOpen(true)}
            >
              New application
            </Button>
          </>
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-48 flex-1 sm:max-w-xs">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-subtle-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search company, role, notes…"
              className="h-8 pl-8 text-xs"
            />
            {search ? (
              <button
                type="button"
                onClick={() => setSearch("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-subtle-foreground hover:text-foreground"
                aria-label="Clear search"
              >
                <X className="size-3.5" />
              </button>
            ) : null}
          </div>

          <Popover>
            <PopoverTrigger asChild>
              <Button size="sm" variant="secondary">
                <Filter />
                Filters
                {activeFilterCount > 0 ? (
                  <span className="ml-0.5 rounded bg-primary px-1 text-[10px] text-primary-foreground">
                    {activeFilterCount}
                  </span>
                ) : null}
              </Button>
            </PopoverTrigger>
            <PopoverContent align="start" className="max-h-[70vh] w-72 overflow-y-auto">
              <FilterGroup title="Status">
                {APPLICATION_STATUSES.map((status) => (
                  <FilterCheck
                    key={status}
                    label={APPLICATION_STATUS_LABELS[status]}
                    checked={statuses.includes(status)}
                    onChange={() => toggler(setStatuses)(status)}
                  />
                ))}
              </FilterGroup>

              <FilterGroup title="Work mode">
                {WORK_MODES.map((mode) => (
                  <FilterCheck
                    key={mode}
                    label={WORK_MODE_LABELS[mode]}
                    checked={workModes.includes(mode)}
                    onChange={() => toggler(setWorkModes)(mode)}
                  />
                ))}
              </FilterGroup>

              {filterOptions?.sources.length ? (
                <FilterGroup title="Source">
                  {filterOptions.sources.map((source) => (
                    <FilterCheck
                      key={source}
                      label={source}
                      checked={sources.includes(source)}
                      onChange={() => toggler(setSources)(source)}
                    />
                  ))}
                </FilterGroup>
              ) : null}

              <FilterGroup title="Interview stage">
                {(types ?? []).map((type) => (
                  <FilterCheck
                    key={type.key}
                    label={type.label}
                    checked={typeKeys.includes(type.key)}
                    onChange={() => toggler(setTypeKeys)(type.key)}
                  />
                ))}
              </FilterGroup>

              <FilterGroup title="Interview outcome">
                {(filterOptions?.outcomes ?? []).map((outcome) => (
                  <FilterCheck
                    key={outcome}
                    label={outcome.replace(/_/g, " ")}
                    checked={outcomes.includes(outcome)}
                    onChange={() => toggler(setOutcomes)(outcome)}
                  />
                ))}
              </FilterGroup>

              <FilterGroup title="Other">
                <FilterCheck
                  label="Has upcoming interview"
                  checked={hasUpcoming}
                  onChange={() => setHasUpcoming((value) => !value)}
                />
                <FilterCheck
                  label="Has overdue follow-up"
                  checked={hasOverdue}
                  onChange={() => setHasOverdue((value) => !value)}
                />
                <FilterCheck
                  label="Include archived"
                  checked={includeArchived}
                  onChange={() => setIncludeArchived((value) => !value)}
                />
              </FilterGroup>

              {activeFilterCount > 0 ? (
                <Button
                  size="xs"
                  variant="ghost"
                  className="mt-2 w-full"
                  onClick={clearFilters}
                >
                  Clear all filters
                </Button>
              ) : null}
            </PopoverContent>
          </Popover>
        </div>
      </PageHeader>

      {view === "pipeline" ? (
        pipeline.isError ? (
          <Card>
            <ErrorState
              message={
                pipeline.error instanceof ApiError
                  ? pipeline.error.message
                  : undefined
              }
              onRetry={() => pipeline.refetch()}
            />
          </Card>
        ) : (
          <PipelineBoard
            columns={pipeline.data?.columns ?? []}
            loading={pipeline.isLoading}
          />
        )
      ) : list.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-16" />
          ))}
        </div>
      ) : list.isError ? (
        <Card>
          <ErrorState
            message={
              list.error instanceof ApiError ? list.error.message : undefined
            }
            onRetry={() => list.refetch()}
          />
        </Card>
      ) : (list.data?.items.length ?? 0) === 0 ? (
        <Card>
          <EmptyState
            icon={Briefcase}
            title={
              activeFilterCount > 0 || debounced
                ? "No applications match those filters"
                : "No applications yet"
            }
            description={
              activeFilterCount > 0 || debounced
                ? "Try widening the search or clearing a filter."
                : "Add the first one — it takes three fields."
            }
            action={
              activeFilterCount > 0 || debounced ? (
                <Button size="sm" onClick={clearFilters}>
                  Clear filters
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() => setQuickAddOpen(true)}
                >
                  New application
                </Button>
              )
            }
          />
        </Card>
      ) : (
        <Card className="divide-y divide-border overflow-hidden">
          {list.data?.items.map((application) => (
            <ApplicationRow key={application.id} application={application} />
          ))}
        </Card>
      )}

      <QuickAddDialog open={quickAddOpen} onOpenChange={setQuickAddOpen} />
    </div>
  );
}

function FilterGroup({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-3">
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-subtle-foreground">
        {title}
      </p>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function FilterCheck({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-xs capitalize hover:bg-surface-hover">
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="size-3.5 accent-[var(--primary)]"
      />
      {label}
    </label>
  );
}

function ApplicationRow({ application }: { application: Application }) {
  const salary = formatSalary(
    application.salary_min,
    application.salary_max,
    application.salary_currency,
  );

  return (
    <Link
      href={`/applications/${application.id}`}
      className="relative flex items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-hover"
    >
      <span
        aria-hidden
        className="absolute inset-y-0 left-0 w-1"
        style={{ backgroundColor: application.person?.color ?? "#64748b" }}
      />
      <PersonAvatar
        color={application.person?.color ?? "#64748b"}
        initials={application.person?.initials ?? "?"}
        title={application.person?.display_name}
        size="lg"
        className="ml-1"
      />

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="truncate text-sm font-medium text-foreground">
            {application.company_name}
          </span>
          <StatusBadge status={application.status} />
          {application.current_stage_badge ? (
            <StageBadge badge={application.current_stage_badge} />
          ) : null}
          <PriorityBadge priority={application.priority} />
        </div>
        <p className="truncate text-xs text-muted-foreground">
          {application.job_title}
          {application.location ? ` · ${application.location}` : ""}
          {salary ? ` · ${salary}` : ""}
        </p>
      </div>

      <div className="hidden shrink-0 text-right sm:block">
        {application.next_interview ? (
          <p className="text-xs font-medium text-status-info">
            {formatDate(application.next_interview.starts_at)} ·{" "}
            {application.next_interview.stage_badge}
          </p>
        ) : (
          <p className="text-xs text-subtle-foreground">No interview booked</p>
        )}
        <p className="text-[11px] text-subtle-foreground">
          {application.has_overdue_follow_up ? (
            <span className="text-status-danger">Follow-up overdue</span>
          ) : (
            `Active ${formatDaysAgo(application.days_since_activity)}`
          )}
        </p>
      </div>
    </Link>
  );
}
