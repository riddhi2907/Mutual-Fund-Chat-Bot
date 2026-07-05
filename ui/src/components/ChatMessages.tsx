import type { ChatMessage } from "../types";
import { ChatMessageBubble } from "./ChatMessageBubble";
import { LOADING_TEXT } from "../types";

interface ChatMessagesProps {
  messages: ChatMessage[];
  isLoading: boolean;
}

export function ChatMessages({ messages, isLoading }: ChatMessagesProps) {
  return (
    <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4 sm:px-6">
      {messages.length === 0 && !isLoading && (
        <p className="text-center text-sm text-slate-400">
          Send a question or pick an example below.
        </p>
      )}

      {messages.map((message) => (
        <ChatMessageBubble key={message.id} message={message} />
      ))}

      {isLoading && (
        <div className="flex justify-start" aria-live="polite" aria-busy="true">
          <div className="flex items-center gap-2 rounded-2xl rounded-bl-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500 shadow-sm">
            <span className="inline-flex gap-1" aria-hidden="true">
              <span className="h-2 w-2 animate-bounce rounded-full bg-brand-500 [animation-delay:-0.3s]" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-brand-500 [animation-delay:-0.15s]" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-brand-500" />
            </span>
            {LOADING_TEXT}
          </div>
        </div>
      )}
    </div>
  );
}
