type BadgeVariant = "success" | "warning" | "neutral" | "danger" | "info";

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  success: "bg-green-50 text-green-700",
  warning: "bg-amber-50 text-amber-700",
  neutral: "bg-muted text-muted-foreground",
  danger: "bg-red-50 text-destructive",
  info: "bg-blue-50 text-blue-700",
};

export default function Badge({
  variant,
  children,
}: {
  variant: BadgeVariant;
  children: React.ReactNode;
}) {
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs ${VARIANT_CLASSES[variant]}`}>
      {children}
    </span>
  );
}
