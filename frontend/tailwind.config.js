/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0b0e13",
        panel: "#11161d",
        panel2: "#161c25",
        line: "#232b37",
        ink: "#d7dde6",
        mute: "#8592a3",
        dim: "#5b6676",
        accent: "#f2a93b",
        up: "#3fb97f",
        down: "#e5615b",
        info: "#5aa9e6",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "SFMono-Regular", "monospace"],
      },
    },
  },
  plugins: [],
};
