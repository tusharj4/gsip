import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50:  "#f0f4ff",
          100: "#d9e4ff",
          500: "#2d5fa6",
          700: "#1a3a6e",
          900: "#0d1e3a",
        },
        severity: {
          blocker: "#ff4d4d",
          high:    "#ff9933",
          medium:  "#ffcc00",
          low:     "#90ee90",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
