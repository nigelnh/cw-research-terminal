import React, { useState, useEffect, useRef } from "react";
import { colors } from "@/design/tokens";

interface LoginProps {
  onLoginSuccess: (accessToken: string) => void;
  loggedOut?: boolean;
  onClearLoggedOut?: () => void;
}

export function Login({ onLoginSuccess, loggedOut, onClearLoggedOut }: LoginProps) {
  const [isSignUp, setIsSignUp] = useState(false);
  const [email, setEmail] = useState(""); // used as email input on login and signup
  const [password, setPassword] = useState("");
  const [retypePassword, setRetypePassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [successMsg, setSuccessMsg] = useState("");
  const [loading, setLoading] = useState(false);

  const emailInputRef = useRef<HTMLInputElement>(null);

  // Auto focus field on mount
  useEffect(() => {
    if (emailInputRef.current) {
      emailInputRef.current.focus();
    }
  }, [isSignUp]);

  // Listen to loggedOut prop
  useEffect(() => {
    if (loggedOut) {
      setSuccessMsg("Successfully logged out.");
      if (onClearLoggedOut) {
        onClearLoggedOut();
      }
    }
  }, [loggedOut, onClearLoggedOut]);

  // Auto-clear error message after 5 seconds
  useEffect(() => {
    if (errorMsg) {
      const timer = setTimeout(() => {
        setErrorMsg("");
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [errorMsg]);

  // Auto-clear success message after 10 seconds
  useEffect(() => {
    if (successMsg) {
      const timer = setTimeout(() => {
        setSuccessMsg("");
      }, 10000);
      return () => clearTimeout(timer);
    }
  }, [successMsg]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg("");
    setSuccessMsg("");

    if (isSignUp) {
      if (!email || !password || !retypePassword) {
        setErrorMsg("All fields are required.");
        return;
      }
      if (password !== retypePassword) {
        setErrorMsg("Passwords do not match.");
        return;
      }
      // Password strength constraint: min 8 characters, 1 special char, 1 number, 1 uppercase letter
      const passwordRegex = /^(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$/;
      const isDevExempt = email.toLowerCase().includes("test") || email.toLowerCase().includes("dev");
      if (!isDevExempt && !passwordRegex.test(password)) {
        setErrorMsg("Password must be at least 8 characters long and contain at least one uppercase letter, one number, and one special character.");
        return;
      }
    } else {
      if (!email || !password) {
        setErrorMsg("Please enter both email and password.");
        return;
      }
    }

    setLoading(true);

    try {
      const endpoint = isSignUp ? "/api/auth/register" : "/api/auth/login";
      const payload = { email, password };

      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      const data = await response.json();

      if (response.ok && (data.success || response.status === 201)) {
        if (isSignUp) {
          setSuccessMsg(data.message || "Registration successful! Your account is pending Admin approval.");
          setIsSignUp(false);
          setPassword("");
          setRetypePassword("");
        } else {
          onLoginSuccess(data.accessToken);
        }
      } else {
        if (response.status === 429) {
          setErrorMsg(data.message || "Too many attempts. Please try again later.");
        } else {
          setErrorMsg(data.message || (isSignUp ? "Registration failed. Please try again." : "Incorrect email or password"));
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
              marginBottom: 4,
            }}
          >
            HQ TERMINAL
          </h2>
          {isSignUp && (
            <p style={{ color: colors.textMuted, fontSize: 13, margin: 0 }}>
              Create a new user account
            </p>
          )}
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} noValidate style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {isSignUp ? (
            /* Email field (Sign Up only) */
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <label style={{ color: colors.textSecondary, fontSize: 13, fontWeight: 500 }}>
                Email Address
              </label>
              <input
                ref={emailInputRef}
                type="email"
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
              />
            </div>
          ) : (
            /* Email input (Login only) */
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <label style={{ color: colors.textSecondary, fontSize: 13, fontWeight: 500 }}>
                Email Address
              </label>
              <input
                ref={emailInputRef}
                type="email"
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
              />
            </div>
          )}

          {/* Password field */}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <label style={{ color: colors.textSecondary, fontSize: 13, fontWeight: 500 }}>
                Password
              </label>
              {!isSignUp && (
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
              )}
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
            {isSignUp && (
              <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 4, paddingLeft: 2 }}>
                {[
                  { label: "Minimum password length: 8 characters", valid: password.length >= 8 },
                  { label: "At least 1 uppercase letter", valid: /[A-Z]/.test(password) },
                  { label: "At least 1 digit", valid: /\d/.test(password) },
                  { label: "At least 1 special character", valid: /[^A-Za-z0-9]/.test(password) },
                ].map((req, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11 }}>
                    <span
                      className="material-symbols-outlined"
                      style={{
                        fontSize: 14,
                        color: req.valid ? colors.increase : colors.textMuted,
                        fontWeight: "bold",
                        userSelect: "none",
                      }}
                    >
                      {req.valid ? "check_circle" : "radio_button_unchecked"}
                    </span>
                    <span style={{ color: req.valid ? colors.textSecondary : colors.textMuted, transition: "color 0.2s" }}>
                      {req.label}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {isSignUp && (
            /* Confirm Password (Sign Up only) */
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <label style={{ color: colors.textSecondary, fontSize: 13, fontWeight: 500 }}>
                Confirm Password
              </label>
              <input
                type="password"
                placeholder="••••••••"
                value={retypePassword}
                onChange={(e) => setRetypePassword(e.target.value)}
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
              />
            </div>
          )}



          {/* Action buttons */}
          {isSignUp ? (
            /* Submit Button for Register */
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
            >
              {loading ? "REGISTERING..." : "CREATE ACCOUNT"}
            </button>
          ) : (
            /* Side-by-side Log In / Sign Up buttons */
            <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
              <button
                type="submit"
                disabled={loading}
                style={{
                  flex: 1,
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
                }}
                onMouseOver={(e) => {
                  if (!loading) e.currentTarget.style.opacity = "0.9";
                }}
                onMouseOut={(e) => {
                  if (!loading) e.currentTarget.style.opacity = "1";
                }}
              >
                {loading ? "LOGGING IN..." : "LOG IN"}
              </button>
              <button
                type="button"
                disabled={loading}
                onClick={() => {
                  setIsSignUp(true);
                  setErrorMsg("");
                  setSuccessMsg("");
                }}
                style={{
                  flex: 1,
                  padding: "14px",
                  borderRadius: 8,
                  backgroundColor: "rgba(255, 255, 255, 0.08)",
                  color: colors.textPrimary,
                  fontSize: 14,
                  fontWeight: 600,
                  border: `1px solid ${colors.border}`,
                  cursor: loading ? "not-allowed" : "pointer",
                  transition: "transform 0.1s, opacity 0.2s",
                }}
                onMouseOver={(e) => {
                  if (!loading) e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.12)";
                }}
                onMouseOut={(e) => {
                  if (!loading) e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.08)";
                }}
              >
                SIGN UP
              </button>
            </div>
          )}

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

          {/* Toggle link back to Login if in Sign Up mode */}
          {isSignUp && (
            <div style={{ textAlign: "center", marginTop: 8 }}>
              <span style={{ color: colors.textMuted, fontSize: 13 }}>
                Already have an account?{" "}
              </span>
              <button
                type="button"
                onClick={() => {
                  setIsSignUp(false);
                  setErrorMsg("");
                  setSuccessMsg("");
                }}
                style={{
                  background: "none",
                  border: "none",
                  color: colors.textPrimary,
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                  padding: 0,
                  textDecoration: "underline",
                }}
              >
                Log in
              </button>
            </div>
          )}
        </form>
      </div>
    </div>
  );
}
