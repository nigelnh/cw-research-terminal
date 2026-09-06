import { createContext, useContext, useMemo, useRef, type ReactNode } from "react";
import { useAuth } from "@/data/auth";
import { useAiChat, DEFAULT_AI_CHAT_ENDPOINT, type ResearchContextEnvelope } from "./use_ai_chat";

/**
 * One `useAiChat` instance for the whole app. The docked REPL input and the floating
 * conversation panel are separate components that must share the same conversation,
 * streaming state and history — a per-component hook call would give each its own.
 *
 * `latestContext` lets the panel (and any resend) ground on the current selection even
 * though only the docked input passes context explicitly today.
 */
type AiChat = ReturnType<typeof useAiChat> & {
  latestContext: () => ResearchContextEnvelope | undefined;
  setLatestContext: (c: ResearchContextEnvelope | undefined) => void;
};

const AiChatContext = createContext<AiChat | null>(null);

export function AiChatProvider({ children }: { children: ReactNode }) {
  const { user, status } = useAuth();
  // `undefined` while auth is still settling so a reload doesn't read as a user switch.
  const subject = status === "loading" ? undefined : user?.id ?? null;
  const chat = useAiChat(DEFAULT_AI_CHAT_ENDPOINT, subject);
  const ctxRef = useRef<ResearchContextEnvelope | undefined>(undefined);

  const value = useMemo<AiChat>(
    () => ({
      ...chat,
      latestContext: () => ctxRef.current,
      setLatestContext: (c) => {
        ctxRef.current = c;
      },
    }),
    [chat],
  );

  return <AiChatContext.Provider value={value}>{children}</AiChatContext.Provider>;
}

export function useAiChatContext(): AiChat {
  const ctx = useContext(AiChatContext);
  if (!ctx) throw new Error("useAiChatContext must be used within <AiChatProvider>");
  return ctx;
}
