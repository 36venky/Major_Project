import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      // react-plotly.js looks for 'plotly.js/dist/plotly' — point it to plotly.js-dist
      'plotly.js/dist/plotly': path.resolve(
        __dirname,
        'node_modules/plotly.js-dist/plotly.js'
      ),
    },
  },
  server: {
    allowedHosts: true,  // allow all hosts including ngrok tunnels
  },
  build: {
    chunkSizeWarningLimit: 1500,  // plotly is large; suppress noise
  },
})
