export const DISCLAIMER =
  "AI-generated estimates are provided as an assistive tool. Verify quantities, " +
  "specifications, rates, applicable standards, SOR provisions and statutory requirements " +
  "before using the estimate for tendering, approval, billing or construction.";

export function Disclaimer() {
  return (
    <p role="note" className="border-t border-line bg-panel px-6 py-2 text-xs text-muted">
      {DISCLAIMER}
    </p>
  );
}
