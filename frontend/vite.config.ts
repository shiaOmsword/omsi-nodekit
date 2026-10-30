import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'NODEKIT_');
  return {
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: Number(env.NODEKIT_FRONTEND_DEV_PORT || 5173),
      strictPort: true,
      proxy: { '/api': env.NODEKIT_API_URL || 'http://127.0.0.1:8765' },
    },
  };
});
