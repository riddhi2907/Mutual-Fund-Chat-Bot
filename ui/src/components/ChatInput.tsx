import { useState, type FormEvent, type KeyboardEvent } from "react";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
}

export function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [value, setValue] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed) {
      setValidationError("Please enter a question before sending.");
      return;
    }
    setValidationError(null);
    onSend(trimmed);
    setValue("");
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    submit();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!disabled) {
        submit();
      }
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="border-t border-slate-200 bg-white px-4 py-4 sm:px-6"
    >
      <div className="mx-auto flex max-w-3xl flex-col gap-2">
        {validationError && (
          <p className="text-sm text-red-600" role="alert">
            {validationError}
          </p>
        )}
        <div className="flex items-end gap-2">
          <label htmlFor="chat-input" className="sr-only">
            Your question
          </label>
          <textarea
            id="chat-input"
            rows={2}
            value={value}
            disabled={disabled}
            placeholder="Ask about expense ratio, exit load, SIP minimums…"
            onChange={(event) => {
              setValue(event.target.value);
              if (validationError) {
                setValidationError(null);
              }
            }}
            onKeyDown={handleKeyDown}
            className="min-h-[44px] flex-1 resize-none rounded-xl border border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-500 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={disabled}
            className="inline-flex h-11 shrink-0 items-center justify-center rounded-xl bg-brand-600 px-5 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Send
          </button>
        </div>
        <p className="text-xs text-slate-400">Press Enter to send, Shift+Enter for a new line.</p>
      </div>
    </form>
  );
}
