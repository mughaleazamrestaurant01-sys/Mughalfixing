/**
 * Tailwind build config for the POS interface.
 *
 * The app previously loaded the Tailwind "Play CDN" (assets/js/tailwindcss.js) which
 * compiled CSS inside the browser on every launch and re-compiled on every DOM change.
 * That is a development-only tool and was the main cause of the window freezing when
 * it was clicked right after opening. The stylesheet is now generated ONCE into
 * assets/css/tailwind.css with:
 *
 *     ./build-css.sh          (Linux / macOS / Git-Bash)
 *     build-css.cmd           (Windows)
 *
 * Re-run it whenever you add new Tailwind classes to index.html.
 */
module.exports = {
  content: ['./index.html'],
  theme: {
    extend: {
      colors: {
        neu: {
          bg: '#1e2026', dark: '#141519', light: '#282b33',
          accent: '#ff4d5a', accentHover: '#ff3344',
          text: '#e1e7ed', muted: '#7b8392',
          emerald: '#10b981', amber: '#f59e0b',
          blue: '#3b82f6', purple: '#8b5cf6',
        },
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        royal: ['Cinzel', 'serif'],
      },
    },
  },
  plugins: [],
};
