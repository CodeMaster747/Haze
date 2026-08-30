import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

/** The state a panel is in most of the time on a fresh install.
 *
 *  Says what is absent and what to do about it, in that order, at the same
 *  size in every panel — rather than a differently-padded line of muted text
 *  per panel, which is what this replaced.
 */
export function EmptyState({
  icon: Icon,
  title,
  hint,
  action,
}: {
  icon?: LucideIcon;
  title: string;
  hint?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center px-4 py-8 text-center">
      {Icon && (
        <Icon
          size={16}
          strokeWidth={1.75}
          aria-hidden
          className="mb-3 text-text-dim"
        />
      )}
      <p className="text-sm text-text-secondary">{title}</p>
      {hint && <p className="mt-1.5 max-w-sm text-xs leading-relaxed text-text-muted">{hint}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
