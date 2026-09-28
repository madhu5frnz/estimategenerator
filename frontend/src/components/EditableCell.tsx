"use client";

import { useEffect, useRef, useState } from "react";

type Props = {
  value: string | null;
  display?: React.ReactNode;
  onSave: (value: string) => Promise<unknown>;
  editable: boolean;
  label: string;
  numeric?: boolean;
  multiline?: boolean;
  placeholder?: string;
  className?: string;
};

/**
 * Click (or Enter/F2 when focused) to edit; Enter or leaving the cell saves, Escape
 * cancels. The saved value shown afterwards is always the server's.
 */
export function EditableCell({ value, display, onSave, editable, label, numeric, multiline, placeholder, className = "" }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? "");
  const [saving, setSaving] = useState(false);
  const ref = useRef<HTMLInputElement & HTMLTextAreaElement>(null);

  useEffect(() => {
    if (editing) ref.current?.select();
  }, [editing]);

  const shown = display ?? (value === null || value === "" ? <span className="text-muted">{placeholder ?? "—"}</span> : value);
  if (!editable) {
    return <div className={`px-2 py-1.5 ${numeric ? "num text-right" : ""} ${className}`}>{shown}</div>;
  }

  async function commit() {
    if (draft === (value ?? "")) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(draft);
      setEditing(false);
    } catch {
      // The error is shown by the page; keep the editor open so the user can fix it.
      ref.current?.focus();
    } finally {
      setSaving(false);
    }
  }

  if (editing) {
    const common = {
      ref,
      "aria-label": label,
      value: draft,
      disabled: saving,
      onChange: (e: React.ChangeEvent<HTMLInputElement & HTMLTextAreaElement>) => setDraft(e.target.value),
      onBlur: () => void commit(),
      onKeyDown: (e: React.KeyboardEvent) => {
        if (e.key === "Escape") {
          setDraft(value ?? "");
          setEditing(false);
        } else if (e.key === "Enter" && !(multiline && e.shiftKey)) {
          e.preventDefault();
          void commit();
        }
      },
      className: `w-full rounded border border-accent bg-surface px-2 py-1 ${numeric ? "num text-right" : ""}`,
    };
    return multiline ? <textarea rows={2} {...common} /> : <input inputMode={numeric ? "decimal" : undefined} {...common} />;
  }

  return (
    <button
      type="button"
      aria-label={`${label}: ${value ?? "empty"}. Click to edit`}
      onClick={() => {
        setDraft(value ?? "");
        setEditing(true);
      }}
      className={`block w-full cursor-text rounded px-2 py-1.5 text-left hover:bg-accent-soft focus:outline focus:outline-accent ${numeric ? "num text-right" : ""} ${className}`}
    >
      {shown}
    </button>
  );
}
