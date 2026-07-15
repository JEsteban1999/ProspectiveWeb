/* ProgressBar — thin bar, determinate (0–100) or indeterminate sweep. */

export function ProgressBar({ value }: { value?: number }) {
  const indeterminate = value === undefined;
  return (
    <div
      role="progressbar"
      aria-valuenow={indeterminate ? undefined : value}
      style={{
        position: "relative",
        height: 5,
        borderRadius: 3,
        background: "var(--muted)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          top: 0,
          bottom: 0,
          borderRadius: 3,
          background: "var(--primary)",
          width: indeterminate ? "35%" : `${value}%`,
          left: indeterminate ? undefined : 0,
          animation: indeterminate ? "progress-sweep 1.2s var(--ease-in-out) infinite" : undefined,
          transition: indeterminate ? undefined : "width var(--dur-base) var(--ease-out)",
        }}
      />
    </div>
  );
}
