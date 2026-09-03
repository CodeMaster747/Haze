import { Loader2, type LucideIcon } from 'lucide-react';
import type { ButtonHTMLAttributes } from 'react';

import { CONTROL_HEIGHT, type Size } from '@/components/ui/controlSize';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';

/** The application's only button.
 *
 *  Before this existed there were six hand-rolled ones with four heights and
 *  three radii, and icons positioned with `className="inline"` — which puts a
 *  glyph on the text baseline rather than on the button's optical centre. The
 *  fix is structural: fixed heights per size, one radius, and the icon is a
 *  flex child with a defined gap, so it cannot drift.
 */
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  /** Leading icon. Pass the component, not an element — the size is ours. */
  icon?: LucideIcon;
  /** Replaces the icon with a spinner and blocks the click. */
  loading?: boolean;
  /** Square button with no label. `aria-label` becomes required in practice. */
  iconOnly?: boolean;
  /** Selected state for the segmented speed control. */
  active?: boolean;
}

const VARIANTS: Record<Variant, string> = {
  // The one high-contrast surface in the app. Reserved for the single primary
  // action of a panel, so that "what do I do here" is answerable at a glance.
  // `solid` rather than the accent because the two themes disagree about which
  // colour that is — see the token's note in index.css.
  primary:
    'bg-solid text-solid-fg font-medium border border-transparent enabled:hover:bg-solid-hover enabled:active:bg-solid',
  secondary:
    'bg-bg-elevated text-text-secondary border border-border enabled:hover:bg-bg-tertiary enabled:hover:text-text-primary enabled:hover:border-border-strong enabled:active:bg-bg-tertiary',
  ghost:
    'bg-transparent text-text-muted border border-transparent enabled:hover:bg-bg-hover enabled:hover:text-text-primary enabled:active:bg-bg-active',
  danger:
    'bg-transparent text-text-muted border border-border enabled:hover:border-state-error/50 enabled:hover:text-state-error enabled:hover:bg-state-error/5',
};

const SIZES: Record<Size, { box: string; square: string; text: string; icon: number }> = {
  sm: { box: 'px-2.5 gap-1.5', square: 'w-7', text: 'text-xs', icon: 12 },
  md: { box: 'px-3 gap-1.5', square: 'w-8', text: 'text-sm', icon: 14 },
  lg: { box: 'px-4 gap-2', square: 'w-9', text: 'text-sm', icon: 14 },
  xl: { box: 'px-5 gap-2', square: 'w-11', text: 'text-base', icon: 16 },
};

export function Button({
  variant = 'secondary',
  size = 'md',
  icon: Icon,
  loading = false,
  iconOnly = false,
  active = false,
  disabled,
  className = '',
  children,
  type = 'button',
  ...rest
}: ButtonProps) {
  const s = SIZES[size];
  const Glyph = loading ? Loader2 : Icon;

  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={[
        'inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap rounded-md',
        'transition-colors ease-out-quart',
        'disabled:cursor-not-allowed disabled:opacity-40',
        CONTROL_HEIGHT[size],
        iconOnly ? s.square : s.box,
        s.text,
        active
          ? 'border border-accent-primary/45 bg-accent-subtle text-accent-primary'
          : VARIANTS[variant],
        className,
      ].join(' ')}
      {...rest}
    >
      {Glyph && (
        <Glyph
          size={s.icon}
          strokeWidth={2}
          aria-hidden
          className={loading ? 'animate-spin' : undefined}
        />
      )}
      {!iconOnly && children}
    </button>
  );
}
