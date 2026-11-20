import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// GitHub Pages serves the site from /<repo>/; override with BASE=/ for local or other hosts.
export default defineConfig({
  plugins: [react()],
  base: process.env.BASE ?? '/SENATE_PREDICTION_TOOL/',
})
