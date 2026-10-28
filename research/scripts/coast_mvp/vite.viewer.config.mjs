// Standalone local preview only; no production entry point or data path.
import {fileURLToPath} from 'node:url';
export default {
  root: fileURLToPath(new URL('../../../', import.meta.url)),
  publicDir: false,
  server: {host: 'localhost', port: 5179, strictPort: true},
};
