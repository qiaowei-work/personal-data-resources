// Minimal CDP driver for the user's running Chrome (Chrome >=144 security model:
// HTTP /json/* endpoints are 404; only the browser websocket from DevToolsActivePort works).
import fs from 'node:fs';
import os from 'node:os';

const PORT_FILE = `${os.homedir()}/Library/Application Support/Google/Chrome/DevToolsActivePort`;

function wsUrl() {
  const [port, path] = fs.readFileSync(PORT_FILE, 'utf8').trim().split('\n');
  return `ws://127.0.0.1:${port}${path}`;
}

class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); this.events = []; this.sessions = []; }
  static async connect() {
    const ws = new WebSocket(wsUrl());
    const c = new CDP(ws);
    ws.addEventListener('message', (e) => {
      const msg = JSON.parse(e.data);
      if (msg.id && c.pending.has(msg.id)) {
        const { resolve, reject } = c.pending.get(msg.id);
        c.pending.delete(msg.id);
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
      } else if (msg.method) {
        c.events.push(msg);
        if (msg.method === 'Target.attachedToTarget') c.sessions.push(msg.params.sessionId);
      }
    });
    await new Promise((res, rej) => {
      ws.addEventListener('open', res, { once: true });
      ws.addEventListener('error', () => rej(new Error('ws error')), { once: true });
    });
    return c;
  }
  send(method, params = {}, sessionId) {
    const id = ++this.id;
    const payload = { id, method, params };
    if (sessionId) payload.sessionId = sessionId;
    this.ws.send(JSON.stringify(payload));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); reject(new Error(`timeout ${method}`)); } }, 45000);
    });
  }
  async targets() { return (await this.send('Target.getTargets')).targetInfos; }
  async attach(targetId) {
    const { sessionId } = await this.send('Target.attachToTarget', { targetId, flatten: true });
    return sessionId;
  }
  async eval(sessionId, expression) {
    const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }, sessionId);
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || 'eval error');
    return r.result.value;
  }
  close() { this.ws.close(); }
}

export { CDP };

const [cmd, ...rest] = process.argv.slice(2);
const c = await CDP.connect();

if (cmd === 'list') {
  const ts = await c.targets();
  for (const t of ts) if (t.type === 'page') console.log(`${t.targetId}\t${t.title.slice(0, 50)}\t${t.url.slice(0, 110)}`);
} else if (cmd === 'eval') {
  const [match, expr] = rest;
  const t = (await c.targets()).find((t) => t.type === 'page' && t.url.includes(match));
  if (!t) throw new Error(`no page matching ${match}`);
  const sid = await c.attach(t.targetId);
  console.log(JSON.stringify(await c.eval(sid, expr), null, 2));
} else if (cmd === 'goto') {
  const [match, url] = rest;
  const t = (await c.targets()).find((t) => t.type === 'page' && t.url.includes(match));
  if (!t) throw new Error(`no page matching ${match}`);
  const sid = await c.attach(t.targetId);
  await c.send('Page.enable', {}, sid);
  await c.send('Page.navigate', { url }, sid);
  console.log('navigating to', url);
} else if (cmd === 'newtab') {
  const { targetId } = await c.send('Target.createTarget', { url: rest[0] || 'about:blank' });
  console.log('created', targetId);
}
c.close();
