"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
} from "react";

import {
  fetchMe,
  login as apiLogin,
  logout as apiLogout,
  setUnauthorizedHandler,
  TOKEN_KEY,
} from "./api";
import {
  useIsHydrated,
  useStoredValue,
  writeStoredValue,
} from "./browser-hooks";
import type { AuthUser } from "./types";

interface AuthState {
  user: AuthUser | null;
  status: "loading" | "authenticated" | "anonymous";
  /** Full access to the workspace: people, settings, connections, users. */
  isAdmin: boolean;
  /**
   * Whether this user may change records belonging to `personId`.
   *
   * The server enforces the same rule; this exists so the UI can disable a
   * control instead of letting someone fill in a form and then be refused.
   * Passing `null`/`undefined` (person not yet chosen) answers `false` for a
   * general user, so nothing is enabled by accident.
   */
  canEdit: (personId: string | null | undefined) => boolean;
  /**
   * Whether the Jobs section is visible at all. Salary is the one thing this
   * workspace does not share by default, so an admin grants it per account.
   */
  canViewJobs: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const queryClient = useQueryClient();

  // The token is browser state, so it is subscribed to rather than mirrored
  // into React state — a login in another tab updates this one too.
  const token = useStoredValue(TOKEN_KEY);
  const hydrated = useIsHydrated();

  // Session restore is a query, not an effect: no read-then-setState, and the
  // result is cached and shared.
  const me = useQuery({
    queryKey: ["auth", "me", token],
    queryFn: fetchMe,
    enabled: Boolean(token),
    retry: false,
    staleTime: 5 * 60_000,
  });

  // Any 401 anywhere drops the session and returns to the login screen.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      queryClient.clear();
      router.replace("/login");
    });
    return () => setUnauthorizedHandler(null);
  }, [router, queryClient]);

  const login = useCallback(
    async (username: string, password: string) => {
      const result = await apiLogin(username, password);
      // `apiLogin` stores the token, which re-runs the `me` query.
      queryClient.setQueryData(
        ["auth", "me", result.access_token],
        result.user,
      );
    },
    [queryClient],
  );

  const logout = useCallback(() => {
    apiLogout();
    queryClient.clear();
    router.replace("/login");
  }, [router, queryClient]);

  const value = useMemo<AuthState>(() => {
    let status: AuthState["status"];
    // Until hydration finishes, localStorage has not been read yet, so a
    // missing token means "unknown", not "signed out". Reporting `anonymous`
    // here would redirect every direct page load to /login.
    if (!hydrated) status = "loading";
    else if (!token) status = "anonymous";
    else if (me.isError) status = "anonymous";
    else if (me.data) status = "authenticated";
    else status = "loading";

    const user = me.data ?? null;
    const isAdmin = user?.role === "admin";
    const assigned = new Set(user?.assigned_person_ids ?? []);
    const canEdit = (personId: string | null | undefined) =>
      isAdmin ? true : Boolean(personId) && assigned.has(personId!);

    const canViewJobs = isAdmin || Boolean(user?.can_view_jobs);

    return { user, status, isAdmin, canEdit, canViewJobs, login, logout };
  }, [hydrated, token, me.data, me.isError, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

export { writeStoredValue };
