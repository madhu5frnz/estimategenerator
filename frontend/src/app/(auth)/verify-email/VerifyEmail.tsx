"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui";
import { ApiError, post } from "@/lib/api";

export function VerifyEmail() {
  const token = useSearchParams().get("token") ?? "";
  const [state, setState] = useState<{ ok: boolean; message: string } | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return; // React strict mode runs effects twice in development
    started.current = true;
    if (!token) return;
    post("/auth/verify-email", { token }, { redirectOn401: false })
      .then(() => setState({ ok: true, message: "Your email address is confirmed." }))
      .catch((e: unknown) =>
        setState({ ok: false, message: e instanceof ApiError ? e.message : "Confirmation failed." }),
      );
  }, [token]);

  if (!token) return <Alert>This confirmation link is incomplete.</Alert>;
  if (!state) return <p className="text-muted">Confirming…</p>;
  return (
    <div className="space-y-4">
      <Alert tone={state.ok ? "ok" : "bad"}>{state.message}</Alert>
      <Link href="/dashboard" className="block text-center text-accent hover:underline">
        Go to dashboard
      </Link>
    </div>
  );
}
