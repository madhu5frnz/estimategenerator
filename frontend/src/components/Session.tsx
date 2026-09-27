"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { api, ApiError, type Me } from "@/lib/api";

type SessionValue = { me: Me; reload: () => Promise<void> };
const SessionContext = createContext<SessionValue | null>(null);

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>");
  return value;
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    () =>
      api<Me>("/me")
        .then(setMe)
        .catch((e: unknown) => {
          // A 401 has already sent the browser to /login.
          if (e instanceof ApiError && e.status !== 401) setError(e.message);
        }),
    [],
  );

  useEffect(() => {
    api<Me>("/me")
      .then(setMe)
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status !== 401) setError(e.message);
      });
  }, []);

  const reload = useCallback(async () => {
    await load();
  }, [load]);

  if (error) return <p className="p-6 text-bad">{error}</p>;
  if (!me) return <p className="p-6 text-muted">Loading…</p>;
  return <SessionContext.Provider value={{ me, reload }}>{children}</SessionContext.Provider>;
}
