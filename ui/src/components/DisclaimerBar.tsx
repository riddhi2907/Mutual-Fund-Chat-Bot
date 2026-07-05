import { DISCLAIMER_TEXT } from "../types";

export function DisclaimerBar() {
  return (
    <div
      className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-center text-sm font-medium text-amber-900"
      role="note"
      aria-label="Disclaimer"
    >
      {DISCLAIMER_TEXT}
    </div>
  );
}
