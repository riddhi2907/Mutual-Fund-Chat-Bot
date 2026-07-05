import type { ChatApiResponse } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export class ChatApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ChatApiError";
  }
}

export async function sendChatMessage(message: string): Promise<ChatApiResponse> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
  } catch {
    throw new ChatApiError(
      "Unable to reach the server. Make sure the API is running on port 8000.",
    );
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) {
        detail = body.detail;
      }
    } catch {
      // ignore JSON parse errors
    }
    throw new ChatApiError(detail, response.status);
  }

  return (await response.json()) as ChatApiResponse;
}
