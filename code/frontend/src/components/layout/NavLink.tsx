import { cn } from "../../lib/utils";

// ─── NavLink ─────────────────────────────────────────────────────────────────

interface NavLinkProps {
  label: string;
  icon: string;
  active: boolean;
  disabled?: boolean;
  badge?: string;
  onClick: () => void;
}

export function NavLink({ label, icon, active, disabled, badge, onClick }: NavLinkProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition-colors",
        active
          ? "bg-violet-50 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300"
          : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800",
        disabled && "cursor-not-allowed opacity-40"
      )}
    >
      <span className="text-base leading-none">{icon}</span>
      <span className="flex-1">{label}</span>
      {badge && (
        <span className="rounded-full bg-zinc-200 px-1.5 py-0.5 text-[10px] text-zinc-500 dark:bg-zinc-700">
          {badge}
        </span>
      )}
    </button>
  );
}