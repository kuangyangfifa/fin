'use strict';
/*
 * 学校退费收款单 —— 自托管后端（仅依赖 Node.js 内置模块，无需 npm install）
 * 角色：老师(登录,仅看自己) / 主管·校方(签字令牌链接,无需登录) / 财务(管理密钥,看全部)
 * 数据：文件系统存储(data/)，多端共享同一份数据。
 */
const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const zlib = require('zlib');
const { URL } = require('url');

const PORT = process.env.PORT || 3000;
const ROOT = __dirname;
// 与 Flask 主模块同域部署时的子路径；独立域名部署时把该变量设为空串。
const BASE_PATH = process.env.REFUND_BASE_PATH === undefined
  ? '/refund'
  : String(process.env.REFUND_BASE_PATH).replace(/\/+$/, '');
// 运行时数据与代码分离，便于服务器备份与升级。
const DATA_DIR = process.env.REFUND_DATA_DIR || path.join(ROOT, 'data');
const FORMS_DIR = path.join(DATA_DIR, 'forms');
const USERS_FILE = path.join(DATA_DIR, 'users.json');
const SESSIONS_FILE = path.join(DATA_DIR, 'sessions.json');
const CONFIG_FILE = path.join(DATA_DIR, 'config.json');
const UPLOADS_DIR = path.join(DATA_DIR, 'uploads');

// ---------- 基础工具 ----------
function ensureDirs() {
  for (const d of [DATA_DIR, FORMS_DIR, UPLOADS_DIR]) {
    if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
  }
}
function readJSON(file, fallback) {
  try {
    if (!fs.existsSync(file)) return fallback;
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (e) {
    return fallback;
  }
}
function writeJSON(file, obj) {
  const tmp = file + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(obj, null, 2), 'utf8');
  fs.renameSync(tmp, file); // 原子替换，降低并发损坏风险
}

// 写串行化：所有写操作排队执行，避免并发写同一文件导致损坏
let writeChain = Promise.resolve();
function withLock(fn) {
  const run = writeChain.then(fn, fn);
  writeChain = run.then(() => {}, () => {});
  return run;
}

// ---------- 配置：财务后台管理密钥 ----------
// 可用环境变量 ADMIN_KEY 覆盖；首次运行写入 config.json，之后以 config.json 为准。
// 不在源码中内置口令：未设置 ADMIN_KEY 时随机生成并打印一次，随后持久化到 config.json。
const DEFAULT_ADMIN_KEY = process.env.ADMIN_KEY || crypto.randomBytes(12).toString('hex');
// 如需把早期版本的密钥一次性迁移到新口令，用 LEGACY_ADMIN_KEY 环境变量传入（逗号分隔）。
const LEGACY_ADMIN_KEYS = (process.env.LEGACY_ADMIN_KEY || '').split(',').filter(Boolean);

const DEFAULT_WECHAT = {
  appId: '',
  appSecret: '',
  nameLogin: true,          // 微信内「姓名 + 手机尾号」免注册进入
  nameLoginNeedPhone4: true, // 是否需要手机号后 4 位（用于区分同名老师）
  verifyFiles: {},           // 公众号「网页授权域名」校验文件：文件名 -> 内容
};

function getConfig() {
  let cfg = readJSON(CONFIG_FILE, null);
  if (!cfg || !cfg.adminKey) {
    cfg = { adminKey: DEFAULT_ADMIN_KEY, seq: 0 };
    writeJSON(CONFIG_FILE, cfg);
    console.log('\n=========================================================');
    console.log('【财务后台密码】已初始化为：' + cfg.adminKey);
    console.log('（可在 data/config.json 中修改；财务登录后台时填入此密码）');
    console.log('=========================================================\n');
  }
  if (LEGACY_ADMIN_KEYS.indexOf(cfg.adminKey) >= 0) {
    cfg.adminKey = DEFAULT_ADMIN_KEY;
    writeJSON(CONFIG_FILE, cfg);
    console.log('【财务后台密码】已迁移为指定密码：' + cfg.adminKey);
  }
  if (!cfg.wechat) {
    cfg.wechat = Object.assign({}, DEFAULT_WECHAT);
    writeJSON(CONFIG_FILE, cfg);
  }
  if (cfg.publicBaseUrl === undefined) cfg.publicBaseUrl = '';
  for (const k of Object.keys(DEFAULT_WECHAT)) {
    if (cfg.wechat[k] === undefined) cfg.wechat[k] = DEFAULT_WECHAT[k];
  }
  return cfg;
}

function getWx() {
  const w = getConfig().wechat;
  return {
    appId: w.appId || '',
    appSecret: w.appSecret || '',
    nameLogin: w.nameLogin !== false,
    nameLoginNeedPhone4: w.nameLoginNeedPhone4 !== false,
    verifyFiles: w.verifyFiles || {},
    configured: !!(w.appId && w.appSecret),
  };
}
function saveWx(patch) {
  const cfg = getConfig();
  cfg.wechat = Object.assign({}, DEFAULT_WECHAT, cfg.wechat || {}, patch);
  writeJSON(CONFIG_FILE, cfg);
  return cfg.wechat;
}

// ---------- 密码哈希 ----------
function hashPassword(password, salt) {
  salt = salt || crypto.randomBytes(16).toString('hex');
  const hash = crypto.scryptSync(password, salt, 64).toString('hex');
  return { salt, hash };
}
function verifyPassword(password, salt, hash) {
  const h = crypto.scryptSync(password, salt, 64).toString('hex');
  return h === hash;
}

// ---------- 会话 ----------
function loadSessions() { return readJSON(SESSIONS_FILE, {}); }
function saveSessions(s) { writeJSON(SESSIONS_FILE, s); }
function createSession(userId) {
  const token = crypto.randomBytes(32).toString('hex');
  const sessions = loadSessions();
  sessions[token] = { userId, expiresAt: Date.now() + 7 * 24 * 3600 * 1000 };
  saveSessions(sessions);
  return token;
}
function getSessionUser(token) {
  if (!token) return null;
  const sessions = loadSessions();
  const s = sessions[token];
  if (!s) return null;
  if (s.expiresAt < Date.now()) { delete sessions[token]; saveSessions(sessions); return null; }
  const users = readJSON(USERS_FILE, {});
  return users[s.userId] || null;
}
function destroySession(token) {
  const sessions = loadSessions();
  delete sessions[token];
  saveSessions(sessions);
}

// ---------- 用户 ----------
function loadUsers() { return readJSON(USERS_FILE, {}); }
function saveUsers(u) { writeJSON(USERS_FILE, u); }

// ---------- 微信网页授权 ----------
const wxTickets = new Map(); // 一次性登录票据：ticket -> { userId, expiresAt }

