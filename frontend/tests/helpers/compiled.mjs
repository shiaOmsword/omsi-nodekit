import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { after } from 'node:test';

const root = fileURLToPath(new URL('../../', import.meta.url));
const require = createRequire(import.meta.url);
mkdirSync(join(root, '.cache'), { recursive: true });
const output = mkdtempSync(join(root, '.cache', 'tests-'));
after(() => rmSync(output, { recursive: true, force: true }));
writeFileSync(join(output, 'package.json'), '{"type":"commonjs"}');
execFileSync(process.execPath, [require.resolve('typescript/bin/tsc'),
  'src/api.ts', 'src/framework/components/index.ts', 'src/framework/messages/index.ts',
  '--outDir', output, '--rootDir', 'src', '--module', 'commonjs', '--target', 'ES2022',
  '--jsx', 'react-jsx', '--esModuleInterop', '--skipLibCheck', '--strict'], { cwd: root, stdio: 'pipe' });

export function compiled(path) {
  return require(join(output, path));
}
