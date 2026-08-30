/** @type {import('tailwindcss').Config} */
// Same token structure as Tracer (bg/text/accent/border scales rather than raw
// palette colours) so the two projects stay visually related and a component
// lifted from one drops into the other. The accent differs deliberately:
// Tracer is violet, Haze is cyan.
//
// Everything a component needs to look like it belongs here is a token in this
// file. If a component reaches for an arbitrary value — text-[13px], a hex
// colour, rounded-[9px] — that is a gap in this file, not a licence to
// improvise.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: {
          primary: '#0a0c0e',
          secondary: '#0f1214',
          tertiary: '#14181b',
          panel: '#131719',
          elevated: '#1a1f23',
          // Interaction surfaces. Expressed as white overlays rather than
          // fixed greys so the same hover reads correctly on any of the
          // surfaces above it.
          hover: 'rgba(255, 255, 255, 0.04)',
          active: 'rgba(255, 255, 255, 0.07)',
        },
        // Four tiers, and 0.50 is the floor. Against the panel surface an
        // alpha below ~0.49 drops under 4.5:1, and every one of these tiers
        // carries real information at 11-13px — the hierarchy is made by size
        // and weight, not by fading text out of legibility.
        //   primary 16.6:1 · secondary 8.8:1 · muted 5.9:1 · dim 4.7:1
        text: {
          primary: '#eef2f4',
          secondary: 'rgba(238, 242, 244, 0.74)',
          muted: 'rgba(238, 242, 244, 0.58)',
          dim: 'rgba(238, 242, 244, 0.50)',
        },
        accent: {
          primary: '#38bdc9',
          secondary: '#7fdde5',
          hover: '#4fcbd6',
          subtle: 'rgba(56, 189, 201, 0.10)',
        },
        // Node and job state. Named by meaning, not colour, so the status of a
        // node is a data property the UI maps rather than a class name a
        // component hardcodes.
        state: {
          online: '#3fb950',
          busy: '#d29922',
          offline: '#6e7681',
          error: '#f85149',
          simulated: '#a371f7',
        },
        border: {
          subtle: 'rgba(255, 255, 255, 0.06)',
          DEFAULT: 'rgba(255, 255, 255, 0.11)',
          strong: 'rgba(255, 255, 255, 0.18)',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'Menlo', 'monospace'],
      },
      letterSpacing: {
        // Mono uppercase labels. Caps at 11px close up into a solid bar
        // without this, and it had been improvised at three different values.
        label: '0.14em',
        // The pairing code, which two people read to each other across a room.
        // Wide enough that a digit is its own object rather than part of a
        // six-digit blob.
        digits: '0.22em',
      },
      fontSize: {
        // 11px is the floor. Below that the interface stops being readable and
        // starts being texture, and this UI had drifted to 10px in places.
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
        xs: ['0.75rem', { lineHeight: '1.125rem' }],
        sm: ['0.8125rem', { lineHeight: '1.25rem' }],
        base: ['0.875rem', { lineHeight: '1.375rem' }],
        lg: ['1rem', { lineHeight: '1.5rem' }],
        xl: ['1.125rem', { lineHeight: '1.625rem' }],
        '2xl': ['1.375rem', { lineHeight: '1.875rem' }],
        '3xl': ['1.75rem', { lineHeight: '2.25rem' }],
        // Display sizes. The dashboard never goes above 3xl; the public
        // landing page needs two steps beyond it, and negative tracking
        // because Inter opens up noticeably at display sizes.
        '4xl': ['2.25rem', { lineHeight: '2.625rem', letterSpacing: '-0.02em' }],
        '5xl': ['3rem', { lineHeight: '3.25rem', letterSpacing: '-0.025em' }],
      },
      // A radius scale by component size, not one value everywhere: a 20px
      // status chip and a 640px dialog do not want the same corner.
      borderRadius: {
        sm: '0.25rem', // 4px  — micro marks (per-core cells)
        DEFAULT: '0.375rem', // 6px  — chips, badges, inline code
        md: '0.5rem', // 8px  — buttons, inputs, selects
        lg: '0.625rem', // 10px — panels, list cards
        xl: '0.875rem', // 14px — dialogs
      },
      boxShadow: {
        // Depth is used twice in this app: to lift a dialog off the page, and
        // to lift a sticky header off content scrolling under it. Nothing else
        // gets a shadow.
        modal: '0 24px 64px -16px rgba(0, 0, 0, 0.72), 0 0 0 1px rgba(255, 255, 255, 0.05)',
        header: '0 1px 0 0 rgba(255, 255, 255, 0.06)',
      },
      transitionTimingFunction: { 'out-quart': 'cubic-bezier(0.25, 1, 0.5, 1)' },
      transitionDuration: { DEFAULT: '150ms' },
      keyframes: {
        'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        'dialog-in': {
          from: { opacity: '0', transform: 'translateY(4px) scale(0.99)' },
          to: { opacity: '1', transform: 'none' },
        },
        shimmer: { '100%': { transform: 'translateX(100%)' } },
      },
      animation: {
        'fade-in': 'fade-in 160ms cubic-bezier(0.25, 1, 0.5, 1)',
        'dialog-in': 'dialog-in 180ms cubic-bezier(0.25, 1, 0.5, 1)',
        'pulse-slow': 'pulse 2.6s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        shimmer: 'shimmer 1.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
