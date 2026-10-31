import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// During development, requests to /api are forwarded to the backend
// (e.g. FastAPI on :8000) so the browser never hits CORS issues.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: env.VITE_BACKEND_URL || 'http://localhost:8000',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''), // backend routes have no /api prefix
          // staff-only endpoints need the admin key; adding it here keeps it out of the browser bundle
          headers: { 'X-Admin-Key': env.ADMIN_KEY || '' },
        },
      },
    },
  };
});
