import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

type InputSize = "xs" | "sm";

const SIZE_STYLES: Record<InputSize, string> = {
  xs: "px-2.5 py-1 text-[11px]",
  sm: "px-3 py-2 text-sm",
};

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  uiSize?: InputSize;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, uiSize = "sm", ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "w-full border border-neutral-700 bg-neutral-950 font-mono text-neutral-200 outline-none transition placeholder:text-neutral-400 hover:border-neutral-600 focus:border-brand-500/60",
        SIZE_STYLES[uiSize],
        className
      )}
      {...props}
    />
  )
);

Input.displayName = "Input";
