export type ChatResponseType = "answer" | "refusal" | "scheme_link";

export interface ChatApiResponse {
  type: ChatResponseType;
  message: string;
  citation_url?: string;
  scheme?: string;
  last_updated?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  responseType?: ChatResponseType;
  citationUrl?: string;
  scheme?: string;
  lastUpdated?: string;
  isError?: boolean;
}

export const WELCOME_TEXT =
  "Ask factual questions about HDFC Mutual Fund schemes — expense ratio, exit load, SIP minimums, benchmarks, and more.";

export const DISCLAIMER_TEXT = "Facts-only. No investment advice.";

export const EXAMPLE_QUESTIONS = [
  "What is the expense ratio of HDFC Mid Cap Fund Direct Growth?",
  "What is the exit load on HDFC Gold ETF Fund of Fund?",
  "What is the benchmark for HDFC Large Cap Fund Direct Growth?",
] as const;

export const LOADING_TEXT = "Searching fund information…";
