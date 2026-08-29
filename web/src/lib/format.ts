/** Display formatting. Kept together so units are consistent everywhere. */

const UNITS = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'] as const;

/** Binary bytes. Deliberately IEC (GiB, 1024-based) rather than decimal GB:
 *  it matches what psutil reports and what the OS shows, so a user comparing
 *  Haze against Activity Monitor sees the same number. */
export function bytes(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return '—';
  let n = value;
  let unit = 0;
  while (n >= 1024 && unit < UNITS.length - 1) {
    n /= 1024;
    unit += 1;
  }
  return `${n.toFixed(unit === 0 ? 0 : digits)} ${UNITS[unit]}`;
}

export function percent(value: number | null | undefined, digits = 0): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${value.toFixed(digits)}%`;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—';
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  const h = Math.floor(s / 3600);
  return `${h}h ${Math.floor((s % 3600) / 60)}m`;
}

/** Colour for a utilisation meter. Thresholds, not a gradient: a meter that
 *  shifts hue continuously reads as decorative, whereas three states read as
 *  information. */
export function loadTone(pct: number): 'ok' | 'warn' | 'high' {
  if (pct >= 85) return 'high';
  if (pct >= 60) return 'warn';
  return 'ok';
}
