import type { ChatMessage } from "../types";

interface ChatMessageBubbleProps {
  message: ChatMessage;
}

function formatAssistantBody(content: string): string[] {
  return content
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

export function ChatMessageBubble({ message }: ChatMessageBubbleProps) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-brand-600 px-4 py-3 text-sm leading-relaxed text-white shadow-sm">
          {message.content}
        </div>
      </div>
    );
  }

  const lines = formatAssistantBody(message.content);
  const showCitation =
    !message.isError &&
    message.citationUrl &&
    (message.responseType === "answer" || message.responseType === "scheme_link");

  return (
    <div className="flex justify-start">
      <div
        className={`max-w-[90%] rounded-2xl rounded-bl-md border px-4 py-3 text-sm leading-relaxed shadow-sm ${
          message.isError
            ? "border-red-200 bg-red-50 text-red-800"
            : message.responseType === "refusal"
              ? "border-slate-200 bg-slate-50 text-slate-700"
              : "border-slate-200 bg-white text-slate-800"
        }`}
      >
        <div className="space-y-2">
          {lines.map((line, index) => (
            <p key={index}>{line}</p>
          ))}
        </div>

        {message.scheme && !message.isError && (
          <p className="mt-2 text-xs font-medium text-slate-500">{message.scheme}</p>
        )}

        {showCitation && (
          <a
            href={message.citationUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-brand-600 underline decoration-brand-300 underline-offset-2 hover:text-brand-700"
          >
            View on Groww
            <span aria-hidden="true">↗</span>
          </a>
        )}

        {message.lastUpdated && !message.isError && message.responseType === "answer" && (
          <p className="mt-2 text-xs text-slate-400">
            Last updated from sources: {message.lastUpdated}
          </p>
        )}
      </div>
    </div>
  );
}
