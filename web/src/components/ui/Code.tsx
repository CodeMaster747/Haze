import type { ReactNode } from 'react';

/** Inline literal — a path, a flag, an address. */
export function Code({ children }: { children: ReactNode }) {
  return (
    <code className="rounded border border-border-subtle bg-bg-tertiary px-1 py-px font-mono text-[0.9em] text-text-secondary">
      {children}
    </code>
  );
}

/** A block of shell the reader is expected to copy.
 *
 *  Same surface as an input, because that is what it is: a thing you take
 *  text out of. Scrolls rather than wraps — a wrapped shell line is a
 *  different command.
 */
export function CodeBlock({ children }: { children: ReactNode }) {
  return (
    <pre className="overflow-x-auto rounded-md border border-border-subtle bg-bg-tertiary px-3 py-2.5 font-mono text-xs leading-relaxed text-text-primary">
      <code>{children}</code>
    </pre>
  );
}