function getOrigin(req, urlObj) {
  const cfg = getConfig();
  // 允许在后台显式指定公网地址（反向代理改写 Host 时使用）
  if (cfg.publicBaseUrl) {
    return String(cfg.publicBaseUrl).trim().replace(/#.*$/, '').replace(/\?.*$/, '').replace(/\/+$/, '');
  }
  const host = String(req.headers.host || req.headers['x-forwarded-host'] || urlObj.host).split(',')[0].trim();
  let proto = String(req.headers['x-forwarded-proto'] || '').split(',')[0].trim();
  if (!proto) {
    if (req.socket && req.socket.encrypted) {
      proto = 'https';
    } else {
      const h = host.split(':')[0];
      const isIp = /^\d+\.\d+\.\d+\.\d+$/.test(h);
      const isLocal = h === 'localhost' || h === '127.0.0.1' || h === '0.0.0.0';
      proto = (!isIp && !isLocal && h.includes('.')) ? 'https' : 'http';
    }
  }
  return proto + '://' + host + BASE_PATH;
}
// 链接前缀：可带查询串（如部署平台的访问口令 sharecode），供签字链接使用
function getLinkBase(req, urlObj) {
  const cfg = getConfig();
  if (cfg.publicBaseUrl) return String(cfg.publicBaseUrl).trim().replace(/#.*$/, '');
  return getOrigin(req, urlObj);
}
function makeHashLink(base, hashPath) {
  const b = String(base).replace(/#.*$/, '');
  return b.indexOf('?') >= 0 ? (b + '#' + hashPath) : (b + '/#' + hashPath);
}
function httpGetJSON(url) {
  return new Promise((resolve, reject) => {
    const rq = https.get(url, { timeout: 8000 }, (r) => {
      let d = '';
      r.on('data', (c) => { d += c; });
      r.on('end', () => { try { resolve(JSON.parse(d)); } catch (e) { reject(new Error('微信接口返回异常：' + d.slice(0, 140))); } });
    });
    rq.on('timeout', () => rq.destroy(new Error('微信接口请求超时')));
    rq.on('error', reject);
  });
}
function signState(obj) {
  const payload = Buffer.from(JSON.stringify(obj)).toString('base64url');
  const mac = crypto.createHmac('sha256', getConfig().adminKey).update(payload).digest('base64url').slice(0, 24);
  return payload + '.' + mac;
}
function verifyState(s) {
  if (!s) return false;
  const i = s.lastIndexOf('.');
  if (i < 0) return false;
  const payload = s.slice(0, i);
  const mac = s.slice(i + 1);
  const want = crypto.createHmac('sha256', getConfig().adminKey).update(payload).digest('base64url').slice(0, 24);
  if (mac.length !== want.length) return false;
  try { if (!crypto.timingSafeEqual(Buffer.from(mac), Buffer.from(want))) return false; } catch (e) { return false; }
  try {
    const o = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
    return Date.now() - (o.t || 0) < 15 * 60 * 1000;
  } catch (e) { return false; }
}
function wxUserKey(openid) {
  return 'wx:' + crypto.createHash('sha256').update('wx|' + openid).digest('hex').slice(0, 20);
}
function upsertWxUser(openid) {
  const key = wxUserKey(openid);
  const users = loadUsers();
  if (!users[key]) {
    users[key] = { id: key, name: '', wechat: true, createdAt: Date.now() };
    saveUsers(users);
  }
  return users[key];
}
function nameLoginUser(name, phone4) {
  const key = 'nm:' + crypto.createHash('sha256').update('nm|' + name + '|' + phone4).digest('hex').slice(0, 20);
  const users = loadUsers();
  let created = false;
  if (!users[key]) {
    users[key] = { id: key, name, nameLogin: true, createdAt: Date.now() };
    saveUsers(users);
    created = true;
  }
  return { user: users[key], created };
}
function issueTicket(userId) {
  for (const [k, v] of wxTickets) if (v.expiresAt < Date.now()) wxTickets.delete(k);
  const t = crypto.randomBytes(24).toString('hex');
  wxTickets.set(t, { userId, expiresAt: Date.now() + 2 * 60 * 1000 });
  return t;
}
function consumeTicket(t) {
  const rec = t && wxTickets.get(t);
  if (!rec || rec.expiresAt < Date.now()) { if (t) wxTickets.delete(t); return null; }
  wxTickets.delete(t);
  return rec;
}
function userView(u) {
  return { phone: u.phone || '', name: u.name || '', wechat: !!u.wechat, nameLogin: !!u.nameLogin };
}

// ---------- 表单（主表 + 退费明细） ----------
const ITEM_FIELDS = ['studentName', 'className', 'enrollDate', 'courseName',
  'tuitionFee', 'mealFee', 'refundTotal', 'payeeName', 'refundReason'];
const ITEM_LABEL = {
  studentName: '学生姓名', className: '所在班级', enrollDate: '入校就读时间', courseName: '课程名称',
  tuitionFee: '学费', mealFee: '餐费', refundTotal: '退费总金额', payeeName: '收款户名', refundReason: '退费原因',
};

function sumItems(items) {
  return (items || []).reduce((s, it) => s + (Number(it.refundTotal) || 0), 0);
}
function round2(n) { return Math.round((Number(n) || 0) * 100) / 100; }
function cleanItem(it, i) {
  const o = { id: 'i' + (i + 1) };
  for (const k of ITEM_FIELDS) o[k] = String(it && it[k] !== undefined ? it[k] : '').trim();
  return o;
}
// 兼容历史单据（早期为单学生扁平结构），读取时统一成 items 结构
function normalizeForm(f) {
  if (!f) return f;
  if (!Array.isArray(f.items) || !f.items.length) {
    f.items = [cleanItem({
      studentName: f.studentName, className: f.className, enrollDate: f.enrollDate,
      courseName: f.courseName, tuitionFee: f.tuitionFee, mealFee: f.mealFee,
      refundTotal: f.refundTotal, payeeName: f.payeeName, refundReason: f.refundReason,
    }, 0)];
  } else {
    f.items = f.items.map(cleanItem);
  }
  if (!f.submitterName) f.submitterName = f.teacherName || f.ownerName || '';
  f.totalAmount = round2(sumItems(f.items));
  return f;
}

function formPath(id) { return path.join(FORMS_DIR, id + '.json'); }
function loadForm(id) {
  try { return normalizeForm(JSON.parse(fs.readFileSync(formPath(id), 'utf8'))); }
  catch (e) { return null; }
}
function saveForm(form) { writeJSON(formPath(form.id), form); }
function genId() {
  const cfg = getConfig();
  cfg.seq = (cfg.seq || 0) + 1;
  writeJSON(CONFIG_FILE, cfg);
  const ym = new Date().toISOString().slice(0, 7).replace('-', '');
  return `R${ym}${String(cfg.seq).padStart(4, '0')}`;
}

// 财务/管理员可见的状态文案
const STATUS_TEXT = {
  pending_supervisor: '待主管签字',
  pending_school: '待校方签字',
  completed: '已完成(双方签字)',
  revoked: '已撤销',
  returned: '已退回老师',
};

// ---------- HTTP 辅助 ----------
function sendJSON(res, code, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(body);
}
function readBody(req, maxBytes) {
  const limit = maxBytes || 5e6;
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (c) => { data += c; if (data.length > limit) { reject(new Error('请求体过大')); req.destroy(); } });
    req.on('end', () => { try { resolve(data ? JSON.parse(data) : {}); } catch (e) { reject(e); } });
    req.on('error', reject);
  });
}
function getToken(req, urlObj) {
  const auth = req.headers['x-auth-token'];
  if (auth) return auth;
  return urlObj.searchParams.get('token') || '';
}

// ---------- 业务校验 ----------
// 注意：退费方式、退款日期由财务在双方签字完成后实际退款时填写，老师填单阶段不作为必填项。
const MAX_ITEMS = 200;
function validateItems(body) {
  const errors = [];
  const items = Array.isArray(body.items) ? body.items : [];
  if (!items.length) return ['请至少填写一条退费明细'];
  if (items.length > MAX_ITEMS) return ['退费明细最多 ' + MAX_ITEMS + ' 条'];
  items.forEach((it, i) => {
    const miss = ITEM_FIELDS.filter((k) => String((it && it[k]) === undefined ? '' : it[k]).trim() === '')
      .map((k) => ITEM_LABEL[k]);
    if (miss.length) errors.push('第 ' + (i + 1) + ' 行：' + miss.join('、'));
    if (String(it && it.refundTotal !== undefined ? it.refundTotal : '').trim() !== ''
      && isNaN(Number(it.refundTotal))) errors.push('第 ' + (i + 1) + ' 行：退费总金额需为数字');
  });
  if (!String(body.submitterName || '').trim()) errors.push('填报人');
  return errors;
}

