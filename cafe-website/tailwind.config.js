/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  // Safelist ensures custom theme classes are never purged
  safelist: [
    'bg-cream', 'bg-beige', 'bg-forest', 'bg-charcoal', 'bg-brass', 'bg-white',
    'text-cream', 'text-beige', 'text-forest', 'text-charcoal', 'text-brass', 'text-brass-light',
    'border-brass', 'border-beige', 'border-forest', 'border-charcoal',
    'hover:bg-forest', 'hover:text-brass', 'hover:text-cream', 'hover:border-brass',
    'hover:bg-brass-light', 'hover:bg-brass',
    'from-charcoal', 'via-charcoal', 'to-charcoal',
    'section-divider', 'menu-card', 'leadlight-strip',
  ],
  theme: {
    extend: {
      colors: {
        cream: "#FAFAF7",
        beige: "#F0EBE1",
        forest: "#2D5016",
        "forest-dark": "#1E3A0F",
        charcoal: "#141414",
        brass: "#B8901C",
        "brass-light": "#D4A82A",
        mist: "#7A746E",
      },
      fontFamily: {
        serif: ["Playfair Display", "Georgia", "serif"],
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      backgroundImage: {
        "leadlight-gradient":
          "linear-gradient(135deg, #2D5016 0%, #D4AF37 50%, #2D5016 100%)",
      },
    },
  },
  plugins: [],
};
