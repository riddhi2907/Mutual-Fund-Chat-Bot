import { useCallback, useState } from "react";
import { ChatApiError, sendChatMessage } from "./api/chat";
import { ChatInput } from "./components/ChatInput";
import { ChatMessages } from "./components/ChatMessages";
import { DisclaimerBar } from "./components/DisclaimerBar";
import { ExampleChips } from "./components/ExampleChips";
import { Header } from "./components/Header";
import { EXAMPLE_QUESTIONS, type ChatMessage } from "./types";

function createId(): string {
  return crypto.randomUUID();
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const sendMessage = useCallback(async (text: string) => {
    const userMessage: ChatMessage = {
      id: createId(),
      role: "user",
      content: text,
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);

    try {
      const response = await sendChatMessage(text);
      const assistantMessage: ChatMessage = {
        id: createId(),
        role: "assistant",
        content: response.message,
        responseType: response.type,
        citationUrl: response.citation_url,
        scheme: response.scheme,
        lastUpdated: response.last_updated,
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      const detail =
        error instanceof ChatApiError
          ? error.message
          : "Something went wrong. Please try again.";
      setMessages((prev) => [
        ...prev,
        {
          id: createId(),
          role: "assistant",
          content: detail,
          isError: true,
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const showExamples = messages.length === 0 && !isLoading;

  return (
    <div className="flex h-full min-h-dvh flex-col">
      <DisclaimerBar />
      <Header />

      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col overflow-hidden">
        <ChatMessages messages={messages} isLoading={isLoading} />

        {showExamples && (
          <div className="border-t border-slate-100 bg-slate-50/80 px-4 py-4 sm:px-6">
            <ExampleChips
              questions={EXAMPLE_QUESTIONS}
              onSelect={sendMessage}
              disabled={isLoading}
            />
          </div>
        )}

        <ChatInput onSend={sendMessage} disabled={isLoading} />
      </main>
    </div>
  );
}