// ---------- 附件 ----------
const ATT_MAX_COUNT = 9;                        // 每单最多 9 个附件
const ATT_MAX_BYTES = 6 * 1024 * 1024;          // 单个附件上限 6MB（base64 前）
const ATT_TYPES = {
  'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp',
  'image/gif': '.gif', 'application/pdf': '.pdf',
};
const ATT_MIME_BY_EXT = {
  '.jpg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp',
  '.gif': 'image/gif', '.pdf': 'application/pdf',
};
function attDir(formId) {
  const d = path.join(UPLOADS_DIR, formId);
  if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
  return d;
}
// 把前端传来的 dataURL 数组落盘，返回附件元数据
function saveAttachments(formId, list) {
  const out = [];
  if (!Array.isArray(list) || !list.length) return out;
  for (const item of list.slice(0, ATT_MAX_COUNT)) {
    const m = String(item && item.data || '').match(/^data:([\w/+.-]+);base64,([A-Za-z0-9+/=\s]+)$/);
    if (!m) continue;
    const mime = m[1].toLowerCase();
    const ext = ATT_TYPES[mime];
    if (!ext) continue;
    const buf = Buffer.from(m[2].replace(/\s/g, ''), 'base64');
    if (!buf.length || buf.length > ATT_MAX_BYTES) continue;
    const attId = crypto.randomBytes(16).toString('hex');
    const fileName = String(item.name || '附件').replace(/[\\/:*?"<>|]/g, '_').slice(0, 80) || '附件';
    fs.writeFileSync(path.join(attDir(formId), attId + ext), buf);
    out.push({ id: attId, ext, name: fileName, type: mime, size: buf.length });
  }
  return out;
}
function formatSize(n) {
  const b = Number(n) || 0;
  if (b < 1024) return b + ' B';
  if (b < 1024 * 1024) return (b / 1024).toFixed(0) + ' KB';
  return (b / 1024 / 1024).toFixed(1) + ' MB';
}

// ---------- 明细导入：模板 / CSV / XLSX 解析 ----------
const IMPORT_HEADERS = [
  ['studentName', '学生姓名'],
  ['className', '所在班级'],
  ['enrollDate', '入校就读时间'],
  ['courseName', '课程名称'],
  ['tuitionFee', '学费'],
  ['mealFee', '餐费'],
  ['refundTotal', '退费总金额'],
  ['payeeName', '收款户名'],
  ['refundReason', '退费原因'],
];
function csvUnquote(s) {
  let t = String(s || '').trim();
  if (t.length > 1 && t[0] === '"' && t[t.length - 1] === '"') t = t.slice(1, -1).replace(/""/g, '"');
  return t;
}
function parseCsv(text) {
  const s = String(text || '').replace(/^\uFEFF/, '');
  const rows = [];
  let row = [];
  let cell = '';
  let inQ = false;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (inQ) {
      if (c === '"') {
        if (s[i + 1] === '"') { cell += '"'; i++; } else inQ = false;
      } else cell += c;
    } else if (c === '"') inQ = true;
    else if (c === ',') { row.push(cell); cell = ''; }
    else if (c === '\r') { /* 跳过 */ }
    else if (c === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; }
    else cell += c;
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
  return rows;
}
function decodeXmlEntities(s) {
  return String(s || '')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'").replace(/&#(\d+);/g, (m, d) => String.fromCharCode(Number(d)))
    .replace(/&#x([0-9a-fA-F]+);/g, (m, h) => String.fromCharCode(parseInt(h, 16)))
    .replace(/&amp;/g, '&');
}
function stripTags(s) { return String(s || '').replace(/<[^>]*>/g, ''); }
function colIndex(ref) {
  let n = 0;
  for (const ch of String(ref).toUpperCase()) {
    if (ch < 'A' || ch > 'Z') break;
    n = n * 26 + (ch.charCodeAt(0) - 64);
  }
  return Math.max(0, n - 1);
}
// 解析 xlsx（仅用内置 zlib，读取第一个工作表）
function xlsxToRows(buf) {
  let eocd = -1;
  for (let i = buf.length - 22; i >= 0; i--) { if (buf.readUInt32LE(i) === 0x06054b50) { eocd = i; break; } }
  if (eocd < 0) throw new Error('不是有效的 Excel(.xlsx) 文件，请另存为 CSV 后重试');
  const count = buf.readUInt16LE(eocd + 10);
  let off = buf.readUInt32LE(eocd + 16);
  const entries = {};
  for (let i = 0; i < count; i++) {
    if (off + 46 > buf.length || buf.readUInt32LE(off) !== 0x02014b50) break;
    const method = buf.readUInt16LE(off + 10);
    const compSize = buf.readUInt32LE(off + 20);
    const nameLen = buf.readUInt16LE(off + 28);
    const extraLen = buf.readUInt16LE(off + 30);
    const commLen = buf.readUInt16LE(off + 32);
    const localOff = buf.readUInt32LE(off + 42);
    const name = buf.slice(off + 46, off + 46 + nameLen).toString('utf8');
    entries[name] = { method, compSize, localOff };
    off += 46 + nameLen + extraLen + commLen;
  }
  const readEntry = (e) => {
    const lo = e.localOff;
    if (buf.readUInt32LE(lo) !== 0x04034b50) throw new Error('Excel 文件结构异常');
    const nameLen = buf.readUInt16LE(lo + 26);
    const extraLen = buf.readUInt16LE(lo + 28);
    const start = lo + 30 + nameLen + extraLen;
    const data = buf.slice(start, start + e.compSize);
    if (e.method === 0) return data;
    if (e.method === 8) return zlib.inflateRawSync(data);
    throw new Error('Excel 文件使用了不支持的压缩方式');
  };
  const keyOf = (pred) => Object.keys(entries).find(pred);
  const sharedKey = keyOf((n) => n.toLowerCase() === 'xl/sharedstrings.xml');
  const shared = [];
  if (sharedKey) {
    const xml = readEntry(entries[sharedKey]).toString('utf8');
    for (const m of xml.matchAll(/<si[\s>][\s\S]*?<\/si>|<si\/>/g)) {
      const ts = [...m[0].matchAll(/<t[^>]*>([\s\S]*?)<\/t>/g)].map((x) => decodeXmlEntities(x[1]));
      shared.push(ts.join(''));
    }
  }
  const sheetKey = Object.keys(entries).filter((n) => /^xl\/worksheets\/sheet\d+\.xml$/i.test(n)).sort()[0];
  if (!sheetKey) throw new Error('Excel 中未找到工作表');
  const sheet = readEntry(entries[sheetKey]).toString('utf8');
  const rows = [];
  for (const rm of sheet.matchAll(/<row[^>]*>([\s\S]*?)<\/row>/g)) {
    const arr = [];
    for (const cm of rm[1].matchAll(/<c([^>]*)>([\s\S]*?)<\/c>/g)) {
      const attrs = cm[1];
      const body = cm[2];
      const ref = (attrs.match(/r="([A-Za-z]+)\d+"/) || [])[1] || '';
      const t = (attrs.match(/\st="([^"]+)"/) || [])[1] || '';
      let val = '';
      if (t === 's') {
        const v = (body.match(/<v>([\s\S]*?)<\/v>/) || [])[1];
        val = v !== undefined && shared[Number(v)] !== undefined ? shared[Number(v)] : '';
      } else if (t === 'inlineStr') {
        val = [...body.matchAll(/<t[^>]*>([\s\S]*?)<\/t>/g)].map((x) => decodeXmlEntities(x[1])).join('');
      } else {
        const v = (body.match(/<v>([\s\S]*?)<\/v>/) || [])[1];
        val = v === undefined ? '' : decodeXmlEntities(stripTags(v));
      }
      if (ref) arr[colIndex(ref)] = String(val).trim();
    }
    rows.push(arr);
  }
  return rows;
}
// 把二维表格按表头映射成明细对象数组
function rowsToItems(rows) {
  const headerKeys = {};
  let headerIdx = -1;
  for (let r = 0; r < Math.min(rows.length, 10); r++) {
    const cells = (rows[r] || []).map((c) => String(c || '').replace(/\s/g, ''));
    if (cells.some((c) => c.indexOf('学生姓名') >= 0 || c === '姓名')) { headerIdx = r; break; }
  }
  if (headerIdx < 0) throw new Error('未识别到表头，请使用下载的模板（第一行需含「学生姓名」等列名）');
  (rows[headerIdx] || []).forEach((c, i) => {
    const name = String(c || '').replace(/\s/g, '');
    for (const [key, label] of IMPORT_HEADERS) {
      if (headerKeys[key]) continue;
      if (name === label || name === label + '（元）' || name.indexOf(label) === 0
        || (key === 'className' && name === '班级')
        || (key === 'courseName' && name === '课程')
        || (key === 'enrollDate' && (name === '入校就读' || name === '入学时间'))
        || (key === 'refundTotal' && (name === '退费金额' || name === '金额'))
        || (key === 'payeeName' && (name === '收款人' || name === '户名'))
        || (key === 'refundReason' && name === '原因')) {
        headerKeys[key] = i;
      }
    }
  });
  const items = [];
  for (let r = headerIdx + 1; r < rows.length; r++) {
    const row = rows[r] || [];
    const get = (k) => (headerKeys[k] === undefined ? '' : String(row[headerKeys[k]] === undefined ? '' : row[headerKeys[k]]).trim());
    const it = {};
    for (const [key] of IMPORT_HEADERS) it[key] = get(key);
    if (!it.studentName && !it.refundTotal && !it.className) continue;      // 空行
    if (/示例|请删除/.test(it.studentName)) continue;                        // 模板示例行
    if (!it.refundTotal) it.refundTotal = round2((Number(it.tuitionFee) || 0) + (Number(it.mealFee) || 0)) || '';
    items.push(it);
  }
  return { items, headerKeys };
}

// ---------- API 路由 ----------
async function handleApi(req, res, urlObj) {
  const parts = urlObj.pathname.split('/').filter(Boolean); // ['api', ...]
  const seg = parts.slice(1); // 去掉 'api'
  const method = req.method;

  // ---- 注册 ----
  if (seg[0] === 'register' && method === 'POST') {
    const b = await readBody(req);
    if (!/^1\d{10}$/.test(b.phone || '')) return sendJSON(res, 400, { error: '请输入正确的 11 位手机号' });
    if (!b.password || String(b.password).length < 6) return sendJSON(res, 400, { error: '密码至少 6 位' });
    if (!b.name || !b.name.trim()) return sendJSON(res, 400, { error: '请填写老师姓名' });
    const users = loadUsers();
    if (users[b.phone]) return sendJSON(res, 409, { error: '该手机号已注册，请直接登录' });
    const { salt, hash } = hashPassword(b.password);
    users[b.phone] = { id: b.phone, phone: b.phone, name: b.name.trim(), salt, hash, createdAt: Date.now() };
    saveUsers(users);
    const token = createSession(b.phone);
    return sendJSON(res, 200, { token, user: userView(users[b.phone]) });
  }

  // ---- 登录 ----
  if (seg[0] === 'login' && method === 'POST') {
    const b = await readBody(req);
    const users = loadUsers();
    const u = users[b.phone];
    if (!u || !verifyPassword(b.password || '', u.salt, u.hash)) return sendJSON(res, 401, { error: '手机号或密码错误' });
    const token = createSession(u.id);
    return sendJSON(res, 200, { token, user: userView(u) });
  }

  // ---- 登出 ----
  if (seg[0] === 'logout' && method === 'POST') {
    destroySession(getToken(req, urlObj));
    return sendJSON(res, 200, { ok: true });
  }

  // ---- 当前用户 ----
  if (seg[0] === 'me' && method === 'GET') {
    const u = getSessionUser(getToken(req, urlObj));
    if (!u) return sendJSON(res, 401, { error: '未登录' });
    return sendJSON(res, 200, { user: userView(u) });
  }

  // ---- 修改我的姓名（如「张老师」）----
  if (seg[0] === 'me' && seg[1] === 'name' && method === 'POST') {
    const u = getSessionUser(getToken(req, urlObj));
    if (!u) return sendJSON(res, 401, { error: '未登录' });
    const b = await readBody(req);
    const name = String(b.name || '').trim().replace(/\s+/g, ' ');
    if (!name) return sendJSON(res, 400, { error: '请填写您的姓名' });
    if (name.length > 20) return sendJSON(res, 400, { error: '姓名请控制在 20 字以内' });
    await withLock(() => {
      const users = loadUsers();
      if (users[u.id]) { users[u.id].name = name; saveUsers(users); }
      // 同步历史单据上的填单人显示名
      for (const file of fs.readdirSync(FORMS_DIR)) {
        if (!file.endsWith('.json')) continue;
        const f = loadForm(file.replace('.json', ''));
        if (f && f.ownerId === u.id && f.ownerName !== name) { f.ownerName = name; saveForm(f); }
      }
    });
    return sendJSON(res, 200, { ok: true, user: userView(Object.assign({}, u, { name })) });
  }

  // ---- 微信登录：配置状态（前端据此显示登录方式）----
  if (seg[0] === 'auth' && seg[1] === 'wechat' && seg[2] === 'status' && method === 'GET') {
    const wx = getWx();
    return sendJSON(res, 200, {
      configured: wx.configured,
      appId: wx.appId,
      nameLogin: wx.nameLogin,
      nameLoginNeedPhone4: wx.nameLoginNeedPhone4,
      callbackUrl: getOrigin(req, urlObj) + '/api/auth/wechat/callback',
    });
  }

  // ---- 微信登录：跳转公众号网页授权 ----
  if (seg[0] === 'auth' && seg[1] === 'wechat' && seg[2] === 'start' && method === 'GET') {
    const wx = getWx();
    if (!wx.configured) return sendJSON(res, 400, { error: '微信登录未配置：请在财务后台填写公众号 AppID 与 AppSecret' });
    const origin = getOrigin(req, urlObj);
    const state = signState({ t: Date.now(), n: crypto.randomBytes(6).toString('hex') });
    const url = 'https://open.weixin.qq.com/connect/oauth2/authorize'
      + '?appid=' + encodeURIComponent(wx.appId)
      + '&redirect_uri=' + encodeURIComponent(origin + '/api/auth/wechat/callback')
      + '&response_type=code&scope=snsapi_base'
      + '&state=' + encodeURIComponent(state)
      + '#wechat_redirect';
    res.writeHead(302, { Location: url });
    return res.end();
  }

  // ---- 微信登录：授权回调（code 换 openid，签发一次性票据）----
  if (seg[0] === 'auth' && seg[1] === 'wechat' && seg[2] === 'callback' && method === 'GET') {
    const wx = getWx();
    const origin = getOrigin(req, urlObj);
    const fail = (msg) => {
      res.writeHead(302, { Location: origin + '/#/login?wxerr=' + encodeURIComponent(msg) });
      return res.end();
    };
    if (!wx.configured) return fail('微信登录未配置');
    const state = urlObj.searchParams.get('state') || '';
    const code = urlObj.searchParams.get('code') || '';
    if (!verifyState(state)) return fail('登录状态已过期，请重新登录');
    if (!code) return fail('未获得微信授权（可能已取消）');
    let tok;
    try {
      tok = await httpGetJSON('https://api.weixin.qq.com/sns/oauth2/access_token'
        + '?appid=' + encodeURIComponent(wx.appId)
        + '&secret=' + encodeURIComponent(wx.appSecret)
        + '&code=' + encodeURIComponent(code)
        + '&grant_type=authorization_code');
    } catch (e) { return fail('微信接口访问失败：' + e.message); }
    if (!tok || !tok.openid) return fail('微信授权失败：' + ((tok && (tok.errmsg || tok.errcode)) || '未知错误'));
    const user = upsertWxUser(tok.openid);
    const ticket = issueTicket(user.id);
    res.writeHead(302, { Location: origin + '/#/wx?ticket=' + ticket });
    return res.end();
  }

  // ---- 微信登录：票据换登录态 ----
  if (seg[0] === 'auth' && seg[1] === 'wechat' && seg[2] === 'exchange' && method === 'POST') {
    const b = await readBody(req);
    const rec = consumeTicket(b.ticket);
    if (!rec) return sendJSON(res, 400, { error: '登录票据已失效，请重新微信登录' });
    const u = loadUsers()[rec.userId];
    if (!u) return sendJSON(res, 400, { error: '用户不存在，请重新登录' });
    const token = createSession(u.id);
    return sendJSON(res, 200, { token, user: userView(u), needName: !u.name });
  }

  // ---- 微信内免注册：姓名 + 手机尾号进入 ----
  if (seg[0] === 'auth' && seg[1] === 'name-login' && method === 'POST') {
    const wx = getWx();
    if (!wx.nameLogin) return sendJSON(res, 403, { error: '姓名快捷登录未开启，请联系管理员' });
    const b = await readBody(req);
    const name = String(b.name || '').trim().replace(/\s+/g, ' ');
    if (!name) return sendJSON(res, 400, { error: '请填写您的姓名，如：张老师' });
    if (name.length > 20) return sendJSON(res, 400, { error: '姓名请控制在 20 字以内' });
    let phone4 = '';
    if (wx.nameLoginNeedPhone4) {
      phone4 = String(b.phone4 || '').trim();
      if (!/^\d{4}$/.test(phone4)) return sendJSON(res, 400, { error: '请填写手机号后 4 位' });
    }
    const r = nameLoginUser(name, phone4);
    const token = createSession(r.user.id);
    return sendJSON(res, 200, { token, user: userView(r.user), created: r.created });
  }

  // ---- 联调用：模拟微信授权回调（仅在服务器设置 WECHAT_MOCK=1 时可用）----
  if (seg[0] === 'auth' && seg[1] === 'wechat' && seg[2] === 'mock' && method === 'GET') {
    if (process.env.WECHAT_MOCK !== '1') return sendJSON(res, 404, { error: '接口不存在' });
    const openid = urlObj.searchParams.get('openid') || 'mock_openid_1';
    const user = upsertWxUser(openid);
    const ticket = issueTicket(user.id);
    res.writeHead(302, { Location: getOrigin(req, urlObj) + '/#/wx?ticket=' + ticket });
    return res.end();
  }

  // ---- 老师：我的退费单列表 ----
  if (seg[0] === 'forms' && method === 'GET' && seg.length === 1) {
    const u = getSessionUser(getToken(req, urlObj));
    if (!u) return sendJSON(res, 401, { error: '未登录' });
    const list = fs.readdirSync(FORMS_DIR)
      .filter((f) => f.endsWith('.json'))
      .map((f) => loadForm(f.replace('.json', '')))
      .filter((f) => f && f.ownerId === u.id)
      .sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0))
      .map((f) => Object.assign(publicSummary(f), { supervisorToken: f.supervisorToken, schoolToken: f.schoolToken, returnReason: f.returnReason, returnedBy: f.returnedBy }));
    return sendJSON(res, 200, { forms: list, linkBase: getLinkBase(req, urlObj) });
  }

  // ---- 老师：新建退费单（主表 + 多条退费明细）----
  if (seg[0] === 'forms' && method === 'POST' && seg.length === 1) {
    const u = getSessionUser(getToken(req, urlObj));
    if (!u) return sendJSON(res, 401, { error: '未登录' });
    const b = await readBody(req, 60e6); // 附件以 dataURL 上传，放宽请求体上限
    const errors = validateItems(b);
    if (errors.length) return sendJSON(res, 400, { error: errors.join('；') });
    const id = genId();
    const now = Date.now();
    const attachments = saveAttachments(id, b.attachments);
    const items = (b.items || []).slice(0, MAX_ITEMS).map(cleanItem);
    const form = {
      id,
      ownerId: u.id,
      ownerName: u.name,
      submitterName: String(b.submitterName || u.name || '').trim(),
      status: 'pending_supervisor',
      items,
      totalAmount: round2(sumItems(items)),
      attachments,
      refundFilledAt: 0, refundNote: '',
      refundMethod: '', refundDate: '',
      supervisorToken: crypto.randomBytes(24).toString('hex'),
      schoolToken: crypto.randomBytes(24).toString('hex'),
      supervisorSig: '', supervisorSigner: '', supervisorSignedAt: 0,
      schoolSig: '', schoolSigner: '', schoolSignedAt: 0,
      returnReason: '', returnedBy: '', returnedAt: 0,
      createdAt: now, updatedAt: now,
    };
    saveForm(form);
    const base = getLinkBase(req, urlObj);
    const supervisorSignUrl = makeHashLink(base, `/sign?id=${id}&token=${form.supervisorToken}&role=supervisor`);
    const schoolSignUrl = makeHashLink(base, `/sign?id=${id}&token=${form.schoolToken}&role=school`);
    return sendJSON(res, 200, {
      id, supervisorSignUrl, schoolSignUrl, attachments: attachments.length,
      itemCount: items.length, totalAmount: form.totalAmount,
    });
  }

  // ---- 老师：下载明细导入模板（CSV，Excel 可直接打开）----
  if (seg[0] === 'import' && seg[1] === 'template' && method === 'GET') {
    const header = IMPORT_HEADERS.map((x) => x[1]);
    const sample = ['示例：张三（请删除本行）', '小班', '2025年9月', '保教费', '2000', '500', '2500', '张三父亲', '转园'];
    const csv = [header, sample].map((r) => r.map(csvCell).join(',')).join('\r\n');
    res.writeHead(200, {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': 'attachment; filename="refund_items_template.csv"',
    });
    return res.end('﻿' + csv);
  }

  // ---- 老师：解析批量导入文件（CSV / XLSX）----
  if (seg[0] === 'import' && seg[1] === 'parse' && method === 'POST') {
    const u = getSessionUser(getToken(req, urlObj));
    if (!u) return sendJSON(res, 401, { error: '未登录' });
    const b = await readBody(req, 20e6);
    const name = String(b.name || '').toLowerCase();
    const m = String(b.data || '').match(/^data:[^;]*;base64,([A-Za-z0-9+/=\s]+)$/);
    if (!m) return sendJSON(res, 400, { error: '文件读取失败，请重新选择' });
    const buf = Buffer.from(m[1].replace(/\s/g, ''), 'base64');
    if (!buf.length) return sendJSON(res, 400, { error: '文件为空' });
    if (buf.length > 10 * 1024 * 1024) return sendJSON(res, 400, { error: '文件不能超过 10MB' });
    let rows;
    try {
      if (/\.xlsx$/.test(name)) rows = xlsxToRows(buf);
      else if (/\.xls$/.test(name)) return sendJSON(res, 400, { error: '不支持旧版 .xls，请在 Excel 中另存为 .xlsx 或 CSV 后重试' });
      else rows = parseCsv(buf.toString('utf8'));
    } catch (e) {
      return sendJSON(res, 400, { error: e.message || '文件解析失败' });
    }
    let items;
    try { items = rowsToItems(rows).items; } catch (e) { return sendJSON(res, 400, { error: e.message }); }
    if (!items.length) return sendJSON(res, 400, { error: '文件中没有可导入的明细，请检查是否按模板填写' });
    return sendJSON(res, 200, { items: items.slice(0, MAX_ITEMS), total: items.length, truncated: items.length > MAX_ITEMS });
  }

  // ---- 老师：撤销（审批完成前均可撤销：待主管签字 / 待校方签字）----
  if (seg[0] === 'forms' && seg[2] === 'revoke' && method === 'POST' && seg.length === 3) {
    const u = getSessionUser(getToken(req, urlObj));
    if (!u) return sendJSON(res, 401, { error: '未登录' });
    const f = loadForm(seg[1]);
    if (!f || f.ownerId !== u.id) return sendJSON(res, 404, { error: '未找到' });
    if (!['pending_supervisor', 'pending_school'].includes(f.status)) {
      return sendJSON(res, 409, { error: f.status === 'completed' ? '该单已完成审批，不能撤销' : '当前状态不可撤销' });
    }
    // 撤销即作废已产生的签字，重新提交后从主管签字重新走流程
    f.status = 'revoked';
    f.supervisorSig = ''; f.supervisorSigner = ''; f.supervisorSignedAt = 0;
    f.schoolSig = ''; f.schoolSigner = ''; f.schoolSignedAt = 0;
    f.returnReason = ''; f.returnedBy = ''; f.returnedAt = 0;
    f.updatedAt = Date.now();
    saveForm(f);
    return sendJSON(res, 200, { ok: true, status: f.status, statusText: STATUS_TEXT[f.status] });
  }

  // ---- 老师：删除（审批完成前可删除，连同附件一并清除）----
  if (seg[0] === 'forms' && seg.length === 2 && method === 'DELETE') {
    const u = getSessionUser(getToken(req, urlObj));
    if (!u) return sendJSON(res, 401, { error: '未登录' });
    const f = loadForm(seg[1]);
    if (!f || f.ownerId !== u.id) return sendJSON(res, 404, { error: '未找到' });
    if (f.status === 'completed') return sendJSON(res, 409, { error: '该单已完成审批，不能删除' });
    try {
      fs.rmSync(path.join(UPLOADS_DIR, f.id), { recursive: true, force: true });
      fs.unlinkSync(formPath(f.id));
    } catch (e) {
      if (e.code !== 'ENOENT') return sendJSON(res, 500, { error: '删除失败，请稍后重试' });
    }
    return sendJSON(res, 200, { ok: true, id: f.id });
  }

  // ---- 老师：重新提交（已撤销/已退回可恢复为待主管签字，并清空已有签字与退回信息）----
  if (seg[0] === 'forms' && seg[2] === 'resubmit' && method === 'POST' && seg.length === 3) {
    const u = getSessionUser(getToken(req, urlObj));
    if (!u) return sendJSON(res, 401, { error: '未登录' });
    const f = loadForm(seg[1]);
    if (!f || f.ownerId !== u.id) return sendJSON(res, 404, { error: '未找到' });
    if (!['revoked', 'returned'].includes(f.status)) return sendJSON(res, 409, { error: '当前状态不可重新提交' });
    f.status = 'pending_supervisor';
    f.supervisorSig = ''; f.supervisorSigner = ''; f.supervisorSignedAt = 0;
    f.schoolSig = ''; f.schoolSigner = ''; f.schoolSignedAt = 0;
    f.returnReason = ''; f.returnedBy = ''; f.returnedAt = 0;
    f.updatedAt = Date.now();
    saveForm(f);
    return sendJSON(res, 200, { ok: true, status: f.status, statusText: STATUS_TEXT[f.status] });
  }

  // ---- 老师：查看自己的单条详情 ----
  if (seg[0] === 'forms' && method === 'GET' && seg.length === 2) {
    const u = getSessionUser(getToken(req, urlObj));
    if (!u) return sendJSON(res, 401, { error: '未登录' });
    const f = loadForm(seg[1]);
    if (!f || f.ownerId !== u.id) return sendJSON(res, 404, { error: '未找到' });
    return sendJSON(res, 200, { form: f });
  }

  // ---- 签字（公开，令牌校验，无需登录）----
  if (seg[0] === 'sign' && method === 'GET') {
    const id = urlObj.searchParams.get('id');
    const token = urlObj.searchParams.get('token');
    const f = loadForm(id);
    if (!f) return sendJSON(res, 404, { error: '链接无效或已失效' });
    let role = urlObj.searchParams.get('role') || '';
    if (f.supervisorToken === token) role = 'supervisor';
    else if (f.schoolToken === token) role = 'school';
    else return sendJSON(res, 404, { error: '链接无效或已失效' });
    return sendJSON(res, 200, { form: publicForm(f), role, statusText: STATUS_TEXT[f.status] });
  }
  if (seg[0] === 'sign' && method === 'POST') {
    const b = await readBody(req);
    const f = loadForm(b.id);
    if (!f) return sendJSON(res, 404, { error: '链接无效或已失效' });
    let role = b.role;
    if (f.supervisorToken === b.token) role = 'supervisor';
    else if (f.schoolToken === b.token) role = 'school';
    else return sendJSON(res, 404, { error: '链接无效或已失效' });
    const action = b.action || 'sign';
    if (action === 'return') {
      if (role === 'supervisor') {
        if (f.status !== 'pending_supervisor') return sendJSON(res, 409, { error: '当前阶段无法退回' });
      } else if (role === 'school') {
        if (f.status !== 'pending_school') return sendJSON(res, 409, { error: '当前阶段无法退回' });
      } else {
        return sendJSON(res, 400, { error: '未知签字角色' });
      }
      f.status = 'returned';
      f.returnedBy = role === 'supervisor' ? '主管' : '校方';
      f.returnReason = b.returnReason || '';
      f.returnedAt = Date.now();
      f.updatedAt = Date.now();
      saveForm(f);
      return sendJSON(res, 200, { ok: true, status: f.status, statusText: STATUS_TEXT[f.status], returnedBy: f.returnedBy });
    }
    if (role === 'supervisor') {
      if (f.status !== 'pending_supervisor') return sendJSON(res, 409, { error: '当前阶段无需主管签字或已签字' });
      if (!b.sig) return sendJSON(res, 400, { error: '请先手写签字' });
      f.supervisorSig = b.sig; f.supervisorSigner = b.signerName || '主管'; f.supervisorSignedAt = Date.now();
      f.status = 'pending_school';
    } else if (role === 'school') {
      if (f.status !== 'pending_school') return sendJSON(res, 409, { error: '当前阶段无需校方签字或已签字' });
      if (!f.supervisorSignedAt) return sendJSON(res, 409, { error: '请先由主管签字' });
      if (!b.sig) return sendJSON(res, 400, { error: '请先手写签字' });
      f.schoolSig = b.sig; f.schoolSigner = b.signerName || '校方'; f.schoolSignedAt = Date.now();
      f.status = 'completed';
    } else {
      return sendJSON(res, 400, { error: '未知签字角色' });
    }
    f.updatedAt = Date.now();
    saveForm(f);
    return sendJSON(res, 200, { ok: true, status: f.status, statusText: STATUS_TEXT[f.status] });
  }

  // ---- 财务后台：校验密钥 ----
  function adminGuard() {
    const cfg = getConfig();
    const key = urlObj.searchParams.get('adminKey') || '';
    if (key !== cfg.adminKey) return false;
    return true;
  }

  // ---- 附件读取（需管理密钥 / 签字令牌 / 本人登录态之一）----
  if (seg[0] === 'file' && method === 'GET' && seg.length === 3) {
    const f = loadForm(seg[1]);
    if (!f) return sendJSON(res, 404, { error: '附件不存在' });
    const att = (f.attachments || []).find((a) => a.id === seg[2]);
    if (!att) return sendJSON(res, 404, { error: '附件不存在' });
    const key = urlObj.searchParams.get('adminKey') || '';
    const tk = urlObj.searchParams.get('token') || urlObj.searchParams.get('auth') || '';
    let allowed = !!key && key === getConfig().adminKey;
    if (!allowed && tk) {
      if (tk === f.supervisorToken || tk === f.schoolToken) allowed = true;
      else {
        const u = getSessionUser(tk);
        if (u && u.id === f.ownerId) allowed = true;
      }
    }
    if (!allowed) return sendJSON(res, 403, { error: '无权访问该附件' });
    const ext = att.ext && ATT_MIME_BY_EXT[att.ext] ? att.ext : '';
    const fp = path.join(UPLOADS_DIR, seg[1], att.id + ext);
    if (!ext || !fs.existsSync(fp)) return sendJSON(res, 404, { error: '附件不存在' });
    const buf = fs.readFileSync(fp);
    res.writeHead(200, {
      'Content-Type': ATT_MIME_BY_EXT[ext],
      'Content-Length': buf.length,
      'Content-Disposition': 'inline; filename="' + encodeURIComponent(att.name || 'attachment') + '"',
      'Cache-Control': 'private, max-age=3600',
    });
    return res.end(buf);
  }

  // ---- 财务后台：全部退费单 ----
  if (seg[0] === 'admin' && seg[1] === 'forms' && method === 'GET') {
    if (!adminGuard()) return sendJSON(res, 401, { error: '管理密码错误' });
    const status = urlObj.searchParams.get('status') || '';
    const q = (urlObj.searchParams.get('q') || '').trim().toLowerCase();
    let list = fs.readdirSync(FORMS_DIR)
      .filter((f) => f.endsWith('.json'))
      .map((f) => loadForm(f.replace('.json', '')))
      .filter(Boolean)
      .sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0));
    if (status) list = list.filter((f) => f.status === status);
    if (q) list = list.filter((f) => formSearchText(f).includes(q));
    return sendJSON(res, 200, { forms: list.map((f) => adminSummary(f)), statusText: STATUS_TEXT });
  }

  // ---- 财务后台：补填退费方式 / 退款日期（双方签字完成后实际退款时填写）----
  if (seg[0] === 'admin' && seg[1] === 'forms' && seg[3] === 'refund' && method === 'POST' && seg.length === 4) {
    const b = await readBody(req);
    const key = urlObj.searchParams.get('adminKey') || b.adminKey || '';
    if (key !== getConfig().adminKey) return sendJSON(res, 401, { error: '管理密码错误' });
    const f = loadForm(seg[2]);
    if (!f) return sendJSON(res, 404, { error: '未找到该退费单' });
    if (f.status !== 'completed') return sendJSON(res, 409, { error: '需主管与校方双方签字完成后，才能登记退费信息' });
    const method2 = String(b.refundMethod || '').trim();
    const date2 = String(b.refundDate || '').trim();
    if (!method2) return sendJSON(res, 400, { error: '请选择退费方式' });
    if (!date2) return sendJSON(res, 400, { error: '请填写退款日期' });
    f.refundMethod = method2;
    f.refundDate = date2;
    f.refundNote = String(b.refundNote || '').trim();
    f.refundFilledAt = Date.now();
    f.updatedAt = Date.now();
    saveForm(f);
    return sendJSON(res, 200, { ok: true, form: adminSummary(f) });
  }

  // ---- 财务后台：全量备份（迁移用；含完整单据、账号哈希与附件，导出文件须妥善保管）----
  if (seg[0] === 'admin' && seg[1] === 'backup' && method === 'GET' && seg.length === 2) {
    if (!adminGuard()) return sendJSON(res, 401, { error: '管理密码错误' });
    const includeFiles = urlObj.searchParams.get('includeFiles') !== '0';
    const forms = fs.readdirSync(FORMS_DIR)
      .filter((f) => f.endsWith('.json'))
      .map((f) => loadForm(f.replace('.json', '')))
      .filter(Boolean);
    const attachments = [];
    if (includeFiles) {
      for (const f of forms) {
        for (const a of (f.attachments || [])) {
          const ext = a.ext && ATT_MIME_BY_EXT[a.ext] ? a.ext : '';
          if (!ext) continue;
          const fp = path.join(UPLOADS_DIR, f.id, a.id + ext);
          if (!fs.existsSync(fp)) continue;
          attachments.push({
            formId: f.id, id: a.id, ext,
            name: a.name || '附件', type: a.type || ATT_MIME_BY_EXT[ext],
            size: a.size || 0, dataBase64: fs.readFileSync(fp).toString('base64'),
          });
        }
      }
    }
    return sendJSON(res, 200, {
      version: 1,
      exportedAt: new Date().toISOString(),
      forms,
      users: loadUsers(),
      config: getConfig(),
      attachments,
    });
  }

  // ---- 财务后台：导出 CSV ----
  if (seg[0] === 'admin' && seg[1] === 'export' && method === 'GET') {
    if (!adminGuard()) return sendJSON(res, 401, { error: '管理密码错误' });
    const status = urlObj.searchParams.get('status') || '';
    let list = fs.readdirSync(FORMS_DIR)
      .filter((f) => f.endsWith('.json'))
      .map((f) => loadForm(f.replace('.json', '')))
      .filter(Boolean)
      .sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0));
    if (status) list = list.filter((f) => f.status === status);
    const header = ['单号', '明细序号', '学生姓名', '所在班级', '入校就读时间', '课程名称', '学费', '餐费', '退费总金额',
      '收款户名', '退费原因', '本单合计', '明细条数', '填报人', '填报时间', '附件数', '状态',
      '退费方式', '退款日期', '财务填写时间', '财务备注',
      '主管签字人', '主管签字时间', '校方签字人', '校方签字时间', '退回人', '退回原因'];
    const rows = [];
    list.forEach((f) => {
      (f.items || []).forEach((it, i) => {
        rows.push([
          f.id, i + 1, it.studentName, it.className, it.enrollDate, it.courseName, it.tuitionFee, it.mealFee, it.refundTotal,
          it.payeeName, it.refundReason,
          i === 0 ? f.totalAmount : '', i === 0 ? (f.items || []).length : '',
          i === 0 ? (f.submitterName || f.ownerName) : '', i === 0 ? fmtTime(f.createdAt) : '',
          i === 0 ? (f.attachments || []).length : '', i === 0 ? (STATUS_TEXT[f.status] || f.status) : '',
          i === 0 ? f.refundMethod : '', i === 0 ? f.refundDate : '', i === 0 ? fmtTime(f.refundFilledAt) : '',
          i === 0 ? f.refundNote : '',
          i === 0 ? f.supervisorSigner : '', i === 0 ? fmtTime(f.supervisorSignedAt) : '',
          i === 0 ? f.schoolSigner : '', i === 0 ? fmtTime(f.schoolSignedAt) : '',
          i === 0 ? f.returnedBy : '', i === 0 ? f.returnReason : '',
        ]);
      });
    });
    const csv = [header, ...rows].map((r) => r.map(csvCell).join(',')).join('\r\n');
    res.writeHead(200, {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': 'attachment; filename="refund_export.csv"',
    });
    // BOM 让 Excel 正确识别 UTF-8
    res.end('﻿' + csv);
    return;
  }

  // ---- 财务后台：统计 ----
  if (seg[0] === 'admin' && seg[1] === 'stats' && method === 'GET') {
    if (!adminGuard()) return sendJSON(res, 401, { error: '管理密码错误' });
    const all = fs.readdirSync(FORMS_DIR).filter((f) => f.endsWith('.json')).map((f) => loadForm(f.replace('.json', ''))).filter(Boolean);
    const stats = {
      total: all.length,
      pending_supervisor: all.filter((f) => f.status === 'pending_supervisor').length,
      pending_school: all.filter((f) => f.status === 'pending_school').length,
      completed: all.filter((f) => f.status === 'completed').length,
      revoked: all.filter((f) => f.status === 'revoked').length,
      returned: all.filter((f) => f.status === 'returned').length,
      totalItems: all.reduce((s, f) => s + (f.items || []).length, 0),
      totalAmount: round2(all.reduce((s, f) => s + (Number(f.totalAmount) || 0), 0)),
    };
    return sendJSON(res, 200, { stats });
  }

  // ---- 财务后台：微信登录设置（读）----
  if (seg[0] === 'admin' && seg[1] === 'wechat' && method === 'GET' && seg.length === 2) {
    if (!adminGuard()) return sendJSON(res, 401, { error: '管理密码错误' });
    const wx = getWx();
    return sendJSON(res, 200, {
      appId: wx.appId,
      hasSecret: !!wx.appSecret,
      configured: wx.configured,
      nameLogin: wx.nameLogin,
      nameLoginNeedPhone4: wx.nameLoginNeedPhone4,
      callbackUrl: getOrigin(req, urlObj) + '/api/auth/wechat/callback',
      publicBaseUrl: getConfig().publicBaseUrl || '',
      verifyFiles: Object.keys(wx.verifyFiles),
    });
  }

  // ---- 财务后台：微信登录设置（写）----
  if (seg[0] === 'admin' && seg[1] === 'wechat' && method === 'POST' && seg.length === 2) {
    const b = await readBody(req);
    const cfg = getConfig();
    const key = urlObj.searchParams.get('adminKey') || b.adminKey || '';
    if (key !== cfg.adminKey) return sendJSON(res, 401, { error: '管理密码错误' });
    const patch = {};
    if (b.appId !== undefined) patch.appId = String(b.appId).trim();
    if (b.appSecret) patch.appSecret = String(b.appSecret).trim();
    if (b.clearSecret) patch.appSecret = '';
    if (b.nameLogin !== undefined) patch.nameLogin = !!b.nameLogin;
    if (b.nameLoginNeedPhone4 !== undefined) patch.nameLoginNeedPhone4 = !!b.nameLoginNeedPhone4;
    saveWx(patch);
    if (b.publicBaseUrl !== undefined) {
      const base = String(b.publicBaseUrl).trim().replace(/\/+$/, '');
      if (base && !/^https?:\/\/[^\s]+$/i.test(base)) return sendJSON(res, 400, { error: '应用公网地址需以 http:// 或 https:// 开头' });
      const c = getConfig();
      c.publicBaseUrl = base;
      writeJSON(CONFIG_FILE, c);
    }
    const wx = getWx();
    return sendJSON(res, 200, {
      ok: true, configured: wx.configured, appId: wx.appId, hasSecret: !!wx.appSecret,
      nameLogin: wx.nameLogin, nameLoginNeedPhone4: wx.nameLoginNeedPhone4,
    });
  }

  // ---- 财务后台：公众号域名校验文件托管 ----
  if (seg[0] === 'admin' && seg[1] === 'wechat' && seg[2] === 'verify-file' && method === 'POST') {
    const b = await readBody(req);
    const cfg = getConfig();
    const key = urlObj.searchParams.get('adminKey') || b.adminKey || '';
    if (key !== cfg.adminKey) return sendJSON(res, 401, { error: '管理密码错误' });
    const vf = Object.assign({}, getWx().verifyFiles);
    if (b.remove) {
      delete vf[String(b.remove)];
    } else {
      const name = String(b.filename || '').trim();
      if (!/^[A-Za-z0-9_.-]{1,80}\.txt$/.test(name)) return sendJSON(res, 400, { error: '文件名需为 .txt，例如 MP_verify_abc123.txt' });
      const content = String(b.content || '').trim();
      if (!content) return sendJSON(res, 400, { error: '请填写校验文件内容' });
      vf[name] = content;
    }
    saveWx({ verifyFiles: vf });
    return sendJSON(res, 200, { ok: true, verifyFiles: Object.keys(vf) });
  }

  return sendJSON(res, 404, { error: '接口不存在' });
}

