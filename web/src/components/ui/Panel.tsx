import type { ReactNode } from 'react';

interface PanelProps {
  title?: ReactNode;
  /** One line under the title. Use for what the panel is, not how to use it. */
  description?: string;
  right?: ReactNode;
  children: ReactNode;
  /** Drops the body padding, for content that wants to reach the panel edge. */
  flush?: boolean;
  className?: string;
}

/** A grouped section.
 *
 *  Solid, single-hairline, no blur and no shadow. The previous version was a
 *  translucent surface with a backdrop filter over a tinted page — which is
 *  the glassmorphism look, and it made every panel edge read as a different
 *  grey depending on what happened to be behind it.
 */
export function Panel({
  title,
  description,
  right,
  children,
  flush = false,
  className = '',
}: PanelProps) {
  const labelled = title !== undefined && title !== null;

  return (
    <section
      className={`overflow-hidden rounded-lg border border-border-subtle bg-bg-panel ${className}`}
    >
      {(labelled || right) && (
        <header className="flex min-h-11 items-center justify-between gap-3 border-b border-border-subtle px-4 py-2.5">
          <div className="min-w-0">
            {labelled && (
              <h2 className="truncate text-sm font-medium text-text-primary">{title}</h2>
            )}
            {description && (
              <p className="mt-0.5 truncate text-xs text-text-muted">{description}</p>
            )}
          </div>
          {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
        </header>
      )}
      <div className={flush ? '' : 'p-4'}>{children}</div>
    </section>
  );
}
