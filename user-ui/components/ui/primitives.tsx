/**
 * Lightweight, dependency-free UI primitives, shadcn-styled, matching the ui2 look
 * (ADR-011). Kept in one file because there are few of them and they share the same
 * token vocabulary; splitting them would mean nine files of ten lines each.
 */

import * as React from "react";

import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- Card */

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-lg border bg-card text-card-foreground shadow-sm", className)}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("flex items-center justify-between gap-2 p-4", className)} {...props} />
  );
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("text-sm font-semibold tracking-tight", className)} {...props} />;
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-4 pt-0", className)} {...props} />;
}

/* ------------------------------------------------------------------------ Button */

type ButtonVariant = "default" | "outline" | "ghost" | "destructive" | "success" | "secondary";
type ButtonSize = "default" | "sm" | "xs" | "icon";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  default: "bg-primary text-primary-foreground hover:opacity-90",
  outline: "border bg-card hover:bg-accent",
  ghost: "hover:bg-accent",
  destructive: "bg-destructive text-destructive-foreground hover:opacity-90",
  success: "bg-success text-success-foreground hover:opacity-90",
  secondary: "bg-secondary text-secondary-foreground hover:opacity-90",
};

const BUTTON_SIZES: Record<ButtonSize, string> = {
  default: "h-8 px-3.5 text-sm",
  sm: "h-7 px-3 text-xs",
  xs: "h-6 px-2 text-[0.7rem]",
  icon: "h-8 w-8",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = "default", size = "default", type = "button", ...props },
  ref
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-medium",
        "transition-opacity focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        "disabled:pointer-events-none disabled:opacity-45",
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className
      )}
      {...props}
    />
  );
});

/* ------------------------------------------------------------------------- Badge */

type BadgeTone =
  | "default"
  | "muted"
  | "outline"
  | "success"
  | "destructive"
  | "warn"
  | "info"
  | "solid-success"
  | "solid-destructive";

const BADGE_TONES: Record<BadgeTone, string> = {
  default: "bg-primary text-primary-foreground",
  muted: "bg-muted text-muted-foreground",
  outline: "border text-foreground",
  success: "bg-success/15 text-success",
  destructive: "bg-destructive/15 text-destructive",
  warn: "bg-warn/20 text-warn",
  info: "bg-info/15 text-info",
  "solid-success": "bg-success text-success-foreground",
  "solid-destructive": "bg-destructive text-destructive-foreground",
};

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
}

export function Badge({ className, tone = "default", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5",
        "text-[0.6875rem] font-semibold",
        BADGE_TONES[tone],
        className
      )}
      {...props}
    />
  );
}

/* ------------------------------------------------------------------------- Input */

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(function Input({ className, ...props }, ref) {
  return (
    <input
      ref={ref}
      className={cn(
        "h-8 w-full rounded-md border border-input bg-card px-2.5 text-sm",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  );
});

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...props }, ref) {
  return (
    <textarea
      ref={ref}
      className={cn(
        "min-h-[4.5rem] w-full rounded-md border border-input bg-card px-2.5 py-2 text-sm",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className
      )}
      {...props}
    />
  );
});

export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(function Select({ className, ...props }, ref) {
  return (
    <select
      ref={ref}
      className={cn(
        "h-8 rounded-md border border-input bg-card px-2 text-sm",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className
      )}
      {...props}
    />
  );
});

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("text-xs font-medium", className)} {...props} />;
}

/* ------------------------------------------------------------------------- Table */

export function Table({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn("w-full border-collapse text-sm", className)} {...props} />
    </div>
  );
}

export function TH({ className, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        "border-b px-2 py-1.5 text-left text-[0.6875rem] font-semibold uppercase",
        "tracking-wide text-muted-foreground",
        className
      )}
      {...props}
    />
  );
}

export function TD({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("border-b px-2 py-2 align-middle", className)} {...props} />;
}

export function TR({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn("hover:bg-accent/40", className)} {...props} />;
}

/* ------------------------------------------------------------------- Page header */

export interface PageHeaderProps {
  /** A node rather than a string so a page can put a tag beside its name. */
  title: React.ReactNode;
  description?: string;
  action?: React.ReactNode;
  breadcrumb?: React.ReactNode;
}

export function PageHeader({ title, description, action, breadcrumb }: PageHeaderProps) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        {breadcrumb ? <div className="mb-1 text-xs text-muted-foreground">{breadcrumb}</div> : null}
        <h1 className="flex flex-wrap items-center gap-2 text-xl font-semibold tracking-tight">
          {title}
        </h1>
        {description ? (
          <p className="mt-0.5 max-w-3xl text-xs text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {action ? <div className="flex flex-wrap items-center gap-2">{action}</div> : null}
    </div>
  );
}

/* ------------------------------------------------------------------ Status states */

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} />;
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="py-12 text-center">
      <p className="text-sm font-medium">{title}</p>
      {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Card className="border-destructive/40 bg-destructive/5">
      <CardContent className="flex items-center justify-between gap-3 p-4">
        <p className="text-sm text-destructive">{message}</p>
        {onRetry ? (
          <Button variant="outline" size="sm" onClick={onRetry}>
            Try again
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------------ Stat */

export interface StatProps {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: "default" | "success" | "destructive" | "warn" | "info" | "muted";
}

const STAT_TONES: Record<NonNullable<StatProps["tone"]>, string> = {
  default: "",
  success: "text-success",
  destructive: "text-destructive",
  warn: "text-warn",
  info: "text-info",
  muted: "text-muted-foreground",
};

export function Stat({ label, value, hint, tone = "default" }: StatProps) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-[0.6875rem] font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </div>
        <div className={cn("mt-1.5 text-2xl font-semibold tabular-nums", STAT_TONES[tone])}>
          {value}
        </div>
        {hint ? <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div> : null}
      </CardContent>
    </Card>
  );
}
