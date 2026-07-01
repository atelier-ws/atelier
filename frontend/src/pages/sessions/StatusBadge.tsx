import { cx } from "../../components/WorkbenchUI";

const STATUS_MAP: Record<string, string> = {
  success: "text-emerald-300 border-emerald-500/30 bg-emerald-500/5",
  completed: "text-emerald-300 border-emerald-500/30 bg-emerald-500/5",
  failed: "text-red-300 border-red-500/30 bg-red-500/5",
  error: "text-red-300 border-red-500/30 bg-red-500/5",
  partial: "text-amber-300 border-amber-500/30 bg-amber-500/5",
  running: "text-sky-300 border-sky-500/30 bg-sky-500/5",
};

const STATUS_NEUTRAL =
  "text-neutral-400 border-neutral-500/30 bg-neutral-500/5";

const STATUS_DOT_MAP: Record<string, string> = {
  success: "bg-emerald-500",
  completed: "bg-emerald-500",
  failed: "bg-red-500",
  error: "bg-red-500",
  partial: "bg-amber-500",
  running: "bg-sky-500",
};

export function StatusDot({
  status,
  className,
}: {
  status: string;
  className?: string;
}) {
  return (
    <span
      className={cx(
        "inline-block h-2 w-2 rounded-full",
        STATUS_DOT_MAP[status] || "bg-neutral-500",
        className
      )}
      title={status}
      aria-label={`Status: ${status}`}
    />
  );
}

export function StatusBadge({
  status,
  className,
}: {
  status: string;
  className?: string;
}) {
  return (
    <span
      className={cx(
        "text-[10px] px-2 py-0.5 border uppercase font-black tracking-[0.2em] font-mono inline-block",
        STATUS_MAP[status] || STATUS_NEUTRAL,
        className
      )}
    >
      {status}
    </span>
  );
}
