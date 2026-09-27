// Display formatting only. Values arrive from the API as exact decimal strings; nothing
// here does arithmetic on them.

function groupIndian(digits: string): string {
  if (digits.length <= 3) return digits;
  const tail = digits.slice(-3);
  let head = digits.slice(0, -3);
  const pairs: string[] = [];
  while (head.length > 2) {
    pairs.unshift(head.slice(-2));
    head = head.slice(0, -2);
  }
  if (head) pairs.unshift(head);
  return [...pairs, tail].join(",");
}

/** "3097500.00" → "₹30,97,500.00". Returns "—" for empty values. */
export function inr(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const negative = value.startsWith("-");
  const [whole = "0", fraction = ""] = value.replace("-", "").split(".");
  const paise = (fraction + "00").slice(0, 2);
  return `${negative ? "-" : ""}₹${groupIndian(whole)}.${paise}`;
}

/** "2026-09-27" or ISO timestamp → "27-09-2026". */
export function indianDate(value: string | null | undefined): string {
  if (!value) return "—";
  const [y, m, d] = value.slice(0, 10).split("-");
  return y && m && d ? `${d}-${m}-${y}` : value;
}

export const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  in_progress: "In progress",
  completed: "Completed",
  archived: "Archived",
};
