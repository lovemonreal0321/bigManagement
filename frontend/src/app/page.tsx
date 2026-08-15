"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Spinner } from "@/components/ui/primitives";
import { useAuth } from "@/lib/auth";

/** Entry point: send the user to the dashboard or the login screen. */
export default function IndexPage() {
  const router = useRouter();
  const { status } = useAuth();

  useEffect(() => {
    if (status === "authenticated") router.replace("/dashboard");
    else if (status === "anonymous") router.replace("/login");
  }, [status, router]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <Spinner className="size-6" />
    </div>
  );
}
