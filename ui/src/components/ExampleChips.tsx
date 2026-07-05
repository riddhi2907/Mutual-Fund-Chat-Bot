interface ExampleChipsProps {
  questions: readonly string[];
  onSelect: (question: string) => void;
  disabled?: boolean;
}

export function ExampleChips({ questions, onSelect, disabled }: ExampleChipsProps) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
        Try an example
      </p>
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        {questions.map((question) => (
          <button
            key={question}
            type="button"
            disabled={disabled}
            onClick={() => onSelect(question)}
            className="rounded-full border border-slate-200 bg-white px-4 py-2 text-left text-sm text-slate-700 shadow-sm transition hover:border-brand-500 hover:bg-brand-50 hover:text-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {question}
          </button>
        ))}
      </div>
    </div>
  );
}
