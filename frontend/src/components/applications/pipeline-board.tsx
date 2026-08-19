"use client";

/**
 * Kanban pipeline (spec §13).
 *
 * Cards are dragged between the six columns; the drop target decides the new
 * status. The card itself carries person colour, the current step tag, the
 * next interview, follow-up state and days since activity.
 */

import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { AlertCircle, Bell, CalendarClock } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";

import { PersonAvatar, PriorityBadge, StageBadge } from "@/components/shared/badges";
import { Skeleton } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate, formatDaysAgo } from "@/lib/format";
import { useChangeApplicationStatus } from "@/lib/queries";
import type { PipelineCard, PipelineColumn } from "@/lib/types";
import { cn, personTint } from "@/lib/utils";

function Card({
  card,
  dragging,
}: {
  card: PipelineCard;
  dragging?: boolean;
}) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-md border border-border bg-surface p-2.5 shadow-sm",
        dragging && "rotate-1 shadow-lg",
      )}
    >
      <span
        aria-hidden
        className="absolute inset-y-0 left-0 w-1"
        style={{ backgroundColor: card.person_color }}
      />

      <div className="pl-1.5">
        <div className="flex items-start justify-between gap-1.5">
          <p className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
            {card.company_name}
          </p>
          <PersonAvatar
            color={card.person_color}
            initials={card.person_initials}
            title={card.person_name}
            size="sm"
          />
        </div>
        <p className="truncate text-xs text-muted-foreground">
          {card.job_title}
        </p>

        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          {card.current_stage_badge ? (
            <StageBadge badge={card.current_stage_badge} />
          ) : null}
          <PriorityBadge priority={card.priority} />
        </div>

        {card.next_interview ? (
          <p className="mt-1.5 flex items-center gap-1 text-[11px] text-status-info">
            <CalendarClock className="size-3" />
            {formatDate(card.next_interview.starts_at)} ·{" "}
            {card.next_interview.stage_badge}
          </p>
        ) : null}

        <div className="mt-1.5 flex items-center gap-2 text-[11px] text-subtle-foreground">
          <span>{formatDaysAgo(card.days_since_activity)}</span>
          {card.has_overdue_follow_up ? (
            <span className="flex items-center gap-0.5 text-status-danger">
              <AlertCircle className="size-3" />
              Overdue
            </span>
          ) : card.open_follow_up_count > 0 ? (
            <span className="flex items-center gap-0.5 text-status-warn">
              <Bell className="size-3" />
              {card.open_follow_up_count}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function DraggableCard({ card }: { card: PipelineCard }) {
  // Dragging a card changes its status, so a card belonging to someone this
  // user does not look after stays a plain link.
  const { canEdit } = useAuth();
  const draggable = canEdit(card.person_id);
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: card.id,
    data: { card },
    disabled: !draggable,
  });

  return (
    <div
      ref={setNodeRef}
      {...(draggable ? listeners : {})}
      {...attributes}
      className={cn("touch-none", isDragging && "opacity-40")}
    >
      <Link
        href={`/applications/${card.id}`}
        // A drag starts with pointerdown; let the click through only when the
        // pointer did not actually move.
        onClick={(event) => {
          if (isDragging) event.preventDefault();
        }}
        className={cn(
          "block",
          draggable && "cursor-grab active:cursor-grabbing",
        )}
      >
        <Card card={card} />
      </Link>
    </div>
  );
}

function Column({
  column,
  children,
  isOver,
}: {
  column: PipelineColumn;
  children: React.ReactNode;
  isOver: boolean;
}) {
  const { setNodeRef } = useDroppable({ id: column.key });

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "flex min-w-56 flex-1 flex-col rounded-lg border bg-surface-muted/40 transition-colors",
        isOver ? "border-primary bg-primary/5" : "border-border",
      )}
    >
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <p className="text-xs font-semibold text-foreground">{column.label}</p>
        <span className="tabular rounded bg-surface px-1.5 py-0.5 text-[11px] text-muted-foreground">
          {column.count}
        </span>
      </div>
      <div className="flex-1 space-y-2 p-2">{children}</div>
    </div>
  );
}

export function PipelineBoard({
  columns,
  loading,
}: {
  columns: PipelineColumn[];
  loading?: boolean;
}) {
  const changeStatus = useChangeApplicationStatus();
  const [activeCard, setActiveCard] = React.useState<PipelineCard | null>(null);
  const [overColumn, setOverColumn] = React.useState<string | null>(null);

  // A small activation distance keeps ordinary clicks working as links.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );

  function handleDragStart(event: DragStartEvent) {
    setActiveCard((event.active.data.current?.card as PipelineCard) ?? null);
  }

  async function handleDragEnd(event: DragEndEvent) {
    const card = activeCard;
    setActiveCard(null);
    setOverColumn(null);
    if (!card || !event.over) return;

    const targetColumn = String(event.over.id);
    const currentColumn = columns.find((column) =>
      column.cards.some((c) => c.id === card.id),
    )?.key;
    if (targetColumn === currentColumn) return;

    try {
      await changeStatus.mutateAsync({ id: card.id, column: targetColumn });
      toast.success(`${card.company_name} moved to ${targetColumn}`);
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : "Could not move the application.",
      );
    }
  }

  if (loading) {
    return (
      <div className="flex gap-3 overflow-x-auto pb-2">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-96 min-w-56 flex-1" />
        ))}
      </div>
    );
  }

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragOver={(event) =>
        setOverColumn(event.over ? String(event.over.id) : null)
      }
      onDragEnd={handleDragEnd}
      onDragCancel={() => {
        setActiveCard(null);
        setOverColumn(null);
      }}
    >
      <div className="flex gap-3 overflow-x-auto pb-2">
        {columns.map((column) => (
          <Column
            key={column.key}
            column={column}
            isOver={overColumn === column.key}
          >
            {column.cards.length === 0 ? (
              <p className="px-1 py-6 text-center text-[11px] text-subtle-foreground">
                Nothing here
              </p>
            ) : (
              column.cards.map((card) => (
                <DraggableCard key={card.id} card={card} />
              ))
            )}
          </Column>
        ))}
      </div>

      <DragOverlay>
        {activeCard ? (
          <div
            className="w-56"
            style={{ backgroundColor: personTint(activeCard.person_color, 4) }}
          >
            <Card card={activeCard} dragging />
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}
