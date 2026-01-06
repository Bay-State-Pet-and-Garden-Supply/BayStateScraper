/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        forest: {
          50: "#f0fdf4",
          100: "#dcfce7",
          200: "#bbf7d0",
          300: "#86efac",
          400: "#4ade80",
          500: "#008850", // Primary
          600: "#007a48",
          700: "#006c3f",
          800: "#005a35",
          900: "#004d2d",
        },
        "forest-green": "#008850",
        "dark-green": "#006c3f",
        "baystate-burgundy": "#66161D",
        "harvest-gold": "#FCD048",
      },
    },
  },
  plugins: [],
};
