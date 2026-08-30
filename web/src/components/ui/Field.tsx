import { ChevronDown } from 'lucide-react';
import { useId } from 'react';
import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react';

/** Form controls.
 *
 *  One height, one radius, one focus treatment. The focus state is a 1px
 *  border shift plus a 2px low-opacity ring — visible from across the room,
 *  but not the glow that a 4px accent halo would be.
 */
const CONTROL = [
  'h-8 w-full min-w-0 rounded-md border border-border bg-bg-tertiary px-2.5',
  'text-sm text-text-primary transition-colors ease-out-quart',
  'placeholder:text-text-dim',
  'hover:border-border-strong',
  'focus:border-accent-primary/70 focus:outline-none focus:ring-2 focus:ring-accent-primary/20',
  'disabled:cursor-not-allowed disabled:opacity-45',
].join(' ');

interface FieldProps {
  label: string;
  /** Hides the label visually but keeps it for screen readers. For controls
   *  whose purpose is already obvious from an adjacent placeholder. */
  hideLabel?: boolean;
  className?: string;
  children: (id: string) => ReactNode;
}

/** Label plus control, wired together.
 *
 *  Takes a render prop so the generated id reaches the control it labels and
 *  cannot drift. Deliberately carries no error slot: this application reports
 *  every failure through Callout, and a second inline error style would be a
 *  second thing to keep consistent — as well as changing the row height and
 *  dragging the submit button out of alignment with the input.
 */
export function Field({ label, hideLabel = false, className = '', children }: FieldProps) {
  const id = useId();

  return (
    <div className={`flex min-w-0 flex-col gap-1.5 ${className}`}>
      <label
        htmlFor={id}
        className={hideLabel ? 'sr-only' : 'text-xs font-medium text-text-secondary'}
      >
        {label}
      </label>
      {children(id)}
    </div>
  );
}

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Renders values that are addresses, ids or counts in the mono face. */
  mono?: boolean;
  invalid?: boolean;
}

export function Input({ mono = false, invalid = false, className = '', ...rest }: InputProps) {
  return (
    <input
      aria-invalid={invalid || undefined}
      className={[
        CONTROL,
        mono ? 'font-mono' : '',
        invalid ? 'border-state-error/60 focus:border-state-error focus:ring-state-error/20' : '',
        className,
      ].join(' ')}
      {...rest}
    />
  );
}

export function Select({
  className = '',
  children,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative min-w-0">
      <select
        className={`${CONTROL} cursor-pointer appearance-none pr-8 ${className}`}
        {...rest}
      >
        {children}
      </select>
      <ChevronDown
        size={14}
        aria-hidden
        className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted"
      />
    </div>
  );
}
