import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.resolve(root, '../../ui/node_modules/@playwright/test'));
await fs.mkdir(path.join(root, 'png'), { recursive: true });
// Use Playwright's cross-platform Chromium unless a local browser is specified.
const browser = await chromium.launch({ executablePath: process.env.CHROME_EXECUTABLE || undefined, headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 2048, height: 2048 }, deviceScaleFactor: 1 });
  for (const file of (await fs.readdir(path.join(root, 'svg'))).filter(f => f.endsWith('.svg'))) {
    const svg = await fs.readFile(path.join(root, 'svg', file), 'utf8');
    await page.setContent(`<html><head><style>*{box-sizing:border-box}html,body{margin:0;width:2048px;height:2048px;background:transparent}svg{display:block;width:2048px;height:2048px}</style></head><body>${svg}</body></html>`);
    await page.screenshot({ path: path.join(root, 'png', file.replace('.svg', '-2048.png')), omitBackground: true });
  }
} finally { await browser.close(); }
console.log('Rendered six 2048 px PNG masters.');
