/** Loading placeholders.
 *
 *  Used only where the shape of what is arriving is known — the node grid on
 *  first connect. Anywhere the payload could be empty, an empty state is the
 *  honest thing to render instead of a skeleton that resolves to nothing.
 */
export function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={`relative overflow-hidden rounded bg-bg-tertiary ${className}`}
    >
      <div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-white/[0.045] to-transparent" />
    </div>
  );
}