function csvCell(v) {
  const s = v === undefined || v === null ? '' : String(v);
  return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}
function formSearchText(f) {
  const parts = [f.id, f.submitterName, f.ownerName, f.refundMethod, f.refundDate];
  (f.items || []).forEach((it) => {
    parts.push(it.studentName, it.className, it.courseName, it.payeeName, it.refundReason);
  });
  return parts.join(' ').toLowerCase();
}
function fmtTime(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
function attSummary(f) {
  return (f.attachments || []).map((a) => ({ id: a.id, name: a.name, type: a.type, size: a.size, ext: a.ext }));
}
function publicSummary(f) {
  const items = f.items || [];
  const first = items[0] || {};
  return {
    id: f.id,
    itemCount: items.length,
    studentName: (first.studentName || '') + (items.length > 1 ? ' 等 ' + items.length + ' 人' : ''),
    className: first.className || '',
    refundTotal: f.totalAmount,
    submitterName: f.submitterName || f.ownerName || '',
    status: f.status, statusText: STATUS_TEXT[f.status] || f.status,
    ownerName: f.ownerName, createdAt: f.createdAt,
    refundMethod: f.refundMethod || '', refundDate: f.refundDate || '',
    attachmentCount: (f.attachments || []).length,
    items: items.map((it) => ({
      studentName: it.studentName, className: it.className, refundTotal: it.refundTotal,
    })),
  };
}
function adminSummary(f) {
  // 财务后台可见：含退费明细与签字人信息
  return Object.assign(publicSummary(f), {
    submitterName: f.submitterName || f.ownerName || '',
    refundFilledAt: f.refundFilledAt || 0, refundNote: f.refundNote || '',
    attachments: attSummary(f),
    supervisorSigner: f.supervisorSigner, supervisorSignedAt: f.supervisorSignedAt,
    schoolSigner: f.schoolSigner, schoolSignedAt: f.schoolSignedAt,
    supervisorSig: f.supervisorSig, schoolSig: f.schoolSig,
    returnReason: f.returnReason, returnedBy: f.returnedBy,
  });
}
function publicForm(f) {
  // 签字页只读展示字段
  return {
    id: f.id, submitterName: f.submitterName || f.ownerName || '', createdAt: f.createdAt,
    items: (f.items || []).map((it) => ({
      studentName: it.studentName, className: it.className, enrollDate: it.enrollDate,
      courseName: it.courseName, tuitionFee: it.tuitionFee, mealFee: it.mealFee,
      refundTotal: it.refundTotal, payeeName: it.payeeName, refundReason: it.refundReason,
    })),
    totalAmount: f.totalAmount,
    refundMethod: f.refundMethod, refundDate: f.refundDate,
    status: f.status, statusText: STATUS_TEXT[f.status] || f.status,
    attachments: attSummary(f),
    supervisorSigner: f.supervisorSigner, supervisorSignedAt: f.supervisorSignedAt, supervisorSig: f.supervisorSig,
    schoolSigner: f.schoolSigner, schoolSignedAt: f.schoolSignedAt, schoolSig: f.schoolSig,
    returnReason: f.returnReason, returnedBy: f.returnedBy,
  };
}

// ---------- 静态文件 ----------
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'application/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.png': 'image/png', '.svg': 'image/svg+xml' };
function serveStatic(req, res, urlObj) {
  // 公众号「网页授权域名」校验文件：/MP_verify_xxx.txt 直接由配置返回
  const mp = urlObj.pathname.match(/^\/(MP_verify_[A-Za-z0-9_-]+\.txt)$/);
  if (mp) {
    const vf = getWx().verifyFiles;
    if (vf[mp[1]]) {
      res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
      return res.end(vf[mp[1]]);
    }
  }
  let p = urlObj.pathname;
  if (p === '/' || p === '') p = '/index.html';
  const file = path.join(ROOT, 'public', path.normalize(p).replace(/^(\.\.[/\\])+/, ''));
  if (!file.startsWith(path.join(ROOT, 'public'))) { res.writeHead(403); return res.end('forbidden'); }
  if (!fs.existsSync(file)) { // SPA 回退
    const idx = path.join(ROOT, 'public', 'index.html');
    res.writeHead(200, { 'Content-Type': MIME['.html'] });
    return res.end(fs.readFileSync(idx));
  }
  const ext = path.extname(file);
  res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' });
  res.end(fs.readFileSync(file));
}

// ---------- 启动 ----------
ensureDirs();
getConfig();
const server = http.createServer(async (req, res) => {
  try {
    let urlObj = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
    // Nginx 把 /refund/ 反向代理到本服务时，先剥掉前缀再进入原有路由分发。
    if (BASE_PATH && (urlObj.pathname === BASE_PATH || urlObj.pathname.startsWith(BASE_PATH + '/'))) {
      req.url = req.url.slice(BASE_PATH.length) || '/';
      urlObj = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
    }
    if (urlObj.pathname.startsWith('/api/')) {
      await handleApi(req, res, urlObj);
    } else {
      serveStatic(req, res, urlObj);
    }
  } catch (e) {
    sendJSON(res, 500, { error: '服务器内部错误', detail: String(e && e.message || e) });
  }
});
server.listen(PORT, '0.0.0.0', () => {
  console.log(`学校退费收款单 已启动： http://localhost:${PORT}`);
  console.log('手机/电脑在同一网络下访问本机 IP 即可使用（如 http://<本机IP>:${PORT}）');
});
