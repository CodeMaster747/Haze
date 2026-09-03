/** @type {import('tailwindcss').Config} */
// Same token structure as Tracer (bg/text/accent/border scales rather than raw
// palette colours) so the two projects stay visually related and a component
// lifted from one drops into the other.
//
// Everything a component needs to look like it belongs here is a token in this
// file. If a component reaches for an arbitrary value — text-[13px], a hex
// colour, rounded-[9px] — that is a gap in this file, not a licence to
// improvise.
//
// **Colours are indirected through CSS variables** and the values themselves
// live in index.css, because there are now two palettes: the dashboard's dark
// one and the public site's paper one. A component never picks a palette — it
// names `bg-bg-panel` and gets whichever is in scope. The landing page sets
// `data-theme="paper"` on its root and nothing else in the tree knows.
//
// Two spellings appear below. A token used with an opacity modifier anywhere
// (`bg-accent-primary/25`) MUST be `rgb(var(--x) / <alpha-value>)`, and its
// variable is three space-separated channels. Everything else is a plain
// `var(--x)`, which lets those tokens stay genuinely translucent — the
// hover/border overlays depend on that, and baking them to solids would break
// the one property they exist to have.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: {
          primary: 'rgb(var(--bg-primary) / <alpha-value>)',
          secondary: 'var(--bg-secondary)',
          tertiary: 'rgb(var(--bg-tertiary) / <alpha-value>)',
          panel: 'var(--bg-panel)',
          elevated: 'var(--bg-elevated)',
          // Interaction surfaces. Expressed as overlays rather than fixed
          // greys so the same hover reads correctly on any of the surfaces
          // above it — and so one rule inverts for the paper theme.
          hover: 'var(--bg-hover)',
          active: 'var(--bg-active)',
        },
        // Four tiers, and every one of them clears 4.5:1 against its own
        // theme's page surface. These carry real information at 11-13px — the
        // hierarchy is made by size and weight, not by fading text out of
        // legibility. Measured ratios are in index.css beside the values.
        text: {
          primary: 'var(--text-primary)',
          secondary: 'var(--text-secondary)',
          muted: 'var(--text-muted)',
          dim: 'var(--text-dim)',
        },
        accent: {
          primary: 'rgb(var(--accent-primary) / <alpha-value>)',
          secondary: 'var(--accent-secondary)',
          hover: 'var(--accent-hover)',
          subtle: 'var(--accent-subtle)',
        },
        // The one high-contrast action surface, split out from `accent`
        // because the two themes disagree about what it should be: on the
        // dashboard the accent itself is the loudest thing available, while on
        // paper a rust button would read as a warning and ink does not.
        solid: {
          DEFAULT: 'var(--solid)',
          hover: 'var(--solid-hover)',
          fg: 'var(--solid-fg)',
        },
        // Node and job state. Named by meaning, not colour, so the status of a
        // node is a data property the UI maps rather than a class name a
        // component hardcodes.
        state: {
          online: 'rgb(var(--state-online) / <alpha-value>)',
          busy: 'rgb(var(--state-busy) / <alpha-value>)',
          offline: 'rgb(var(--state-offline) / <alpha-value>)',
          error: 'rgb(var(--state-error) / <alpha-value>)',
          simulated: 'rgb(var(--state-simulated) / <alpha-value>)',
        },
        border: {
          subtle: 'var(--border-subtle)',
          DEFAULT: 'var(--border-default)',
          strong: 'var(--border-strong)',
        },
      },
      fontFamily: {
        // IBM Plex rather than Inter: Inter is the default voice of every
        // generated interface, and Plex has an engineering provenance this
        // product can borrow. Sans and mono are the same superfamily, so
        // hostnames in a table line up with the prose around them.
        sans: ['IBM Plex Sans', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['IBM Plex Mono', 'ui-monospace', 'Menlo', 'monospace'],
        // Display only, and only on the public site. Newsreader gives the
        // landing page a voice the dashboard deliberately does not have.
        display: ['Newsreader', 'Georgia', 'Times New Roman', 'serif'],
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
        // landing page needs three steps beyond it. Negative tracking because
        // Newsreader, like most serifs, opens up at display sizes.
        '4xl': ['2.25rem', { lineHeight: '2.5rem', letterSpacing: '-0.012em' }],
        '5xl': ['3rem', { lineHeight: '3.15rem', letterSpacing: '-0.016em' }],
        '6xl': ['4.375rem', { lineHeight: '1.04', letterSpacing: '-0.018em' }],
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
        modal: '0 24px 64px -16px var(--shadow-modal), 0 0 0 1px var(--border-subtle)',
        header: '0 1px 0 0 var(--border-subtle)',
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
