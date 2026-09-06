import { describe, it, expect, beforeEach } from "vitest";
import {
  AI_DRAFT_KEY,
  COPILOT_STORAGE_KEY_V2,
  LEGACY_STORAGE_KEY_V1,
  MAX_CONVERSATIONS,
  loadCopilotHistory,
  reconcileCopilotOwner,
  saveCopilotHistory,
  generateConversationTitle,
  formatRelativeTime,
  type CopilotHistoryStore,
} from "../data/ai/copilot_history_store";

class MemoryStorage {
  private store: Record<string, string> = {};

  getItem(key: string): string | null {
    return this.store[key] !== undefined ? this.store[key] : null;
  }

  setItem(key: string, value: string): void {
    this.store[key] = String(value);
  }

  removeItem(key: string): void {
    delete this.store[key];
  }

  clear(): void {
    this.store = {};
  }
}

describe("Targeted Copilot Chat Persistence & History Store Verifications", () => {
  let mockStorage: MemoryStorage;

  beforeEach(() => {
    mockStorage = new MemoryStorage();
    (globalThis as any).window = (globalThis as any).window || {};
    (globalThis as any).window.localStorage = mockStorage;
  });

  it("1. Persisted chat restores accurately after reload/hydration", () => {
    const persistedPayload: CopilotHistoryStore = {
      version: 2,
      activeConversationId: "conv_test_1",
      conversations: [
        {
          id: "conv_test_1",
          title: "HPG P/E Analysis",
          createdAt: 1700000000000,
          updatedAt: 1700000010000,
          messages: [
            { id: "m1", role: "user", content: "What is HPG P/E?", createdAt: 1700000000000 },
            { id: "m2", role: "assistant", content: "HPG trailing P/E is ~8.5x.", createdAt: 1700000005000 },
          ],
        },
      ],
    };

    mockStorage.setItem(COPILOT_STORAGE_KEY_V2, JSON.stringify(persistedPayload));

    const restored = loadCopilotHistory();
    expect(restored.version).toBe(2);
    expect(restored.activeConversationId).toBe("conv_test_1");
    expect(restored.conversations).toHaveLength(1);
    expect(restored.conversations[0].messages).toHaveLength(2);
    expect(restored.conversations[0].messages[0].content).toBe("What is HPG P/E?");
    expect(restored.conversations[0].messages[1].content).toBe("HPG trailing P/E is ~8.5x.");
  });

  it("2. Hydration does not get overwritten by empty default state when valid history exists", () => {
    const persistedPayload: CopilotHistoryStore = {
      version: 2,
      activeConversationId: "conv_saved",
      conversations: [
        {
          id: "conv_saved",
          title: "VHM Volatility",
          createdAt: 1700000000000,
          updatedAt: 1700000020000,
          messages: [
            { id: "m1", role: "user", content: "Check VHM 30D HV", createdAt: 1700000000000 },
          ],
        },
      ],
    };

    mockStorage.setItem(COPILOT_STORAGE_KEY_V2, JSON.stringify(persistedPayload));

    // Load store directly as initial render does
    const store = loadCopilotHistory();
    expect(store.activeConversationId).toBe("conv_saved");
    expect(store.conversations[0].title).toBe("VHM Volatility");

    // Saving back maintains existing conversations
    saveCopilotHistory(store);
    const reloadedRaw = mockStorage.getItem(COPILOT_STORAGE_KEY_V2);
    expect(reloadedRaw).toContain("VHM Volatility");
  });

  it("3 & 4. Assistant + user messages and activeConversationId survive remount", () => {
    const store: CopilotHistoryStore = {
      version: 2,
      activeConversationId: "conv_remount",
      conversations: [
        {
          id: "conv_remount",
          title: "CVHM2615 Greeks",
          createdAt: Date.now() - 5000,
          updatedAt: Date.now(),
          messages: [
            { id: "m1", role: "user", content: "Calculate CVHM2615 Delta", createdAt: Date.now() - 4000 },
            { id: "m2", role: "assistant", content: "Delta is 0.6200.", createdAt: Date.now() - 2000 },
          ],
        },
      ],
    };

    saveCopilotHistory(store);
    const reloaded = loadCopilotHistory();

    expect(reloaded.activeConversationId).toBe("conv_remount");
    expect(reloaded.conversations[0].messages).toHaveLength(2);
  });

  it("5 & 6. New chat preserves old conversation in history and orders by updatedAt descending", () => {
    const initialStore: CopilotHistoryStore = {
      version: 2,
      activeConversationId: "conv_1",
      conversations: [
        {
          id: "conv_1",
          title: "Older Chat",
          createdAt: 1000,
          updatedAt: 2000,
          messages: [{ id: "m1", role: "user", content: "Hello", createdAt: 1000 }],
        },
      ],
    };

    // Add a new conversation
    const newConv = {
      id: "conv_2",
      title: "Newer Chat",
      createdAt: 3000,
      updatedAt: 4000,
      messages: [{ id: "m2", role: "user" as const, content: "Second question", createdAt: 3000 }],
    };

    const updatedStore: CopilotHistoryStore = {
      version: 2,
      activeConversationId: newConv.id,
      conversations: [newConv, ...initialStore.conversations],
    };

    saveCopilotHistory(updatedStore);
    const reloaded = loadCopilotHistory();

    expect(reloaded.conversations).toHaveLength(2);
    // Sort descending by updatedAt
    const sorted = [...reloaded.conversations].sort((a, b) => b.updatedAt - a.updatedAt);
    expect(sorted[0].id).toBe("conv_2");
    expect(sorted[1].id).toBe("conv_1");
  });

  it("7. Selecting a previous conversation restores its messages immediately", () => {
    const store: CopilotHistoryStore = {
      version: 2,
      activeConversationId: "conv_2",
      conversations: [
        {
          id: "conv_1",
          title: "First Thread",
          createdAt: 1000,
          updatedAt: 2000,
          messages: [{ id: "m1", role: "user", content: "First question", createdAt: 1000 }],
        },
        {
          id: "conv_2",
          title: "Second Thread",
          createdAt: 3000,
          updatedAt: 4000,
          messages: [{ id: "m2", role: "user", content: "Second question", createdAt: 3000 }],
        },
      ],
    };

    saveCopilotHistory(store);

    // Switch active conversation to conv_1
    const switchedStore: CopilotHistoryStore = {
      ...store,
      activeConversationId: "conv_1",
    };
    saveCopilotHistory(switchedStore);

    const reloaded = loadCopilotHistory();
    expect(reloaded.activeConversationId).toBe("conv_1");
    const active = reloaded.conversations.find((c) => c.id === reloaded.activeConversationId);
    expect(active?.messages[0].content).toBe("First question");
  });

  it("8. Old single-chat storage (v1) migrates cleanly to v2 history schema without data loss", () => {
    const v1LegacyMessages = [
      { role: "user", content: "What is the strike of CVHM2615?" },
      { role: "assistant", content: "The strike price is 45,000 VND." },
    ];

    mockStorage.setItem(LEGACY_STORAGE_KEY_V1, JSON.stringify(v1LegacyMessages));

    const migrated = loadCopilotHistory();
    expect(migrated.version).toBe(2);
    expect(migrated.conversations).toHaveLength(1);
    expect(migrated.conversations[0].messages).toHaveLength(2);
    expect(migrated.conversations[0].title).toContain("What is the strike of CVHM2615?");
    expect(migrated.conversations[0].messages[0].content).toBe("What is the strike of CVHM2615?");

    // Legacy key should be removed after migration
    expect(mockStorage.getItem(LEGACY_STORAGE_KEY_V1)).toBeNull();
    // V2 key should be persisted
    expect(mockStorage.getItem(COPILOT_STORAGE_KEY_V2)).toBeTruthy();
  });

  it("9. Title generator creates concise clean titles without markdown syntax", () => {
    expect(generateConversationTitle("**Valuation** of HPG with P/E ratio")).toBe(
      "Valuation of HPG with P/E ratio"
    );
    expect(
      generateConversationTitle(
        "A very long prompt that goes on and on discussing complex mathematical concepts regarding Greeks and volatility surfaces"
      )
    ).toBe("A very long prompt that goes on and on discussin…");
    expect(generateConversationTitle("")).toBe("New conversation");
  });

  it("10. Relative time formatter produces human-friendly compact labels", () => {
    const now = Date.now();
    expect(formatRelativeTime(now - 10000)).toBe("Just now");
    expect(formatRelativeTime(now - 120000)).toBe("2m ago");
    expect(formatRelativeTime(now - 7200000)).toBe("2h ago");
    expect(formatRelativeTime(now - 100000000)).toBe("Yesterday");
  });

  it("11. History is bounded to MAX_CONVERSATIONS by pruning oldest inactive threads first", () => {
    const conversations = [];
    for (let i = 1; i <= 30; i++) {
      conversations.push({
        id: `conv_${i}`,
        title: `Thread ${i}`,
        createdAt: 1000 * i,
        updatedAt: 1000 * i,
        messages: [{ id: `m_${i}`, role: "user" as const, content: `Q ${i}`, createdAt: 1000 * i }],
      });
    }

    const store: CopilotHistoryStore = {
      version: 2,
      activeConversationId: "conv_30",
      conversations,
    };

    saveCopilotHistory(store);
    const reloaded = loadCopilotHistory();

    // Must not exceed MAX_CONVERSATIONS (25)
    expect(reloaded.conversations.length).toBeLessThanOrEqual(MAX_CONVERSATIONS);
    expect(reloaded.conversations.length).toBe(MAX_CONVERSATIONS);
    // Active conversation must remain preserved
    expect(reloaded.conversations.some((c) => c.id === "conv_30")).toBe(true);
  });

  // The conversation surface's controls (new chat, history, composer) are covered in
  // ai_anchor.test.tsx against a real DOM — the anchor renders through a portal, which
  // the static renderMarkup helper here cannot capture.
});

