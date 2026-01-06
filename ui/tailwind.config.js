/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        "forest-green": "#348C41",
        "dark-green": "#2a7034",
        "baystate-burgundy": "#66161D",
        "harvest-gold": "#FCD048",
      },
    },
  },
  plugins: [],
};
