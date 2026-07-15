/* ThemeContext — one theme instance for the whole app (App provides it). */

import { createContext, useContext } from "react";
import type { ReactNode } from "react";
import { useTheme } from "../hooks/useTheme";

const ThemeContext = createContext<{ theme: "light" | "dark"; toggle: () => void }>({
  theme: "light",
  toggle: () => {},
});

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, toggle] = useTheme();
  return <ThemeContext.Provider value={{ theme, toggle }}>{children}</ThemeContext.Provider>;
}

export function useThemeContext() {
  return useContext(ThemeContext);
}
