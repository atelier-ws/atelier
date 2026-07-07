import {
  forwardRef,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";
import { cn } from "../../lib/utils";

type ButtonVariant =
  | "outline"
  | "ghost"
  | "accent"
  | "amber"
  | "emerald"
  | "danger"
  | "link";
type ButtonSize = "xs" | "sm" | "icon";

const VARIANT_STYLES: Record<ButtonVariant, string> = {
  outline:
    "border-neutral-700 text-neutral-300 hover:border-neutral-500 hover:text-neutral-100",
  ghost:
    "border-transparent text-neutral-400 hover:border-neutral-700 hover:bg-neutral-900/40 hover:text-neutral-200",
  accent:
    "border-brand-500/60 text-brand-300 hover:bg-brand-500/10 hover:text-brand-200",
  amber:
    "border-amber-500/60 text-amber-200 hover:bg-amber-500/10 hover:text-amber-100",
  emerald:
    "border-emerald-700 text-emerald-200 hover:border-emerald-500 hover:text-emerald-100",
  danger: "border-red-700 text-red-200 hover:border-red-500 hover:text-red-100",
  link: "border-transparent px-0 py-0 text-neutral-400 hover:text-neutral-300",
};

const SIZE_STYLES: Record<ButtonSize, string> = {
  xs: "px-2.5 py-1 text-[10px] tracking-widest",
  sm: "px-3 py-2 text-xs tracking-widest",
  icon: "h-5 w-5 px-0 py-0 text-xs",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  active?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant = "outline",
      size = "sm",
      active = false,
      icon,
      children,
      type = "button",
      ...props
    },
    ref
  ) => (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex items-center justify-center gap-2 border bg-transparent font-mono uppercase transition disabled:cursor-not-allowed disabled:opacity-40",
        SIZE_STYLES[size],
        VARIANT_STYLES[variant],
        active && variant === "outline" && "border-neutral-500 bg-neutral-800 text-neutral-100",
        className
      )}
      {...props}
    >
      {icon}
      {children}
    </button>
  )
);

Button.displayName = "Button";
