/* ThemeToggle — light/dark switch using the ◐ / ◑ glyphs. */

import { Icon } from "./Icon";
import { useThemeContext } from "../store/theme";

export function ThemeToggle({ size = "md" }: { size?: "sm" | "md" }) {
  const { theme, toggle } = useThemeContext();
  const px = size === "sm" ? 30 : 36;
  return (
    <button
      onClick={toggle}
      aria-label={theme === "light" ? "Cambiar a tema oscuro" : "Cambiar a tema claro"}
      title={theme === "light" ? "Tema oscuro" : "Tema claro"}
      style={{
        width: px,
        height: px,
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-md)",
        background: "transparent",
        color: "var(--foreground)",
        cursor: "pointer",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        transition: "transform var(--dur-fast) var(--ease-out)",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.transform = "scale(1.05)")}
      onMouseLeave={(e) => (e.currentTarget.style.transform = "scale(1)")}
    >
      <Icon name={theme === "light" ? "THEME_DARK" : "THEME_LIGHT"} size={size === "sm" ? 14 : 16} />
    </button>
  );
}
