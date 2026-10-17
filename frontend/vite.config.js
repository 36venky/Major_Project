import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [react(), tailwindcss()],

  resolve: {
    alias: {
      // Redirect Plotly to the installed distribution
      'plotly.js/dist/plotly': path.resolve(
        __dirname,
        'node_modules/plotly.js-dist/plotly.js'
      ),
    },
  },

  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
  },

  build: {
    chunkSizeWarningLimit: 1500,
  },
})