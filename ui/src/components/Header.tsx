import { WELCOME_TEXT } from "../types";

export function Header() {
  return (
    <header className="border-b border-slate-200 bg-white px-4 py-5 sm:px-6">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-start gap-3">
          <div
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-600 text-sm font-bold text-white"
            aria-hidden="true"
          >
            HDFC
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-tight text-slate-900 sm:text-xl">
              HDFC Mutual Fund FAQ Assistant
            </h1>
            <p className="mt-1 text-sm leading-relaxed text-slate-600">{WELCOME_TEXT}</p>
          </div>
        </div>
      </div>
    </header>
  );
}
