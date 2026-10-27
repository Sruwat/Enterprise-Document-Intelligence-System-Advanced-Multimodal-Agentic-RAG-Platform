"use client";

import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from "react";
import { Theme } from "./types";

type ThemeContextValue = { theme: Theme; toggleTheme: () => void; setTheme: (theme: Theme) => void };
const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>("dark");

  useEffect(() => {
    const stored = window.localStorage.getItem("aiwana_theme") as Theme | null;
    if (stored === "dark" || stored === "light") setThemeState(stored);
  }, []);

  function setTheme(theme: Theme) {
    setThemeState(theme);
    window.localStorage.setItem("aiwana_theme", theme);
  }

  const value = useMemo(() => ({ theme, setTheme, toggleTheme: () => setTheme(theme === "dark" ? "light" : "dark") }), [theme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme must be used inside ThemeProvider");
  return value;
}