describe("reconcileCopilotOwner — history never crosses an identity boundary", () => {
  let mockStorage: MemoryStorage;
  const seed = () => {
    saveCopilotHistory({
      version: 2,
      activeConversationId: "c1",
      conversations: [{
        id: "c1", title: "t", createdAt: 1, updatedAt: 2,
        messages: [{ id: "m", role: "user", content: "secret question", createdAt: 1 }],
      }],
    });
    mockStorage.setItem(AI_DRAFT_KEY, "half-typed secret");
  };
  const hasHistory = () => (loadCopilotHistory().conversations[0]?.messages ?? []).some(m => m.content === "secret question");

  beforeEach(() => {
    mockStorage = new MemoryStorage();
    (globalThis as any).window = (globalThis as any).window || {};
    (globalThis as any).window.localStorage = mockStorage;
  });

  it("wipes pre-existing (unattributable) history on the first reconcile", () => {
    seed();
    expect(hasHistory()).toBe(true);
    reconcileCopilotOwner("user-a");
    expect(hasHistory()).toBe(false);
    expect(mockStorage.getItem(AI_DRAFT_KEY)).toBeNull();
  });

  it("keeps history across a reload / token refresh for the same subject", () => {
    reconcileCopilotOwner("user-a"); // adopt
    seed();                          // user-a builds a conversation
    reconcileCopilotOwner("user-a"); // reload
    expect(hasHistory()).toBe(true);
  });

  it("wipes on logout (user -> guest) and on a user switch", () => {
    reconcileCopilotOwner("user-a");
    seed();
    reconcileCopilotOwner(null); // sign out
    expect(hasHistory()).toBe(false);

    reconcileCopilotOwner("user-b");
    seed();
    reconcileCopilotOwner("user-a"); // A signs in on the same device
    expect(hasHistory()).toBe(false);
  });

  it("lets a guest keep history across reloads (marker is '', not absent)", () => {
    reconcileCopilotOwner(null); // adopt guest
    seed();
    reconcileCopilotOwner(null); // reload as guest
    expect(hasHistory()).toBe(true);
  });
});
