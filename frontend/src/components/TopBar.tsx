"use client";

import { useState } from "react";

import { post } from "@/lib/api";

import { useSession } from "./Session";

export function UserMenu() {
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
    <div className="flex items-center gap-2 text-xs">
      <span className="hidden text-right leading-tight sm:block">
        <span className="block font-medium">{me.user.full_name}</span>
        <span className="block text-muted">{me.organization.name}</span>
      </span>
      <button onClick={signOut} disabled={busy} className="rounded-full border border-line bg-surface px-3 py-1 font-medium hover:bg-panel">
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
    <div role="status" className="no-print border-b border-warn/30 bg-accent-soft px-6 py-2 text-xs text-warn">
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
