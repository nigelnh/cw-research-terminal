import { useResearchMarket } from "@/data/use_research_market";
import { useWatchlist } from "@/data/watchlist";

interface TopNavProps {
  activeTab: "dashboard" | "research";
  onTabChange: (tab: "dashboard" | "research") => void;
}

export function TopNav({ activeTab, onTabChange }: TopNavProps) {
  const { connectionState, upstreamFeedState, marketSession, marketSessionActive } = useResearchMarket();
  const { plan } = useWatchlist();

  const capacity = plan.capacity ?? 33;
  const ratio = Math.min(plan.symbolCount / (plan.capacity || 33), 1);

  const getStatusLabel = () => {
    if (connectionState === "DISCONNECTED" || connectionState === "ERROR") {
      return (
        <span className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
          <span className="h-1.5 w-1.5 rounded-full bg-destructive" aria-hidden />
          Backend offline
        </span>
      );
    }

    if (connectionState === "RECONNECTING") {
      return (
        <span className="flex items-center gap-1.5 text-[12px] text-flat">
          <span className="h-1.5 w-1.5 rounded-full bg-flat" aria-hidden />
          Reconnecting feed
        </span>
      );
    }

    if (connectionState === "CONNECTING") {
      return (
        <span className="flex items-center gap-1.5 text-[12px] text-flat">
          <span className="h-1.5 w-1.5 rounded-full bg-flat" aria-hidden />
          Connecting
        </span>
      );
    }

    // When gateway is connected:
    if (marketSession === "LUNCH_BREAK") {
      return (
        <span className="flex items-center gap-1.5 text-[12px] text-flat">
          <span className="h-1.5 w-1.5 rounded-full bg-flat" aria-hidden />
          Lunch break
        </span>
      );
    }

    if (
      marketSession === "CLOSED_PRE_OPEN" ||
      marketSession === "CLOSED_POST_MARKET" ||
      marketSession === "CLOSED_WEEKEND"
    ) {
      return (
        <span className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
          <span className="h-1.5 w-1.5 rounded-full bg-border-strong" aria-hidden />
          Market closed
        </span>
      );
    }

    if (upstreamFeedState === "CONNECTED" || marketSessionActive) {
      return (
        <span className="flex items-center gap-1.5 text-[12px] text-up">
          <span className="h-1.5 w-1.5 rounded-full bg-up" aria-hidden />
          Market open
        </span>
      );
    }

    if (upstreamFeedState === "UNKNOWN" || upstreamFeedState === "CONNECTING") {
      return (
        <span className="flex items-center gap-1.5 text-[12px] text-flat">
          <span className="h-1.5 w-1.5 rounded-full bg-flat" aria-hidden />
          Connecting feed
        </span>
      );
    }

    return (
      <span className="flex items-center gap-1.5 text-[12px] text-destructive">
        <span className="h-1.5 w-1.5 rounded-full bg-destructive" aria-hidden />
        Feed unavailable
      </span>
    );
  };

  return (
    <header
      style={{
        position: "sticky",
        top: 0,
        zIndex: 30,
        borderBottom: "1px solid var(--border)",
        backgroundColor: "rgba(15, 18, 24, 0.85)",
        backdropFilter: "blur(8px)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "32px",
          padding: "0 28px",
        }}
      >
        {/* Brand Mark */}
        <button
          onClick={() => onTabChange("dashboard")}
          className="focus-ring"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "10px",
            padding: "18px 0",
            background: "transparent",
            border: "none",
            cursor: "pointer",
            textAlign: "left",
          }}
        >
          <span
            className="tnum"
            style={{
              display: "flex",
              height: "20px",
              width: "20px",
              alignItems: "center",
              justifyContent: "center",
              borderRadius: "3px",
              border: "1px solid var(--border-strong)",
              fontSize: "9px",
              fontWeight: 500,
              color: "var(--primary)",
            }}
          >
            CW
          </span>
          <span
            style={{
              fontSize: "13px",
              fontWeight: 500,
              letterSpacing: "-0.01em",
              color: "var(--foreground)",
            }}
          >
          </span>
        </button>

        {/* Minimal Navigation Tabs */}
        <nav style={{ display: "flex", alignItems: "center", gap: "24px" }}>
          <button
            onClick={() => onTabChange("dashboard")}
            className="focus-ring"
            style={{
              position: "relative",
              padding: "18px 0",
              fontSize: "13px",
              fontWeight: 400,
              background: "transparent",
              border: "none",
              cursor: "pointer",
              color: activeTab === "dashboard" ? "var(--primary)" : "var(--muted-foreground)",
              transition: "color 0.15s ease",
            }}
          >
            Dashboard
            {activeTab === "dashboard" && (
              <span
                style={{
                  position: "absolute",
                  left: 0,
                  right: 0,
                  bottom: "-1px",
                  height: "1px",
                  backgroundColor: "var(--primary)",
                }}
                aria-hidden
              />
            )}
          </button>

          <button
            onClick={() => onTabChange("research")}
            className="focus-ring"
            style={{
              position: "relative",
              padding: "18px 0",
              fontSize: "13px",
              fontWeight: 400,
              background: "transparent",
              border: "none",
              cursor: "pointer",
              color: activeTab === "research" ? "var(--primary)" : "var(--muted-foreground)",
              transition: "color 0.15s ease",
            }}
          >
            Research
            {activeTab === "research" && (
              <span
                style={{
                  position: "absolute",
                  left: 0,
                  right: 0,
                  bottom: "-1px",
                  height: "1px",
                  backgroundColor: "var(--primary)",
                }}
                aria-hidden
              />
            )}
          </button>
        </nav>

        {/* Right Side: Capacity Indicator & Truthful Status */}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "24px" }}>
          <div
            title="Realtime subscription capacity (includes deduplicated underlyings)"
            style={{ display: "flex", alignItems: "center", gap: "8px" }}
          >
            <span className="tnum" style={{ fontSize: "12px", color: "var(--muted-foreground)" }}>
              <span style={{ color: "var(--foreground)" }}>{plan.symbolCount}</span> / {capacity} slots
            </span>
            <span
              style={{
                display: "block",
                height: "1px",
                width: "40px",
                backgroundColor: "var(--border-strong)",
              }}
              aria-hidden
            >
              <span
                style={{
                  display: "block",
                  height: "1px",
                  backgroundColor: "var(--primary)",
                  width: `${ratio * 100}%`,
                  transition: "width 0.2s ease",
                }}
              />
            </span>
          </div>

          {getStatusLabel()}
        </div>
      </div>
    </header>
  );
}
