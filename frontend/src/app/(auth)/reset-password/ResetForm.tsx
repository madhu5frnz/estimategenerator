"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { Alert, Button, Field, Input } from "@/components/ui";
import { ApiError, post } from "@/lib/api";

export function ResetForm() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await post("/auth/reset-password", { token, password }, { redirectOn401: false });
      setDone(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Reset failed.");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="space-y-4">
        <Alert tone="ok">Your password has been changed. Other devices have been signed out.</Alert>
        <Link href="/login" className="block text-center text-accent hover:underline">
          Sign in
        </Link>
      </div>
    );
  }
  if (!token) return <Alert>This reset link is incomplete. Please request a new one.</Alert>;

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <h1 className="text-lg font-semibold">Set a new password</h1>
      {error ? <Alert>{error}</Alert> : null}
      <Field label="New password" hint="At least 8 characters.">
        <Input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </Field>
      <Field label="Confirm new password">
        <Input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      </Field>
      <Button type="submit" disabled={busy} className="w-full">
        Update password
      </Button>
    </form>
  );
}
