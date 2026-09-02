"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import * as React from "react";
import { Toaster } from "sonner";

import { UndoProvider } from "@/lib/undo";

import { TooltipProvider } from "@/components/ui/overlays";
import { ApiError } from "@/lib/api";
import { AuthProvider } from "@/lib/auth";
import { PersonFilterProvider } from "@/lib/person-filter";

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          // Never retry a request the server has already judged: a 404 or a
          // validation error will fail identically every time.
          if (error instanceof ApiError) {
            if (error.status >= 400 && error.status < 500) return false;
            return error.retryable && failureCount < 2;
          }
          return failureCount < 2;
        },
      },
      mutations: { retry: false },
    },
  });
}

export function Providers({ children }: { children: React.ReactNode }) {
  // One client per browser session, created lazily so it is not shared across
  // requests during SSR.
  const [queryClient] = React.useState(makeQueryClient);

  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
    >
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <PersonFilterProvider>
            <TooltipProvider delayDuration={250}>
              <UndoProvider>{children}</UndoProvider>
              <Toaster
                position="top-right"
                toastOptions={{
                  classNames: {
                    toast:
                      "!bg-surface !text-foreground !border-border !shadow-lg",
                    description: "!text-muted-foreground",
                  },
                }}
              />
            </TooltipProvider>
          </PersonFilterProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
