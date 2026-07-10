/**
 * Topbar component with clock and branding
 */

import { useEffect, useState, useRef } from "react";
import { colors } from "@/design/tokens";

function formatDate(d: Date): string {
  const months = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  const day = String(d.getDate()).padStart(2, "0");
  const month = months[d.getMonth()];
  const year = d.getFullYear();
  return `${day} ${month} ${year}`;
}

function formatTime(d: Date): string {
  const h = String(d.getHours()).padStart(2, "0");
  const m = String(d.getMinutes()).padStart(2, "0");
  const s = String(d.getSeconds()).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

interface TopbarProps {
  currentView: "equity" | "info";
  onViewChange: (view: "equity" | "info") => void;
  serverTimeOffset?: number;
  userEmail?: string;
  onLogout?: () => void;
  accessToken?: string | null;
}

export function Topbar({
  currentView,
  onViewChange,
  serverTimeOffset = 0,
  userEmail,
  onLogout,
  accessToken,
}: TopbarProps) {
  const [now, setNow] = useState(Date.now());

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<"info" | "password">("info");
  const [notificationCount, setNotificationCount] = useState<number>(() => {
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem("notificationCount");
      return stored ? parseInt(stored, 10) : 0;
    }
    return 0;
  });
  const [notificationsList, setNotificationsList] = useState<string[]>(() => {
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem("notificationsList");
      try {
        return stored ? JSON.parse(stored) : [];
      } catch {
        return [];
      }
    }
    return [];
  });

  useEffect(() => {
    localStorage.setItem("notificationCount", String(notificationCount));
  }, [notificationCount]);

  useEffect(() => {
    localStorage.setItem("notificationsList", JSON.stringify(notificationsList));
  }, [notificationsList]);

  const [isNotificationOpen, setIsNotificationOpen] = useState(false);
  const notificationTimeoutRef = useRef<any>(null);

  const handleNotificationMouseEnter = () => {
    if (notificationTimeoutRef.current) clearTimeout(notificationTimeoutRef.current);
    setIsNotificationOpen(true);
  };

  const handleNotificationMouseLeave = () => {
    notificationTimeoutRef.current = setTimeout(() => {
      setIsNotificationOpen(false);
    }, 150);
  };

  useEffect(() => {
    return () => {
      if (notificationTimeoutRef.current) clearTimeout(notificationTimeoutRef.current);
    };
  }, []);

  // Form states
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [modalError, setModalError] = useState("");
  const [modalSuccess, setModalSuccess] = useState("");

  // Input-specific error notification states
  const [oldPasswordError, setOldPasswordError] = useState("");
  const [newPasswordError, setNewPasswordError] = useState("");
  const [confirmPasswordError, setConfirmPasswordError] = useState("");

  const clearFormErrors = () => {
    setOldPasswordError("");
    setNewPasswordError("");
    setConfirmPasswordError("");
    setModalError("");
    setModalSuccess("");
  };

  const handleSavePassword = () => {
    // Reset errors
    clearFormErrors();

    if (!oldPassword) {
      setOldPasswordError("Old password is required.");
      return;
    }
    if (!newPassword) {
      setNewPasswordError("New password is required.");
      return;
    }
    if (!confirmPassword) {
      setConfirmPasswordError("Please confirm your new password.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setConfirmPasswordError("New passwords do not match.");
      return;
    }
    if (oldPassword === newPassword) {
      setNewPasswordError("New password cannot be the same as the old password.");
      return;
    }

    fetch("/api/auth/change-password", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${accessToken || ""}`
      },
      body: JSON.stringify({ oldPassword, newPassword, confirmPassword })
    })
      .then(async (res) => {
        const data = await res.json();
        if (res.ok) {
          setOldPassword("");
          setNewPassword("");
          setConfirmPassword("");
          setModalSuccess("Password changed successfully!");

          const timeString = new Date().toLocaleTimeString();
          setNotificationsList(prev => [
            `Password updated successfully at ${timeString}`,
            ...prev
          ]);
          setNotificationCount(c => c + 1);
        } else {
          const errMsg = data.message || "Failed to update password.";
          if (errMsg.toLowerCase().includes("old password")) {
            setOldPasswordError(errMsg);
          } else if (errMsg.toLowerCase().includes("match")) {
            setConfirmPasswordError(errMsg);
          } else {
            setNewPasswordError(errMsg);
          }
        }
      })
      .catch(() => {
        setNewPasswordError("Failed to connect to the server.");
      });
  };

  useEffect(() => {
    const interval = setInterval(() => {
      setNow(Date.now());
    }, 500);
    return () => clearInterval(interval);
  }, []);

  const adjustedNow = new Date(now + serverTimeOffset);

  const navButtonStyle = (isActive: boolean) => ({
    padding: "6px 16px",
    borderRadius: "6px",
    fontSize: "14px",
    fontWeight: 500,
    cursor: "pointer",
    transition: "all 0.2s",
    backgroundColor: isActive ? "rgba(243, 186, 47, 0.15)" : "transparent",
    color: isActive ? "#F3BA2F" : colors.textSecondary,
    border: `1px solid ${isActive ? "#F3BA2F" : "transparent"}`,
  });

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        height: 48,
        padding: "0 24px",
        backgroundColor: colors.background,
        borderBottom: `1px solid ${colors.border}`,
      }}
    >
      {/* Left - Spacer */}
      <div style={{ flex: 1 }} />

      {/* Center - Navigation */}
      <div
        style={{
          flex: 1,
          display: "flex",
          justifyContent: "center",
          gap: 8,
        }}
      >
        <div
          style={navButtonStyle(currentView === "equity")}
          onClick={() => onViewChange("equity")}
        >
          Equity
        </div>
        <div
          style={navButtonStyle(currentView === "info")}
          onClick={() => onViewChange("info")}
        >
          Info
        </div>
      </div>

      {/* Right - Date, Time, Notifications */}
      <div
        style={{
          flex: 1,
          display: "flex",
          alignItems: "center",
          justifyContent: "flex-end",
          gap: 16,
          position: "relative",
        }}
      >
        <span style={{ color: colors.textSecondary, fontSize: 14 }}>
          {formatDate(adjustedNow)}
        </span>
        <span
          style={{
            color: colors.textSecondary,
            fontSize: 14,
            fontWeight: 500,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {formatTime(adjustedNow)}
        </span>
        <div
          onMouseEnter={handleNotificationMouseEnter}
          onMouseLeave={handleNotificationMouseLeave}
          style={{ position: "relative" }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 32,
              height: 32,
              borderRadius: 8,
              backgroundColor: "rgba(255, 255, 255, 0.05)",
              cursor: "pointer",
            }}
            title="Notifications"
          >
            <span
              className="material-symbols-outlined"
              style={{ fontSize: 19, color: colors.textSecondary }}
            >
              notifications
            </span>
            {notificationCount > 0 && (
              <div
                style={{
                  position: "absolute",
                  top: -4,
                  right: -4,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  minWidth: 16,
                  height: 16,
                  padding: "0 4px",
                  borderRadius: 8,
                  backgroundColor: colors.decrease,
                  color: "#FFFFFF",
                  fontSize: 10,
                  fontWeight: 700,
                  boxShadow: "0 0 4px rgba(0,0,0,0.5)",
                }}
              >
                {notificationCount}
              </div>
            )}
          </div>

          {isNotificationOpen && (
            <div
              style={{
                position: "absolute",
                top: 36,
                right: 0,
                width: 260,
                backgroundColor: "#1E1E1E",
                border: `1px solid ${colors.border}`,
                borderRadius: 8,
                boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
                zIndex: 1000,
                padding: 12,
                display: "flex",
                flexDirection: "column",
                gap: 8,
              }}
            >
              <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", paddingBottom: notificationsList.length > 0 ? 6 : 0 }}>
                {notificationsList.length > 0 && (
                  <span
                    style={{ color: colors.textPrimary, fontSize: 11, cursor: "pointer" }}
                    onClick={() => {
                      setNotificationsList([]);
                      setNotificationCount(0);
                    }}
                  >
                    Clear all
                  </span>
                )}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 150, overflowY: "auto" }}>
                {notificationsList.length === 0 ? (
                  <div style={{ color: colors.textMuted, fontSize: 12, padding: "8px 0", textAlign: "center" }}>
                    No new notifications
                  </div>
                ) : (
                  notificationsList.map((notif, idx) => (
                    <div
                      key={idx}
                      style={{
                        padding: 6,
                        borderRadius: 4,
                        backgroundColor: "rgba(255, 255, 255, 0.03)",
                        color: colors.textSecondary,
                        fontSize: 12,
                      }}
                    >
                      {notif}
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>

        {userEmail && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              height: 32,
              padding: "0 12px",
              borderRadius: 8,
              backgroundColor: "rgba(255, 255, 255, 0.05)",
              border: `1px solid rgba(255, 255, 255, 0.08)`,
              cursor: "pointer",
              transition: "background-color 0.2s",
            }}
            onClick={() => setIsSettingsOpen(true)}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.08)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.05)";
            }}
          >
            <span
              className="material-symbols-outlined"
              style={{ fontSize: 16, color: colors.textPrimary }}
            >
              account_circle
            </span>
            <span style={{ color: colors.textSecondary, fontSize: 12, fontWeight: 500 }}>
              {userEmail}
            </span>
          </div>
        )}

        {onLogout && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 32,
              height: 32,
              borderRadius: 8,
              backgroundColor: "rgba(246, 70, 93, 0.1)",
              cursor: "pointer",
              transition: "background-color 0.2s",
            }}
            title="Logout"
            onClick={onLogout}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = "rgba(246, 70, 93, 0.2)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = "rgba(246, 70, 93, 0.1)";
            }}
          >
            <span
              className="material-symbols-outlined"
              style={{ fontSize: 19, color: colors.decrease }}
            >
              logout
            </span>
          </div>
        )}

        {/* Settings Modal */}
        {isSettingsOpen && (
          <div
            style={{
              position: "fixed",
              top: 0,
              left: 0,
              width: "100vw",
              height: "100vh",
              backgroundColor: "rgba(0, 0, 0, 0.6)",
              backdropFilter: "blur(4px)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              zIndex: 9999,
            }}
            onClick={() => {
              setIsSettingsOpen(false);
              setOldPassword("");
              setNewPassword("");
              setConfirmPassword("");
              clearFormErrors();
            }}
          >
            <div
              style={{
                width: 580,
                height: 380,
                backgroundColor: "#1E1E1E",
                border: `1px solid ${colors.border}`,
                borderRadius: 12,
                boxShadow: "0 12px 40px rgba(0, 0, 0, 0.5)",
                display: "flex",
                flexDirection: "column",
                overflow: "hidden",
              }}
              onClick={(e) => e.stopPropagation()}
            >
              {/* Modal Header */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "16px 20px",
                  borderBottom: `1px solid ${colors.border}`,
                }}
              >
                <h3 style={{ color: colors.textPrimary, fontSize: 16, fontWeight: 600, margin: 0 }}>
                  Account Settings
                </h3>
                <span
                  className="material-symbols-outlined"
                  style={{ color: colors.textMuted, cursor: "pointer", fontSize: 20 }}
                  onClick={() => {
                    setIsSettingsOpen(false);
                    setOldPassword("");
                    setNewPassword("");
                    setConfirmPassword("");
                    clearFormErrors();
                  }}
                >
                  close
                </span>
              </div>

              {/* Modal Content - 2 columns */}
              <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
                {/* Left Column - Tabs */}
                <div
                  style={{
                    width: 170,
                    backgroundColor: "rgba(0, 0, 0, 0.2)",
                    borderRight: `1px solid ${colors.border}`,
                    padding: "16px 8px",
                    display: "flex",
                    flexDirection: "column",
                    gap: 6,
                  }}
                >
                  <div
                    style={{
                      padding: "10px 14px",
                      borderRadius: 6,
                      fontSize: 13,
                      fontWeight: 500,
                      cursor: "pointer",
                      transition: "all 0.2s",
                      backgroundColor: activeTab === "info" ? "rgba(243, 186, 47, 0.1)" : "transparent",
                      color: activeTab === "info" ? colors.textPrimary : colors.textMuted,
                    }}
                    onClick={() => {
                      setActiveTab("info");
                      clearFormErrors();
                    }}
                  >
                    Info
                  </div>
                  <div
                    style={{
                      padding: "10px 14px",
                      borderRadius: 6,
                      fontSize: 13,
                      fontWeight: 500,
                      cursor: "pointer",
                      transition: "all 0.2s",
                      backgroundColor: activeTab === "password" ? "rgba(243, 186, 47, 0.1)" : "transparent",
                      color: activeTab === "password" ? colors.textPrimary : colors.textMuted,
                    }}
                    onClick={() => {
                      setActiveTab("password");
                      clearFormErrors();
                    }}
                  >
                    Change Password
                  </div>
                </div>

                {/* Right Column - Details */}
                <div style={{ flex: 1, padding: "20px 24px", overflowY: "auto", display: "flex", flexDirection: "column" }}>
                  {activeTab === "info" ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                      <h4 style={{ color: colors.textSecondary, fontSize: 14, fontWeight: 600, margin: "0 0 8px 0" }}>
                        User Information
                      </h4>

                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingBottom: 8 }}>
                        <span style={{ color: colors.textMuted, fontSize: 12, fontWeight: 500 }}>
                          Username
                        </span>
                        <span style={{ color: colors.textSecondary, fontSize: 13, fontWeight: 500 }}>
                          {userEmail}
                        </span>
                      </div>

                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingBottom: 8 }}>
                        <span style={{ color: colors.textMuted, fontSize: 12, fontWeight: 500 }}>
                          Role
                        </span>
                        <span style={{ color: colors.textSecondary, fontSize: 13, fontWeight: 500 }}>
                          Trader
                        </span>
                      </div>

                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingBottom: 8 }}>
                        <span style={{ color: colors.textMuted, fontSize: 12, fontWeight: 500 }}>
                          Environment
                        </span>
                        <span style={{ color: colors.increase, fontSize: 13, fontWeight: 600 }}>
                          DEVELOPMENT STAGE
                        </span>
                      </div>
                    </div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                      {modalError && (
                        <div style={{ color: colors.decrease, fontSize: 12, fontWeight: 500 }}>
                          {modalError}
                        </div>
                      )}


                      {/* Inputs */}
                      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <label style={{ color: colors.textMuted, fontSize: 11 }}>
                          Old Password
                        </label>
                        <input
                          type="password"
                          placeholder="••••••••"
                          value={oldPassword}
                          onChange={(e) => setOldPassword(e.target.value)}
                          style={{
                            padding: "8px 12px",
                            borderRadius: 6,
                            backgroundColor: "rgba(255, 255, 255, 0.04)",
                            border: `1px solid ${oldPasswordError ? colors.decrease : colors.border}`,
                            color: colors.textSecondary,
                            fontSize: 13,
                            outline: "none",
                          }}
                        />
                        {oldPasswordError && (
                          <span style={{ color: colors.decrease, fontSize: 11, marginTop: 2 }}>
                            {oldPasswordError}
                          </span>
                        )}
                      </div>

                      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <label style={{ color: colors.textMuted, fontSize: 11 }}>
                          New Password
                        </label>
                        <input
                          type="password"
                          placeholder="••••••••"
                          value={newPassword}
                          onChange={(e) => setNewPassword(e.target.value)}
                          style={{
                            padding: "8px 12px",
                            borderRadius: 6,
                            backgroundColor: "rgba(255, 255, 255, 0.04)",
                            border: `1px solid ${newPasswordError ? colors.decrease : colors.border}`,
                            color: colors.textSecondary,
                            fontSize: 13,
                            outline: "none",
                          }}
                        />
                        {newPasswordError && (
                          <span style={{ color: colors.decrease, fontSize: 11, marginTop: 2 }}>
                            {newPasswordError}
                          </span>
                        )}
                      </div>

                      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <label style={{ color: colors.textMuted, fontSize: 11 }}>
                          Confirm Password
                        </label>
                        <input
                          type="password"
                          placeholder="••••••••"
                          value={confirmPassword}
                          onChange={(e) => setConfirmPassword(e.target.value)}
                          style={{
                            padding: "8px 12px",
                            borderRadius: 6,
                            backgroundColor: "rgba(255, 255, 255, 0.04)",
                            border: `1px solid ${confirmPasswordError ? colors.decrease : colors.border}`,
                            color: colors.textSecondary,
                            fontSize: 13,
                            outline: "none",
                          }}
                        />
                        {confirmPasswordError && (
                          <span style={{ color: colors.decrease, fontSize: 11, marginTop: 2 }}>
                            {confirmPasswordError}
                          </span>
                        )}
                      </div>

                      {/* Save Button & Success Message */}
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12 }}>
                        <div style={{ flex: 1, marginRight: 12 }}>
                          {modalSuccess && (
                            <span style={{ color: colors.increase, fontSize: 12, fontWeight: 500 }}>
                              {modalSuccess}
                            </span>
                          )}
                        </div>
                        <button
                          onClick={handleSavePassword}
                          style={{
                            padding: "8px 20px",
                            borderRadius: 6,
                            backgroundColor: colors.textPrimary,
                            color: colors.background,
                            fontSize: 13,
                            fontWeight: 600,
                            border: "none",
                            cursor: "pointer",
                          }}
                        >
                          Save
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

