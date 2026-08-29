/**
 * CW Research Terminal — Versioned Copilot Conversation History Store
 * Schema Version: 2
 * Key: cw_research:copilot_history:v2
 */

export const COPILOT_STORAGE_KEY_V2 = "cw_research:copilot_history:v2";
export const LEGACY_STORAGE_KEY_V1 = "cw_research:copilot:v1";
export const MAX_CONVERSATIONS = 25;
export const MAX_MESSAGES_PER_CONVERSATION = 50;

export interface StoredChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  createdAt: number;
}

export interface StoredConversation {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: StoredChatMessage[];
}

export interface CopilotHistoryStore {
  version: 2;
  activeConversationId: string | null;
  conversations: StoredConversation[];
}

/**
 * Creates a unique random ID for conversations and messages.
 */
export function generateId(prefix: string = "id"): string {
  const ts = Date.now().toString(36);
  const rand = Math.random().toString(36).slice(2, 8);
  return `${prefix}_${ts}_${rand}`;
}

/**
 * Creates a fresh empty conversation with a generated ID.
 */
export function createEmptyConversation(): StoredConversation {
  const now = Date.now();
  return {
    id: generateId("conv"),
    title: "New conversation",
    createdAt: now,
    updatedAt: now,
    messages: [],
  };
}

/**
 * Generates a clean human-readable conversation title from the first user message.
 * Collapses line breaks, trims whitespace, and strips raw Markdown syntax.
 */
export function generateConversationTitle(firstUserMessage: string): string {
  if (!firstUserMessage || !firstUserMessage.trim()) {
    return "New conversation";
  }

  const cleaned = firstUserMessage
    .replace(/\r?\n+/g, " ")
    .replace(/\s+/g, " ")
    .replace(/[*_#`]/g, "")
    .trim();

  if (cleaned.length <= 48) {
    return cleaned;
  }

  return cleaned.slice(0, 48).trimEnd() + "…";
}

/**
 * Formats a timestamp into a compact relative or short date label for the history panel.
 */
export function formatRelativeTime(timestamp: number): string {
  if (!timestamp || isNaN(timestamp)) return "";
  const diffSec = Math.floor((Date.now() - timestamp) / 1000);

  if (diffSec < 45) return "Just now";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  if (diffSec < 172800) return "Yesterday";

  return new Date(timestamp).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

/**
 * Loads the conversation history store from localStorage.
 * Safely migrates legacy single-chat v1 stores to the v2 conversation schema.
 */
export function loadCopilotHistory(): CopilotHistoryStore {
  if (typeof window === "undefined" || !window.localStorage) {
    const initial = createEmptyConversation();
    return {
      version: 2,
      activeConversationId: initial.id,
      conversations: [initial],
    };
  }

  try {
    // 1. Try loading canonical v2 schema
    const rawV2 = window.localStorage.getItem(COPILOT_STORAGE_KEY_V2);
    if (rawV2) {
      const parsed = JSON.parse(rawV2);
      if (
        parsed &&
        parsed.version === 2 &&
        Array.isArray(parsed.conversations) &&
        parsed.conversations.length > 0
      ) {
        // Validate and clean conversations
        const validConversations: StoredConversation[] = parsed.conversations
          .filter((c: any) => c && typeof c.id === "string" && Array.isArray(c.messages))
          .map((c: any) => ({
            id: c.id,
            title: c.title || "Conversation",
            createdAt: typeof c.createdAt === "number" ? c.createdAt : Date.now(),
            updatedAt: typeof c.updatedAt === "number" ? c.updatedAt : Date.now(),
            messages: (c.messages || [])
              .filter(
                (m: any) =>
                  m &&
                  (m.role === "user" || m.role === "assistant") &&
                  typeof m.content === "string" &&
                  m.content.trim().length > 0
              )
              .map((m: any) => ({
                id: m.id || generateId("msg"),
                role: m.role,
                content: m.content,
                createdAt: typeof m.createdAt === "number" ? m.createdAt : Date.now(),
              }))
              .slice(-MAX_MESSAGES_PER_CONVERSATION),
          }));

        if (validConversations.length > 0) {
          // Verify active ID belongs to valid conversations
          let activeId = parsed.activeConversationId;
          if (!activeId || !validConversations.some((c) => c.id === activeId)) {
            activeId = validConversations[0].id;
          }

          return {
            version: 2,
            activeConversationId: activeId,
            conversations: validConversations.slice(0, MAX_CONVERSATIONS),
          };
        }
      }
    }

    // 2. Try migrating legacy v1 single-chat array
    const rawV1 = window.localStorage.getItem(LEGACY_STORAGE_KEY_V1);
    if (rawV1) {
      try {
        const legacyMessages = JSON.parse(rawV1);
        if (Array.isArray(legacyMessages) && legacyMessages.length > 0) {
          const validMsgs: StoredChatMessage[] = legacyMessages
            .filter(
              (m: any) =>
                m &&
                (m.role === "user" || m.role === "assistant") &&
                typeof m.content === "string" &&
                m.content.trim().length > 0
            )
            .map((m: any) => ({
              id: generateId("msg"),
              role: m.role,
              content: m.content,
              createdAt: Date.now(),
            }))
            .slice(-MAX_MESSAGES_PER_CONVERSATION);

          if (validMsgs.length > 0) {
            const firstUser = validMsgs.find((m) => m.role === "user");
            const title = generateConversationTitle(firstUser ? firstUser.content : "Migrated conversation");
            const migratedConv: StoredConversation = {
              id: generateId("conv"),
              title,
              createdAt: Date.now(),
              updatedAt: Date.now(),
              messages: validMsgs,
            };

            const store: CopilotHistoryStore = {
              version: 2,
              activeConversationId: migratedConv.id,
              conversations: [migratedConv],
            };

            // Save migrated v2 store and remove legacy key
            saveCopilotHistory(store);
            window.localStorage.removeItem(LEGACY_STORAGE_KEY_V1);
            return store;
          }
        }
      } catch {
        // Ignore legacy parse error
      }
    }
  } catch {
    // Ignore storage read error
  }

  // 3. Default fallback: brand new conversation
  const initial = createEmptyConversation();
  const freshStore: CopilotHistoryStore = {
    version: 2,
    activeConversationId: initial.id,
    conversations: [initial],
  };
  saveCopilotHistory(freshStore);
  return freshStore;
}

/**
 * Persists the conversation history store to localStorage.
 * Enforces MAX_CONVERSATIONS limit by pruning oldest inactive conversations.
 */
export function saveCopilotHistory(store: CopilotHistoryStore): void {
  if (typeof window === "undefined" || !window.localStorage) return;

  try {
    // Prune conversations if over limit, preserving active conversation
    let conversations = [...store.conversations];
    if (conversations.length > MAX_CONVERSATIONS) {
      // Sort oldest updated first among non-active conversations for pruning
      const activeId = store.activeConversationId;
      const sortedForPrune = [...conversations].sort((a, b) => a.updatedAt - b.updatedAt);
      const toRemoveCount = conversations.length - MAX_CONVERSATIONS;
      const removedIds = new Set<string>();

      for (const conv of sortedForPrune) {
        if (conv.id !== activeId && removedIds.size < toRemoveCount) {
          removedIds.add(conv.id);
        }
      }

      conversations = conversations.filter((c) => !removedIds.has(c.id));
    }

    const payload: CopilotHistoryStore = {
      version: 2,
      activeConversationId: store.activeConversationId,
      conversations,
    };

    window.localStorage.setItem(COPILOT_STORAGE_KEY_V2, JSON.stringify(payload));
  } catch {
    // Ignore storage quota errors
  }
}
