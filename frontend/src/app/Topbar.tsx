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

function formatNotificationDate(d: Date): string {
  const day = String(d.getDate()).padStart(2, "0");
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const year = d.getFullYear();
  const h = String(d.getHours()).padStart(2, "0");
  const m = String(d.getMinutes()).padStart(2, "0");
  const s = String(d.getSeconds()).padStart(2, "0");
  return `${day}/${month}/${year} ${h}:${m}:${s}`;
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
  const [activeTab, setActiveTab] = useState<"info" | "manage" | "password">("info");
  const [envStage, setEnvStage] = useState<string>("UAT STAGE");

  // Fetch environment stage on modal open
  useEffect(() => {
    if (isSettingsOpen) {
      fetch("/api/environment")
        .then((res) => {
          if (res.ok) return res.json();
          throw new Error("Failed to fetch environment");
        })
        .then((data) => {
          if (data && data.environment) {
            setEnvStage(data.environment === "PROD" ? "PROD STAGE" : "UAT STAGE");
          }
        })
        .catch((err) => {
          console.error("[Topbar] Error fetching environment:", err);
          setEnvStage("UAT STAGE");
        });
    }
  }, [isSettingsOpen]);
  const [notificationCount, setNotificationCount] = useState<number>(0);
  const [notificationsList, setNotificationsList] = useState<string[]>([]);

  // User management states
  const [allUsersList, setAllUsersList] = useState<any[]>([]);
  const [allUsersLoading, setAllUsersLoading] = useState<boolean>(false);
  const [selectedUserForPassword, setSelectedUserForPassword] = useState<any | null>(null);
  const [adminNewPassword, setAdminNewPassword] = useState<string>("");

  // Synchronize notifications per-user
  useEffect(() => {
    if (userEmail) {
      const countKey = `${userEmail}:notificationCount`;
      const listKey = `${userEmail}:notificationsList`;

      const storedCount = localStorage.getItem(countKey);
      setNotificationCount(storedCount ? parseInt(storedCount, 10) : 0);

      const storedList = localStorage.getItem(listKey);
      try {
        setNotificationsList(storedList ? JSON.parse(storedList) : []);
      } catch {
        setNotificationsList([]);
      }
    } else {
      setNotificationCount(0);
      setNotificationsList([]);
    }
  }, [userEmail]);

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

  // Admin approval states
  const [selectedPendingUser, setSelectedPendingUser] = useState<any>(null);

  // Parse user info from JWT token
  let userRole = "user";
  let tokenEmail = "";
  if (accessToken) {
    try {
      const payload = JSON.parse(atob(accessToken.split(".")[1]));
      userRole = payload.role || "user";
      tokenEmail = payload.email || "";
    } catch (e) {
      // ignore
    }
  }

  // Polling for pending users if admin
  useEffect(() => {
    if (userRole !== "admin" || !accessToken) return;

    const pollPendingUsers = async () => {
      try {
        const response = await fetch("/api/admin/pending-users", {
          headers: {
            Authorization: `Bearer ${accessToken}`,
          },
        });
        if (response.ok) {
          const users = await response.json();
          const notifiedKey = `${userEmail}:notifiedPendingIds`;
          const storedNotified = localStorage.getItem(notifiedKey);
          const notifiedIds: string[] = storedNotified ? JSON.parse(storedNotified) : [];

          const newUsers = users.filter((u: any) => !notifiedIds.includes(u.id));
          if (newUsers.length > 0) {
            const updatedIds = [...notifiedIds, ...newUsers.map((u: any) => u.id)];
            localStorage.setItem(notifiedKey, JSON.stringify(updatedIds));

            setNotificationsList((prev) => {
              const addedNotifs = newUsers.map((u: any) =>
                JSON.stringify({
                  id: `pending-${u.id}`,
                  type: "pending_approval",
                  message: `New sign-up request`,
                  email: u.email,
                  timestamp: formatNotificationDate(new Date(u.created_at || Date.now())),
                  data: u,
                })
              );
              const updated = [...addedNotifs, ...prev];
              if (userEmail) {
                localStorage.setItem(`${userEmail}:notificationsList`, JSON.stringify(updated));
              }
              return updated;
            });
            setNotificationCount((prev) => {
              const updated = prev + newUsers.length;
              if (userEmail) {
                localStorage.setItem(`${userEmail}:notificationCount`, String(updated));
              }
              return updated;
            });
          }
        }
      } catch (err) {
        console.error("Failed to poll pending users:", err);
      }
    };

    pollPendingUsers();
    const interval = setInterval(pollPendingUsers, 5000);
    return () => clearInterval(interval);
  }, [userRole, accessToken, userEmail]);

  const handleApproveUser = async (userId: string) => {
    if (!accessToken) return;
    try {
      const response = await fetch("/api/admin/approve", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ userId }),
      });
      if (response.ok) {
        setNotificationsList((prev) => {
          const updated = prev.filter((n) => {
            try {
              const p = JSON.parse(n);
              return p.data?.id !== userId;
            } catch {
              return true;
            }
          });
          if (userEmail) {
            localStorage.setItem(`${userEmail}:notificationsList`, JSON.stringify(updated));
          }
          return updated;
        });

        setNotificationCount((prev) => {
          const nextCount = Math.max(0, prev - 1);
          if (userEmail) {
            localStorage.setItem(`${userEmail}:notificationCount`, String(nextCount));
          }
          return nextCount;
        });

        if (userEmail) {
          const notifiedKey = `${userEmail}:notifiedPendingIds`;
          const storedNotified = localStorage.getItem(notifiedKey);
          const notifiedIds: string[] = storedNotified ? JSON.parse(storedNotified) : [];
          if (!notifiedIds.includes(userId)) {
            notifiedIds.push(userId);
            localStorage.setItem(notifiedKey, JSON.stringify(notifiedIds));
          }
        }

        setSelectedPendingUser(null);
        alert("User approved successfully!");
      } else {
        const data = await response.json();
        alert(data.message || "Failed to approve user.");
      }
    } catch (err) {
      alert("A connection error occurred.");
    }
  };

  const handleRejectUser = async (userId: string) => {
    if (!accessToken) return;
    try {
      const response = await fetch("/api/admin/reject", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ userId }),
      });
      if (response.ok) {
        setNotificationsList((prev) => {
          const updated = prev.filter((n) => {
            try {
              const p = JSON.parse(n);
              return p.data?.id !== userId;
            } catch {
              return true;
            }
          });
          if (userEmail) {
            localStorage.setItem(`${userEmail}:notificationsList`, JSON.stringify(updated));
          }
          return updated;
        });

        setNotificationCount((prev) => {
          const nextCount = Math.max(0, prev - 1);
          if (userEmail) {
            localStorage.setItem(`${userEmail}:notificationCount`, String(nextCount));
          }
          return nextCount;
        });

        if (userEmail) {
          const notifiedKey = `${userEmail}:notifiedPendingIds`;
          const storedNotified = localStorage.getItem(notifiedKey);
          const notifiedIds: string[] = storedNotified ? JSON.parse(storedNotified) : [];
          if (!notifiedIds.includes(userId)) {
            notifiedIds.push(userId);
            localStorage.setItem(notifiedKey, JSON.stringify(notifiedIds));
          }
        }

        setSelectedPendingUser(null);
        alert("User rejected.");
      } else {
        const data = await response.json();
        alert(data.message || "Failed to reject user.");
      }
    } catch (err) {
      alert("A connection error occurred.");
    }
  };

  const fetchAllUsers = async () => {
    if (!accessToken || userRole !== "admin") return;
    setAllUsersLoading(true);
    try {
      const response = await fetch("/api/admin/users", {
        headers: {
          Authorization: `Bearer ${accessToken}`,
        },
      });
      if (response.ok) {
        const data = await response.json();
        setAllUsersList(data);
      }
    } catch (err) {
      console.error("Failed to fetch all users:", err);
    } finally {
      setAllUsersLoading(false);
    }
  };

  useEffect(() => {
    if (isSettingsOpen && activeTab === "manage") {
      fetchAllUsers();
    }
  }, [isSettingsOpen, activeTab]);

  const handleRemoveUser = async (userId: string) => {
    if (!window.confirm("Are you sure you want to remove this user? This action cannot be undone.")) return;
    try {
      const response = await fetch("/api/admin/delete-user", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ userId }),
      });
      if (response.ok) {
        alert("User removed successfully.");
        fetchAllUsers();
      } else {
        const data = await response.json();
        alert(data.message || "Failed to remove user.");
      }
    } catch (err) {
      alert("A connection error occurred.");
    }
  };

  const handleAdminModifyPassword = async () => {
    if (!selectedUserForPassword) return;
    if (!adminNewPassword) {
      alert("Please enter a new password.");
      return;
    }
    const passwordRegex = /^(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$/;
    if (!passwordRegex.test(adminNewPassword)) {
      alert("Password must be at least 8 characters long and contain at least one uppercase letter, one number, and one special character.");
      return;
    }
    try {
      const response = await fetch("/api/admin/modify-password", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({
          userId: selectedUserForPassword.id,
          newPassword: adminNewPassword,
        }),
      });
      if (response.ok) {
        alert("Password updated successfully.");
        setSelectedUserForPassword(null);
        setAdminNewPassword("");
        fetchAllUsers();
      } else {
        const data = await response.json();
        alert(data.message || "Failed to update password.");
      }
    } catch (err) {
      alert("A connection error occurred.");
    }
  };

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

    const isAdmin = userRole === "admin";

    if (!isAdmin && !oldPassword) {
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
    if (!isAdmin && oldPassword === newPassword) {
      setNewPasswordError("New password cannot be the same as the old password.");
      return;
    }

    const passwordRegex = /^(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$/;
    const isDevExempt = (userEmail && (userEmail.toLowerCase().includes("test") || userEmail.toLowerCase().includes("dev") || userEmail.toLowerCase() === "dev@example.invalid"));
    if (!isDevExempt && !passwordRegex.test(newPassword)) {
      setNewPasswordError("Password must be at least 8 characters long and contain at least one uppercase letter, one number, and one special character.");
      return;
    }

    const endpoint = isAdmin ? "/api/admin/change-password" : "/api/auth/change-password";
    const payload = isAdmin ? { newPassword, confirmPassword } : { oldPassword, newPassword, confirmPassword };

    fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${accessToken || ""}`
      },
      body: JSON.stringify(payload)
    })
      .then(async (res) => {
        const data = await res.json();
        if (res.ok) {
          setOldPassword("");
          setNewPassword("");
          setConfirmPassword("");
          setModalSuccess("Password changed successfully!");

          const now = new Date();
          const dateTimeString = formatNotificationDate(now);
          setNotificationsList(prev => {
            const updated = [
              JSON.stringify({
                id: `pwd-change-${Date.now()}`,
                type: "password_change",
                message: "Password changed successfully",
                email: userEmail,
                timestamp: dateTimeString
              }),
              ...prev
            ];
            if (userEmail) {
              localStorage.setItem(`${userEmail}:notificationsList`, JSON.stringify(updated));
            }
            return updated;
          });
          setNotificationCount(c => {
            const updated = c + 1;
            if (userEmail) {
              localStorage.setItem(`${userEmail}:notificationCount`, String(updated));
            }
            return updated;
          });
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
                width: 300,
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
                      setNotificationCount(0);
                      if (userEmail) {
                        localStorage.setItem(`${userEmail}:notificationCount`, "0");
                      }
                    }}
                  >
                    Read all
                  </span>
                )}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 280, overflowY: "auto" }}>
                {notificationsList.length === 0 ? (
                  <div style={{ color: colors.textMuted, fontSize: 12, padding: "8px 0", textAlign: "center" }}>
                    No new notifications
                  </div>
                ) : (
                  notificationsList.map((notif, idx) => {
                    let parsed: any = null;
                    if (notif.startsWith('{')) {
                      try {
                        parsed = JSON.parse(notif);
                      } catch (e) { }
                    }
                    const isPending = parsed && parsed.type === 'pending_approval';
                    const isPasswordChange = parsed && parsed.type === 'password_change';

                    let title = "Notification";
                    let details = notif;
                    let time = "";
                    let isClickable = false;

                    if (isPending) {
                      title = "Sign-Up Request";
                      details = `User registered: ${parsed.email || parsed.data?.email}`;
                      time = parsed.timestamp || (parsed.data?.created_at ? formatNotificationDate(new Date(parsed.data.created_at)) : "");
                      isClickable = true;
                    } else if (isPasswordChange) {
                      title = "Password Changed";
                      details = parsed.email ? `Credentials updated for ${parsed.email}` : parsed.message;
                      time = parsed.timestamp || "";
                      isClickable = false;
                    } else if (parsed) {
                      title = parsed.title || "Alert";
                      details = parsed.message || "";
                      time = parsed.timestamp || "";
                    }

                    return (
                      <div
                        key={idx}
                        onClick={() => {
                          if (isClickable && isPending) {
                            setSelectedPendingUser(parsed.data);
                          }
                        }}
                        style={{
                          padding: "10px 12px",
                          borderRadius: 8,
                          backgroundColor: "rgba(255, 255, 255, 0.03)",
                          color: colors.textSecondary,
                          fontSize: 12,
                          lineHeight: "1.4",
                          boxSizing: "border-box",
                          cursor: isClickable ? "pointer" : "default",
                          transition: "background-color 0.2s, border-color 0.2s",
                          border: "1px solid rgba(255, 255, 255, 0.04)",
                          display: "flex",
                          gap: 10,
                          alignItems: "flex-start",
                        }}
                        onMouseEnter={(e) => {
                          if (isClickable) {
                            e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.08)";
                            e.currentTarget.style.borderColor = "rgba(255, 255, 255, 0.1)";
                          }
                        }}
                        onMouseLeave={(e) => {
                          if (isClickable) {
                            e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.03)";
                            e.currentTarget.style.borderColor = "rgba(255, 255, 255, 0.04)";
                          }
                        }}
                      >

                        {/* Text Content */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 2, flexGrow: 1, minWidth: 0 }}>
                          <span style={{ fontWeight: 600, color: colors.textPrimary, fontSize: 12 }}>
                            {title}
                          </span>
                          <span style={{ color: colors.textMuted, fontSize: 11, wordBreak: "break-all" }}>
                            {details}
                          </span>
                          {time && (
                            <span style={{ color: "rgba(255, 255, 255, 0.3)", fontSize: 9, marginTop: 2 }}>
                              {time}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })
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
                  {userRole === "admin" && (
                    <div
                      style={{
                        padding: "10px 14px",
                        borderRadius: 6,
                        fontSize: 13,
                        fontWeight: 500,
                        cursor: "pointer",
                        transition: "all 0.2s",
                        backgroundColor: activeTab === "manage" ? "rgba(243, 186, 47, 0.1)" : "transparent",
                        color: activeTab === "manage" ? colors.textPrimary : colors.textMuted,
                      }}
                      onClick={() => {
                        setActiveTab("manage");
                        clearFormErrors();
                      }}
                    >
                      Manage Accounts
                    </div>
                  )}
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
                          Email
                        </span>
                        <span style={{ color: colors.textSecondary, fontSize: 13, fontWeight: 500 }}>
                          {tokenEmail || userEmail}
                        </span>
                      </div>

                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingBottom: 8 }}>
                        <span style={{ color: colors.textMuted, fontSize: 12, fontWeight: 500 }}>
                          Role
                        </span>
                        <span style={{ color: colors.textSecondary, fontSize: 13, fontWeight: 500 }}>
                          {userRole === "admin" ? "Admin" : "User"}
                        </span>
                      </div>

                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingBottom: 8 }}>
                        <span style={{ color: colors.textMuted, fontSize: 12, fontWeight: 500 }}>
                          Environment
                        </span>
                        <span style={{ 
                          color: envStage === "PROD STAGE" ? colors.increase : "#F3BA2F", 
                          fontSize: 13, 
                          fontWeight: 600 
                        }}>
                          {envStage}
                        </span>
                      </div>
                    </div>
                  ) : activeTab === "manage" ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                      {selectedUserForPassword ? (
                        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                          <h4 style={{ color: colors.textSecondary, fontSize: 13, fontWeight: 600, margin: 0 }}>
                            Modify Password for {selectedUserForPassword.username || selectedUserForPassword.email}
                          </h4>
                          <input
                            type="password"
                            placeholder="Enter new password"
                            value={adminNewPassword}
                            onChange={(e) => setAdminNewPassword(e.target.value)}
                            style={{
                              padding: "8px 12px",
                              borderRadius: 6,
                              backgroundColor: "rgba(255, 255, 255, 0.04)",
                              border: `1px solid ${colors.border}`,
                              color: colors.textSecondary,
                              fontSize: 13,
                              outline: "none",
                            }}
                          />
                          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 8 }}>
                            <button
                              onClick={() => {
                                setSelectedUserForPassword(null);
                                setAdminNewPassword("");
                              }}
                              style={{
                                padding: "6px 12px",
                                borderRadius: 6,
                                border: "none",
                                backgroundColor: "rgba(255, 255, 255, 0.08)",
                                color: colors.textSecondary,
                                fontSize: 12,
                                cursor: "pointer",
                              }}
                            >
                              Cancel
                            </button>
                            <button
                              onClick={handleAdminModifyPassword}
                              style={{
                                padding: "6px 12px",
                                borderRadius: 6,
                                border: "none",
                                backgroundColor: "#F3BA2F",
                                color: "#1E1E1E",
                                fontWeight: 600,
                                fontSize: 12,
                                cursor: "pointer",
                              }}
                            >
                              Save
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                          <h4 style={{ color: colors.textSecondary, fontSize: 14, fontWeight: 600, margin: "0 0 8px 0" }}>
                            User Accounts
                          </h4>
                          {allUsersLoading ? (
                            <div style={{ color: colors.textMuted, fontSize: 12, textAlign: "center", padding: 20 }}>
                              Loading...
                            </div>
                          ) : allUsersList.filter(usr => usr.role !== "admin").length === 0 ? (
                            <div style={{ color: colors.textMuted, fontSize: 12, textAlign: "center", padding: 20 }}>
                              No users found
                            </div>
                          ) : (
                            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                              {allUsersList.filter(usr => usr.role !== "admin").map((usr) => (
                                <div
                                  key={usr.id}
                                  style={{
                                    padding: "10px 12px",
                                    borderRadius: 8,
                                    backgroundColor: "rgba(255, 255, 255, 0.02)",
                                    border: "1px solid rgba(255, 255, 255, 0.04)",
                                    display: "flex",
                                    flexDirection: "column",
                                    gap: 6,
                                  }}
                                >
                                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                    <span style={{ fontWeight: 600, color: colors.textPrimary, fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 180 }}>
                                      {usr.username || usr.email}
                                    </span>
                                    <span style={{ color: colors.textMuted, fontSize: 10, whiteSpace: "nowrap" }}>
                                      Last Active: {usr.last_active ? (() => {
                                        const d = new Date(usr.last_active);
                                        const day = String(d.getDate()).padStart(2, "0");
                                        const month = String(d.getMonth() + 1).padStart(2, "0");
                                        const year = d.getFullYear();
                                        const h = String(d.getHours()).padStart(2, "0");
                                        const m = String(d.getMinutes()).padStart(2, "0");
                                        return `${day}/${month}/${year} ${h}:${m}`;
                                      })() : "Never"}
                                    </span>
                                  </div>

                                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 4 }}>
                                    <div style={{ minHeight: 16, display: "flex", alignItems: "center" }}>
                                      {usr.username && usr.email && usr.username !== usr.email && (
                                        <span style={{ color: colors.textMuted, fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 220, display: "inline-block" }}>
                                          {usr.email}
                                        </span>
                                      )}
                                    </div>
                                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                                      <button
                                        onClick={() => setSelectedUserForPassword(usr)}
                                        style={{
                                          padding: "3px 8px",
                                          borderRadius: 4,
                                          border: "1px solid rgba(255, 255, 255, 0.1)",
                                          backgroundColor: "transparent",
                                          color: colors.textPrimary,
                                          fontSize: 10,
                                          cursor: "pointer",
                                        }}
                                      >
                                        Password
                                      </button>
                                      {usr.id !== (accessToken ? JSON.parse(atob(accessToken.split(".")[1])).userId : null) && (
                                        <button
                                          onClick={() => handleRemoveUser(usr.id)}
                                          style={{
                                            padding: "3px 8px",
                                            borderRadius: 4,
                                            border: "none",
                                            backgroundColor: "rgba(246, 70, 93, 0.15)",
                                            color: "#F6465D",
                                            fontSize: 10,
                                            cursor: "pointer",
                                          }}
                                        >
                                          Remove
                                        </button>
                                      )}
                                    </div>
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                      {modalError && (
                        <div style={{ color: colors.decrease, fontSize: 12, fontWeight: 500 }}>
                          {modalError}
                        </div>
                      )}


                      {/* Inputs */}
                      {userRole !== "admin" && (
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
                      )}

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

      {selectedPendingUser && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            width: "100vw",
            height: "100vh",
            backgroundColor: "rgba(0, 0, 0, 0.6)",
            backdropFilter: "blur(4px)",
            WebkitBackdropFilter: "blur(4px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 9999,
          }}
        >
          <div
            style={{
              width: 440,
              backgroundColor: "#1E1E1E",
              borderRadius: 12,
              border: `1px solid ${colors.border}`,
              padding: 24,
              boxShadow: "0 12px 36px rgba(0,0,0,0.6)",
              display: "flex",
              flexDirection: "column",
              gap: 20,
            }}
          >
            <div>
              <h3 style={{ color: colors.textPrimary, fontSize: 18, fontWeight: 600, margin: "0 0 4px 0" }}>
                Pending User Approval
              </h3>
              <p style={{ color: colors.textMuted, fontSize: 13, margin: 0 }}>
                Review user registration details below.
              </p>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 12, backgroundColor: "rgba(255, 255, 255, 0.02)", padding: 16, borderRadius: 8, border: "1px solid rgba(255, 255, 255, 0.04)" }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: colors.textMuted, fontSize: 13 }}>Email:</span>
                <span style={{ color: colors.textPrimary, fontSize: 13, fontWeight: 500 }}>{selectedPendingUser.email}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: colors.textMuted, fontSize: 13 }}>Registered:</span>
                <span style={{ color: colors.textPrimary, fontSize: 13, fontWeight: 500 }}>
                  {formatNotificationDate(new Date(selectedPendingUser.created_at))}
                </span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>
                <span style={{ color: colors.textMuted, fontSize: 13 }}>Device Sign-up:</span>
                <span style={{ color: colors.textSecondary, fontSize: 12, lineHeight: "1.4", wordBreak: "break-all", fontFamily: "monospace" }}>
                  {selectedPendingUser.login_device || "Unknown User-Agent"}
                </span>
              </div>
            </div>

            <div style={{ display: "flex", gap: 12 }}>
              <button
                onClick={() => handleApproveUser(selectedPendingUser.id)}
                style={{
                  flex: 1,
                  padding: "10px",
                  borderRadius: 6,
                  backgroundColor: colors.increase,
                  color: "#FFFFFF",
                  border: "none",
                  fontWeight: 600,
                  fontSize: 13,
                  cursor: "pointer",
                  transition: "opacity 0.2s",
                }}
                onMouseOver={(e) => (e.currentTarget.style.opacity = "0.9")}
                onMouseOut={(e) => (e.currentTarget.style.opacity = "1")}
              >
                APPROVE
              </button>
              <button
                onClick={() => handleRejectUser(selectedPendingUser.id)}
                style={{
                  flex: 1,
                  padding: "10px",
                  borderRadius: 6,
                  backgroundColor: colors.decrease,
                  color: "#FFFFFF",
                  border: "none",
                  fontWeight: 600,
                  fontSize: 13,
                  cursor: "pointer",
                  transition: "opacity 0.2s",
                }}
                onMouseOver={(e) => (e.currentTarget.style.opacity = "0.9")}
                onMouseOut={(e) => (e.currentTarget.style.opacity = "1")}
              >
                REJECT
              </button>
              <button
                onClick={() => setSelectedPendingUser(null)}
                style={{
                  padding: "10px 16px",
                  borderRadius: 6,
                  backgroundColor: "rgba(255, 255, 255, 0.08)",
                  color: colors.textPrimary,
                  border: `1px solid ${colors.border}`,
                  fontSize: 13,
                  cursor: "pointer",
                  transition: "background-color 0.2s",
                }}
                onMouseOver={(e) => (e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.12)")}
                onMouseOut={(e) => (e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.08)")}
              >
                CANCEL
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

