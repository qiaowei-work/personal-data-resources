import { spawn } from 'node:child_process';

const args = process.argv.slice(2);
const child = spawn('npx', ['-y', 'chrome-devtools-mcp@latest', ...args], { stdio: ['pipe', 'pipe', 'pipe'] });
let stderr = '', buf = '';
child.stderr.on('data', (d) => { stderr += d; });
child.stdout.on('data', (d) => {
  buf += d;
  for (const line of buf.split('\n')) {
    if (!line.trim()) continue;
    try {
      const m = JSON.parse(line);
      if (m.id === 3) {
        console.log('=== list_pages RESPONSE ===');
        console.log(JSON.stringify(m, null, 2).slice(0, 2500));
      }
    } catch {}
  }
  buf = '';
});
const send = (o) => child.stdin.write(JSON.stringify(o) + '\n');
send({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'p', version: '1' } } });
setTimeout(() => send({ jsonrpc: '2.0', method: 'notifications/initialized' }), 1200);
setTimeout(() => send({ jsonrpc: '2.0', id: 3, method: 'tools/call', params: { name: 'list_pages', arguments: {} } }), 3000);
setTimeout(() => {
  console.log('\n=== STDERR TAIL ===');
  console.log(stderr.split('\n').filter(l => !l.includes('Google collects') && !l.includes('chrome-devtools-mcp exposes') && !l.includes('Avoid sharing') && !l.includes('Performance tools') && !l.includes('For more details') && l.trim()).join('\n').slice(0, 2000) || '(no errors)');
  child.kill('SIGKILL');
  process.exit(0);
}, 25000);
