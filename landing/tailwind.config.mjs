/** @type {import('tailwindcss').Config} */
export default {
  content: ["./src/**/*.{astro,tsx,ts,jsx,js}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#9b75d9",
          50: "#f5f2fd",
          100: "#ebe5fb",
          200: "#d7ccf7",
          300: "#c3b2f3",
          400: "#9b75d9",
          500: "#865ed2",
          600: "#7b46cb",
          700: "#6a39b3",
          800: "#5a3196",
          900: "#49287a",
        },
      },
      fontFamily: {
        mono: ['"Hack Nerd Font Mono"', '"Hack Nerd Font"', '"Droid Sans Mono"', "monospace"],
        sans: ['"Hack Nerd Font Mono"', '"Hack Nerd Font"', '"Droid Sans Mono"', "monospace"],
      },
    },
  },
  plugins: [],
};
