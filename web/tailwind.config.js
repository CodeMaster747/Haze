/** @type {import('tailwindcss').Config} */
// Same token structure as Tracer (bg/text/accent/border scales rather than raw
// palette colours) so the two projects stay visually related and a component
// lifted from one drops into the other. The accent differs deliberately:
// Tracer is violet, Haze is cyan.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: {
          primary: '#0a0c0e',
          secondary: '#0f1214',
          tertiary: '#14181b',
          panel: '#181d21',
          elevated: '#1e242a',
        },
        text: {
          primary: '#eef2f4',
          secondary: 'rgba(238, 242, 244, 0.66)',
          muted: 'rgba(238, 242, 244, 0.44)',
          dim: 'rgba(238, 242, 244, 0.28)',
        },
        accent: {
          primary: '#38bdc9',
          secondary: '#5fd4de',
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
          subtle: 'rgba(255, 255, 255, 0.055)',
          DEFAULT: 'rgba(255, 255, 255, 0.10)',
          strong: 'rgba(255, 255, 255, 0.17)',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'Menlo', 'monospace'],
      },
      borderRadius: { DEFAULT: '0.5rem' },
      transitionTimingFunction: { 'out-quart': 'cubic-bezier(0.25, 1, 0.5, 1)' },
      transitionDuration: { DEFAULT: '150ms' },
      keyframes: {
        'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
      },
      animation: {
        'fade-in': 'fade-in 200ms cubic-bezier(0.25, 1, 0.5, 1)',
        'pulse-slow': 'pulse 2.6s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
};
