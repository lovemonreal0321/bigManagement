"use client";

import {
  BarChart3,
  Briefcase,
  CalendarDays,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Settings as SettingsIcon,
  Sun,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import * as React from "react";

import { PersonSelector } from "@/components/layout/person-selector";
import { QuickAddButton } from "@/components/applications/quick-add";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/overlays";
import { Button, Spinner } from "@/components/ui/primitives";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

/** Navigation, kept to the seven sections in the spec — nothing more. */
const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/calendar", label: "Calendar", icon: CalendarDays },
  { href: "/applications", label: "Applications", icon: Briefcase },
  { href: "/follow-ups", label: "Follow-Ups", icon: CheckSquareIcon },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/people", label: "People", icon: Users },
  { href: "/settings", label: "Settings", icon: SettingsIcon },
] as const;

function CheckSquareIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M9 11l3 3L22 4" />
      <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
    </svg>
  );
}

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();

  return (
    <Button
      variant="ghost"
      size="icon-sm"
      aria-label="Toggle theme"
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
    >
      {/*
        Both icons are rendered and CSS picks one from the `dark` class on
        <html>. The server does not know the theme, so deciding in JS would
        either mismatch on hydration or need a mounted flag; letting CSS choose
        avoids both.
      */}
      <Moon className="dark:hidden" />
      <Sun className="hidden dark:block" />
    </Button>
  );
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav className="space-y-0.5">
      {NAV.map((item) => {
        const active =
          pathname === item.href || pathname.startsWith(`${item.href}/`);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors",
              active
                ? "bg-surface-muted text-foreground"
                : "text-muted-foreground hover:bg-surface-hover hover:text-foreground",
            )}
          >
            <Icon className="size-4 shrink-0" />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { status, user, logout } = useAuth();
  const [mobileNavOpen, setMobileNavOpen] = React.useState(false);

  React.useEffect(() => {
    if (status === "anonymous") router.replace("/login");
  }, [status, router]);

  if (status !== "authenticated") {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner className="size-6" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-background">
      {/* Desktop sidebar */}
      <aside className="hidden w-56 shrink-0 flex-col border-r border-border bg-surface lg:flex">
        <div className="px-4 py-4">
          <Link href="/dashboard" className="block">
            <p className="text-sm font-semibold leading-tight tracking-tight text-foreground">
              Job Search
            </p>
            <p className="text-sm font-semibold leading-tight tracking-tight text-primary">
              Command Center
            </p>
          </Link>
        </div>
        <div className="flex-1 px-2">
          <NavLinks />
        </div>
        <div className="border-t border-border p-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-xs text-muted-foreground transition-colors hover:bg-surface-hover">
                <span className="flex size-6 items-center justify-center rounded-full bg-primary text-[10px] font-semibold text-primary-foreground">
                  {user?.display_name?.[0]?.toUpperCase() ?? "A"}
                </span>
                <span className="min-w-0 flex-1 truncate">
                  {user?.username}
                </span>
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuLabel>Signed in</DropdownMenuLabel>
              <DropdownMenuItem asChild>
                <Link href="/settings">
                  <SettingsIcon />
                  Settings
                </Link>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem destructive onSelect={logout}>
                <LogOut />
                Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </aside>

      {/* Mobile nav drawer */}
      {mobileNavOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            className="absolute inset-0 bg-black/40"
            aria-label="Close navigation"
            onClick={() => setMobileNavOpen(false)}
          />
          <div className="relative flex h-full w-64 flex-col border-r border-border bg-surface">
            <div className="flex items-center justify-between px-4 py-4">
              <p className="text-sm font-semibold text-foreground">
                Command Center
              </p>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => setMobileNavOpen(false)}
                aria-label="Close navigation"
              >
                <X />
              </Button>
            </div>
            <div className="flex-1 px-2">
              <NavLinks onNavigate={() => setMobileNavOpen(false)} />
            </div>
            <div className="border-t border-border p-2">
              <Button
                variant="ghost"
                size="sm"
                className="w-full justify-start"
                onClick={logout}
              >
                <LogOut />
                Sign out
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 border-b border-border bg-surface/95 backdrop-blur">
          <div className="flex items-center gap-2 px-3 py-2.5 sm:px-4">
            <Button
              variant="ghost"
              size="icon-sm"
              className="lg:hidden"
              onClick={() => setMobileNavOpen(true)}
              aria-label="Open navigation"
            >
              <Menu />
            </Button>

            <div className="min-w-0 flex-1">
              <PersonSelector />
            </div>

            <div className="flex shrink-0 items-center gap-1">
              <QuickAddButton />
              <ThemeToggle />
            </div>
          </div>
        </header>

        <main className="min-w-0 flex-1 px-3 py-4 sm:px-4 sm:py-5">
          {children}
        </main>
      </div>
    </div>
  );
}
