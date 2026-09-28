"use client";

import { useSyncExternalStore } from "react";

const KEY = "eai-theme";

/** Light / dark switch. The choice is kept in this browser only. */
export function ThemeToggle() {
  const dark = useSyncExternalStore(subscribe, isDark, () => false);

  function toggle() {
    const next = !dark;
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem(KEY, next ? "dark" : "light");
    } catch {
      // Storage can be blocked (private mode); the switch still works for this page.
    }
  }

  return (
    <button
      onClick={toggle}
      className="no-print inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 text-xs font-medium text-ink hover:bg-panel"
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
    >
      <span aria-hidden>{dark ? "☀" : "☾"}</span> {dark ? "Light" : "Dark"}
    </button>
  );
}

function isDark(): boolean {
  return document.documentElement.classList.contains("dark");
}

function subscribe(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
}

/** Runs before first paint so the page never flashes the wrong theme. */
export const THEME_SCRIPT = `try{var t=localStorage.getItem("${KEY}");if(t==="dark"||(!t&&window.matchMedia("(prefers-color-scheme: dark)").matches))document.documentElement.classList.add("dark")}catch(e){}`;
