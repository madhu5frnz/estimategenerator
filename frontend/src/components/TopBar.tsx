"use client";

import { useState } from "react";

import { post } from "@/lib/api";

import { useSession } from "./Session";

export function TopBar() {
  const { me } = useSession();
  const [busy, setBusy] = useState(false);

  async function signOut() {
    setBusy(true);
    try {
      await post("/auth/logout", undefined, { redirectOn401: false });
    } finally {
      // Full reload on purpose: drops every piece of client state from the old session.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/login");
    }
  }

  return (
    <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-1 border-b border-line px-6 py-2 text-xs">
      <span className="text-muted">
        {me.organization.name} · <span className="font-medium text-ink">{me.subscription.plan_name} plan</span>
      </span>
      <span className="font-medium">{me.user.full_name}</span>
      <button onClick={signOut} disabled={busy} className="rounded px-2 py-1 text-accent hover:bg-panel">
        Sign out
      </button>
    </div>
  );
}

export function VerifyEmailBanner() {
  const { me } = useSession();
  const [sent, setSent] = useState(false);
  if (me.user.email_verified) return null;
  return (
    <div role="status" className="border-b border-warn/30 bg-amber-50 px-6 py-2 text-xs text-warn">
      Please confirm your email address ({me.user.email}). Check your inbox for the link.{" "}
      {sent ? (
        <span>A new link has been sent.</span>
      ) : (
        <button
          className="underline"
          onClick={async () => {
            await post("/auth/resend-verification");
            setSent(true);
          }}
        >
          Send it again
        </button>
      )}
    </div>
  );
}
