/* Tabs — underline tab bar. */

export function Tabs({
  tabs,
  value,
  onChange,
}: {
  tabs: readonly string[];
  value: string;
  onChange: (tab: string) => void;
}) {
  return (
    <div style={{ display: "flex", gap: 2, borderBottom: "1px solid var(--border)" }}>
      {tabs.map((t) => {
        const active = t === value;
        return (
          <button
            key={t}
            onClick={() => onChange(t)}
            style={{
              padding: "8px 14px",
              border: "none",
              background: "transparent",
              cursor: "pointer",
              fontFamily: "var(--font-sans)",
              fontSize: 13,
              fontWeight: active ? 700 : 500,
              color: active ? "var(--foreground)" : "var(--muted-foreground)",
              borderBottom: `2px solid ${active ? "var(--brand-deep)" : "transparent"}`,
              marginBottom: -1,
              transition: "color var(--dur-fast) var(--ease-out)",
            }}
          >
            {t}
          </button>
        );
      })}
    </div>
  );
}
