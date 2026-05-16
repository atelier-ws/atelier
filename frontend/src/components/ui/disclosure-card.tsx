import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

interface DisclosureCardProps {
  open: boolean;
  onToggle: () => void;
  header: ReactNode;
  children?: ReactNode;
  className?: string;
  triggerClassName?: string;
  contentClassName?: string;
}

export function DisclosureCard({
  open,
  onToggle,
  header,
  children,
  className,
  triggerClassName,
  contentClassName,
}: DisclosureCardProps) {
  return (
    <div
      className={cn(
        "overflow-hidden border border-neutral-800 bg-neutral-900/50 transition-all",
        className
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        className={cn(
          "w-full px-5 py-4 text-left transition-colors hover:bg-neutral-800/50",
          triggerClassName
        )}
      >
        {header}
      </button>
      {open && (
        <div
          className={cn(
            "border-t border-neutral-800 bg-neutral-950/50 px-5 py-4",
            contentClassName
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}
