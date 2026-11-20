import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// GitHub Pages serves the site from /<repo>/; override with BASE=/ for local or other hosts.
export default defineConfig({
  plugins: [react()],
  base: process.env.BASE ?? '/SENATE_PREDICTION_TOOL/',
  // three.js ships as its own lazy chunk (about 145 kB gzipped).
  build: { chunkSizeWarningLimit: 700 },
})
