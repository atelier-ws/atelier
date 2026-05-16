import { cx } from "../../components/WorkbenchUI";

const STATUS_MAP: Record<string, string> = {
  success: "text-emerald-500 border-emerald-500/30 bg-emerald-500/5",
  failed: "text-red-500 border-red-500/30 bg-red-500/5",
  partial: "text-amber-500 border-amber-500/30 bg-amber-500/5",
};

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
        "text-[9px] px-2 py-0.5 border uppercase font-black tracking-[0.2em] font-mono inline-block",
        STATUS_MAP[status] || STATUS_MAP.failed,
        className
      )}
    >
      {status}
    </span>
  );
}
