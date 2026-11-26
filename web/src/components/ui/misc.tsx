import * as React from "react";
import { Tooltip as TooltipPrimitive, Progress as ProgressPrimitive, Separator as SeparatorPrimitive } from "radix-ui";
import { cn } from "@/lib/utils";

export function Tooltip({ content, children, side = "top" }: { content: React.ReactNode; children: React.ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  return (
    <TooltipPrimitive.Root delayDuration={250}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={6}
          className="z-50 max-w-xs rounded-md bg-foreground px-2.5 py-1.5 text-xs text-background shadow-md"
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
export const TooltipProvider = TooltipPrimitive.Provider;

export function Progress({ className, value, indicatorClassName, ...props }: React.ComponentProps<typeof ProgressPrimitive.Root> & { indicatorClassName?: string }) {
  return (
    <ProgressPrimitive.Root className={cn("relative h-2 w-full overflow-hidden rounded-full bg-muted", className)} value={value} {...props}>
      <ProgressPrimitive.Indicator
        className={cn("h-full bg-primary transition-all duration-500", indicatorClassName)}
        style={{ width: `${Math.max(0, Math.min(100, value ?? 0))}%` }}
      />
    </ProgressPrimitive.Root>
  );
}

export function Separator({ className, orientation = "horizontal", ...props }: React.ComponentProps<typeof SeparatorPrimitive.Root>) {
  return (
    <SeparatorPrimitive.Root
      orientation={orientation}
      className={cn("shrink-0 bg-border", orientation === "horizontal" ? "h-px w-full" : "h-full w-px", className)}
      {...props}
    />
  );
}

export function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} {...props} />;
}

export function Alert({ className, variant = "default", ...props }: React.ComponentProps<"div"> & { variant?: "default" | "warning" | "destructive" | "info" }) {
  const styles = {
    default: "bg-card",
    info: "border-primary/30 bg-accent/60 text-accent-foreground",
    warning: "border-partial/40 bg-partial/10",
    destructive: "border-destructive/40 bg-destructive/10 text-destructive",
  }[variant];
  return <div role="alert" className={cn("flex gap-3 rounded-lg border p-4 text-sm [&>svg]:size-4 [&>svg]:mt-0.5 [&>svg]:shrink-0", styles, className)} {...props} />;
}

export function Kbd({ className, ...props }: React.ComponentProps<"kbd">) {
  return <kbd className={cn("rounded border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground", className)} {...props} />;
}
