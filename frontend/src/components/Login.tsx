import React, { useState, useEffect, useRef } from "react";
import { colors } from "@/design/tokens";

interface LoginProps {
  onLoginSuccess: (accessToken: string) => void;
  loggedOut?: boolean;
  onClearLoggedOut?: () => void;
}

declare global {
  interface Window {
    turnstile?: {
      render: (container: string | HTMLElement, params: any) => string;
      reset: (widgetId?: string) => void;
      remove: (widgetId?: string) => void;
    };
  }
}

export function Login({ onLoginSuccess, loggedOut, onClearLoggedOut }: LoginProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [successMsg, setSuccessMsg] = useState("");
  const [loading, setLoading] = useState(false);
  const [showCaptcha, setShowCaptcha] = useState(false);
  const [turnstileToken, setTurnstileToken] = useState("");

  const emailInputRef = useRef<HTMLInputElement>(null);
  const turnstileWidgetId = useRef<string | null>(null);

  // Auto focus email field on mount
  useEffect(() => {
    if (emailInputRef.current) {
      emailInputRef.current.focus();
    }
  }, []);

  // Listen to loggedOut prop
  useEffect(() => {
    if (loggedOut) {
      setSuccessMsg("Successfully logged out.");
      if (onClearLoggedOut) {
        onClearLoggedOut();
      }
    }
  }, [loggedOut, onClearLoggedOut]);

  // Auto-clear error message after 3 seconds
  useEffect(() => {
    if (errorMsg) {
      const timer = setTimeout(() => {
        setErrorMsg("");
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [errorMsg]);

  // Auto-clear success message after 3 seconds
  useEffect(() => {
    if (successMsg) {
      const timer = setTimeout(() => {
        setSuccessMsg("");
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [successMsg]);

  // Dynamically load Cloudflare Turnstile script if captcha is required
  useEffect(() => {
    if (showCaptcha) {
      const existingScript = document.getElementById("cf-turnstile-script");
      if (!existingScript) {
        const script = document.createElement("script");
        script.id = "cf-turnstile-script";
        script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
        script.async = true;
        script.defer = true;
        document.body.appendChild(script);
        script.onload = initializeTurnstile;
      } else {
        initializeTurnstile();
      }
    }
    return () => {
      if (window.turnstile && turnstileWidgetId.current) {
        try {
          window.turnstile.remove(turnstileWidgetId.current);
        } catch (e) {
          // ignore
        }
      }
    };
  }, [showCaptcha]);

  const initializeTurnstile = () => {
    if (window.turnstile && document.getElementById("turnstile-container")) {
      try {
        if (turnstileWidgetId.current) {
          window.turnstile.reset(turnstileWidgetId.current);
        } else {
          turnstileWidgetId.current = window.turnstile.render("#turnstile-container", {
            sitekey: "1x0000000000000000000000000000000AA", // CF Test Sitekey
            theme: "dark",
            callback: (token: string) => {
              setTurnstileToken(token);
            },
          });
        }
      } catch (err) {
        console.error("Failed to render Turnstile widget:", err);
      }
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      setErrorMsg("Please enter both email and password.");
      return;
    }

    if (showCaptcha && !turnstileToken) {
      setErrorMsg("Please complete CAPTCHA verification.");
      return;
    }

    setErrorMsg("");
    setLoading(true);

    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          email,
          password,
          turnstileToken: showCaptcha ? turnstileToken : undefined,
        }),
      });

      const data = await response.json();

      if (response.ok && data.success) {
        onLoginSuccess(data.accessToken);
      } else {
        // Handle login failure
        if (data.showCaptcha) {
          setShowCaptcha(true);
          // reset turnstile token if already rendered
          setTurnstileToken("");
          if (window.turnstile && turnstileWidgetId.current) {
            window.turnstile.reset(turnstileWidgetId.current);
          }
        }

        if (response.status === 429) {
          setErrorMsg(data.message || "Account temporarily locked due to multiple failed login attempts. Please try again in 5 minutes.");
        } else {
          setErrorMsg("Invalid email or password. Please try again.");
        }
      }
    } catch (err) {
      setErrorMsg("A connection error occurred. Please try again later.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        height: "100vh",
        width: "100vw",
        backgroundColor: colors.background,
        backgroundImage: "radial-gradient(circle at center, rgba(243, 186, 47, 0.05) 0%, rgba(14, 17, 23, 1) 70%)",
      }}
    >
      <div
        style={{
          width: 400,
          padding: "40px 32px",
          borderRadius: 16,
          backgroundColor: "rgba(30, 30, 30, 0.4)",
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
          border: `1px solid ${colors.border}`,
          boxShadow: "0 8px 32px 0 rgba(0, 0, 0, 0.37)",
          display: "flex",
          flexDirection: "column",
          gap: 24,
        }}
      >
        {/* Header */}
        <div style={{ textAlign: "center" }}>
          <h2
            style={{
              color: colors.textPrimary,
              fontSize: 24,
              fontWeight: 700,
              letterSpacing: "0.5px",
              marginBottom: 8,
            }}
          >
            HQ TERMINAL
          </h2>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {/* Email input */}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <label style={{ color: colors.textSecondary, fontSize: 13, fontWeight: 500 }}>
              Username
            </label>
            <input
              ref={emailInputRef}
              type="text"
              placeholder="name@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={loading}
              style={{
                width: "100%",
                padding: "12px 16px",
                borderRadius: 8,
                backgroundColor: "rgba(255, 255, 255, 0.04)",
                border: `1px solid ${colors.border}`,
                color: colors.textSecondary,
                fontSize: 14,
                outline: "none",
                transition: "border-color 0.2s, box-shadow 0.2s",
              }}
              onFocus={(e) => {
                e.target.style.borderColor = colors.textPrimary;
                e.target.style.boxShadow = `0 0 0 2px rgba(243, 186, 47, 0.2)`;
              }}
              onBlur={(e) => {
                e.target.style.borderColor = colors.border;
                e.target.style.boxShadow = "none";
              }}
            />
          </div>

          {/* Password input */}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <label style={{ color: colors.textSecondary, fontSize: 13, fontWeight: 500 }}>
                Password
              </label>
              <a
                href="#forgot-password"
                onClick={(e) => {
                  e.preventDefault();
                  alert("Please contact the administrator to reset your password.");
                }}
                style={{
                  color: colors.textPrimary,
                  fontSize: 12,
                  textDecoration: "none",
                  transition: "opacity 0.2s",
                }}
                onMouseOver={(e) => (e.currentTarget.style.opacity = "0.8")}
                onMouseOut={(e) => (e.currentTarget.style.opacity = "1")}
              >
                Forgot password?
              </a>
            </div>
            <div style={{ position: "relative" }}>
              <input
                type={showPassword ? "text" : "password"}
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={loading}
                style={{
                  width: "100%",
                  padding: "12px 48px 12px 16px",
                  borderRadius: 8,
                  backgroundColor: "rgba(255, 255, 255, 0.04)",
                  border: `1px solid ${colors.border}`,
                  color: colors.textSecondary,
                  fontSize: 14,
                  outline: "none",
                  transition: "border-color 0.2s, box-shadow 0.2s",
                }}
                onFocus={(e) => {
                  e.target.style.borderColor = colors.textPrimary;
                  e.target.style.boxShadow = `0 0 0 2px rgba(243, 186, 47, 0.2)`;
                }}
                onBlur={(e) => {
                  e.target.style.borderColor = colors.border;
                  e.target.style.boxShadow = "none";
                }}
              />
              <span
                className="material-symbols-outlined"
                onClick={() => setShowPassword(!showPassword)}
                style={{
                  position: "absolute",
                  right: 14,
                  top: "50%",
                  transform: "translateY(-50%)",
                  cursor: "pointer",
                  color: colors.textMuted,
                  fontSize: 20,
                  userSelect: "none",
                }}
              >
                {showPassword ? "visibility" : "visibility_off"}
              </span>
            </div>
          </div>

          {/* Cloudflare Turnstile */}
          {showCaptcha && (
            <div
              style={{
                display: "flex",
                justifyContent: "center",
                marginTop: 8,
                minHeight: 65,
              }}
            >
              <div id="turnstile-container"></div>
            </div>
          )}

          {/* Submit button */}
          <button
            type="submit"
            disabled={loading}
            style={{
              width: "100%",
              padding: "14px",
              borderRadius: 8,
              backgroundColor: colors.textPrimary,
              color: colors.background,
              fontSize: 14,
              fontWeight: 600,
              border: "none",
              cursor: loading ? "not-allowed" : "pointer",
              transition: "transform 0.1s, opacity 0.2s",
              opacity: loading ? 0.7 : 1,
              marginTop: 8,
            }}
            onMouseOver={(e) => {
              if (!loading) e.currentTarget.style.opacity = "0.9";
            }}
            onMouseOut={(e) => {
              if (!loading) e.currentTarget.style.opacity = "1";
            }}
            onMouseDown={(e) => {
              if (!loading) e.currentTarget.style.transform = "scale(0.98)";
            }}
            onMouseUp={(e) => {
              if (!loading) e.currentTarget.style.transform = "scale(1)";
            }}
          >
            {loading ? "PROCESSING..." : "LOG IN"}
          </button>

          {/* Error message */}
          {errorMsg && (
            <div
              style={{
                backgroundColor: "rgba(246, 70, 93, 0.1)",
                border: `1px solid ${colors.decrease}`,
                borderRadius: 8,
                padding: "12px 16px",
                color: colors.decrease,
                fontSize: 13,
                lineHeight: "18px",
                marginTop: 4,
              }}
            >
              {errorMsg}
            </div>
          )}

          {/* Success message */}
          {successMsg && (
            <div
              style={{
                backgroundColor: "rgba(14, 203, 129, 0.1)",
                border: `1px solid ${colors.increase}`,
                borderRadius: 8,
                padding: "12px 16px",
                color: colors.increase,
                fontSize: 13,
                lineHeight: "18px",
                marginTop: 4,
              }}
            >
              {successMsg}
            </div>
          )}
        </form>
      </div>
    </div>
  );
}
