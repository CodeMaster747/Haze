import type { ReactNode } from 'react';

interface PanelProps {
  title?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Panel({ title, right, children, className = '' }: PanelProps) {
  return (
    <section
      className={`rounded-lg border border-border-subtle bg-bg-panel/70 backdrop-blur-sm ${className}`}
    >
      {(title || right) && (
        <header className="flex items-center justify-between border-b border-border-subtle px-4 py-2.5">
          {title && (
            <h2 className="font-mono text-[11px] uppercase tracking-[0.14em] text-text-muted">
              {title}
            </h2>
          )}
          {right}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}
