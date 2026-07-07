import { forwardRef, type SelectHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

type SelectSize = "xs" | "sm";

const SIZE_STYLES: Record<SelectSize, string> = {
  xs: "px-2.5 py-1 text-[10px]",
  sm: "px-3 py-2 text-sm",
};

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  uiSize?: SelectSize;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, uiSize = "sm", ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        "border border-neutral-700 bg-neutral-950 font-mono text-neutral-200 outline-none transition hover:border-neutral-600 focus:border-brand-500/60",
        SIZE_STYLES[uiSize],
        className
      )}
      {...props}
    />
  )
);

Select.displayName = "Select";
