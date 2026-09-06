// src/lib/use-auth.ts
import { useState, useEffect } from "react";
import { client } from "./api";
// We can use a lightweight library to decode the JWT on the client side
import { jwtDecode } from "jwt-decode";

// Install this via: npm install jwt-decode

export function useAuth() {
  const [user, setUser] = useState<any>(null);
  const [isPending, setIsPending] = useState(true);

  // Check for existing session on load
  useEffect(() => {
    const token = localStorage.getItem("pantry_token");
    if (token) {
      try {
        const decoded = jwtDecode(token);
        // Check if token is expired
        if (decoded.exp && decoded.exp * 1000 > Date.now()) {
          setUser(decoded);
        } else {
          localStorage.removeItem("pantry_token");
        }
      } catch {
        localStorage.removeItem("pantry_token");
      }
    }
    setIsPending(false);
  }, []);

  const login = async (email: string, password: string) => {
    const { data, error } = await client.POST("/auth/login", {
      body: { email, password },
    });

    if (error) throw new Error(error as string);

    // Save token and set user
    localStorage.setItem("pantry_token", `${(data as any).token}`);
    setUser((data as any).user);
  };

  const logout = () => {
    localStorage.removeItem("pantry_token");
    setUser(null);
  };

  // Inside src/lib/use-auth.ts
  const signup = async (
    email: string,
    password: string,
    display_name: string,
  ) => {
    const { data, error } = await client.POST("/auth/signup", {
      // Your backend explicitly expects role: "charity" for self-signups
      body: { email, password, display_name, role: "charity" },
    });

    if (error) {
      // Extract the exact error message from your Python backend (e.g. "Password needs an uppercase letter")
      const err = error as any;
      throw new Error(err.message || err.detail || "Failed to create account");
    }

    localStorage.setItem("pantry_token", (data as any).token);
    setUser((data as any).user);
  };

  return { user, isPending, login, logout, signup };
}
