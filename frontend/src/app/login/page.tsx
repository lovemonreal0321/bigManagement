"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button, Card, Field, Input } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const { login, status } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (status === "authenticated") router.replace("/dashboard");
  }, [status, router]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username.trim(), password);
      router.replace("/dashboard");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not sign in. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <h1 className="text-lg font-semibold tracking-tight text-foreground">
            Job Search Command Center
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">
            Sign in to your workspace
          </p>
        </div>

        <Card className="p-5">
          <form onSubmit={handleSubmit} className="space-y-4">
            <Field label="Username" htmlFor="username">
              <Input
                id="username"
                name="username"
                autoComplete="username"
                autoFocus
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin321"
                required
              />
            </Field>

            <Field label="Password" htmlFor="password">
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
              />
            </Field>

            {error ? (
              <p
                role="alert"
                className="rounded-md border border-status-danger/30 bg-status-danger-bg px-3 py-2 text-xs text-status-danger"
              >
                {error}
              </p>
            ) : null}

            <Button
              type="submit"
              variant="primary"
              className="w-full"
              loading={submitting}
            >
              Sign in
            </Button>
          </form>
        </Card>

        <p className="mt-4 text-center text-[11px] text-subtle-foreground">
          Credentials are set with ADMIN_USERNAME / ADMIN_PASSWORD in
          backend/.env
        </p>
      </div>
    </main>
  );
}
