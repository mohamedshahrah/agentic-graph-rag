/** @type {import('tailwindcss').Config} */

// Colors are CSS variables (defined in index.css) rather than literal values,
// so light and dark are one set of class names with two sets of values —
// components never branch on theme.
const withVar = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        canvas: withVar("canvas"),
        surface: withVar("surface"),
        raised: withVar("raised"),
        border: withVar("border"),
        strong: withVar("text-strong"),
        body: withVar("text-body"),
        muted: withVar("text-muted"),
        accent: {
          DEFAULT: withVar("accent"),
          soft: withVar("accent-soft"),
          text: withVar("accent-text"),
        },
        positive: withVar("positive"),
        caution: withVar("caution"),
        danger: withVar("danger"),
      },
      fontFamily: {
        sans: ["Inter Variable", "Inter", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      borderRadius: { md: "8px", lg: "12px", xl: "16px" },
      boxShadow: {
        // Low-contrast, large-radius shadows: enough to lift a surface without
        // the heavy drop shadows that date an interface.
        card: "0 1px 2px rgb(0 0 0 / 0.04), 0 1px 3px rgb(0 0 0 / 0.06)",
        pop: "0 4px 12px rgb(0 0 0 / 0.08), 0 12px 32px rgb(0 0 0 / 0.10)",
      },
      keyframes: {
        "fade-in": { from: { opacity: 0 }, to: { opacity: 1 } },
        "slide-up": {
          from: { opacity: 0, transform: "translateY(4px)" },
          to: { opacity: 1, transform: "translateY(0)" },
        },
        shimmer: { "100%": { transform: "translateX(100%)" } },
      },
      animation: {
        "fade-in": "fade-in 150ms ease-out",
        "slide-up": "slide-up 200ms ease-out",
        shimmer: "shimmer 1.6s infinite",
      },
    },
  },
  plugins: [],
};
