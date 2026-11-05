#!/usr/bin/env node
'use strict';
/**
 * 把退费模块的全量备份导入到指定数据目录（离线执行，不经过 HTTP）。
 *
 * 用法：
 *   node scripts/import-backup.js --backup ./backup.json --data /home/fin/data/refund
 *   node scripts/import-backup.js --dir   ./data          --data /home/fin/data/refund
 *
 * 可选参数：
 *   --public-base-url https://域名/refund   写入 config.json 的对外地址；默认留空，由服务端按请求 Host 推导
 *   --overwrite                            覆盖同单号的既有单据（默认跳过）
 *   环境变量 REFUND_DATA_DIR               可代替 --data
 *
 * 说明：会话令牌不迁移，老师需重新登录；config.seq 会保留，避免新单号与历史单据冲突。
 */
const fs = require('fs');
const path = require('path');

const EXT_OK = { '.jpg': 1, '.png': 1, '.webp': 1, '.gif': 1, '.pdf': 1 };

function arg(name, def) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 && process.argv[i + 1] && !process.argv[i + 1].startsWith('--')
    ? process.argv[i + 1] : def;
}
function safeId(s) { return /^[A-Za-z0-9_-]+$/.test(String(s || '')); }
function readJSON(p, fallback) {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (e) { return fallback; }
}
function writeJSON(p, obj) {
  fs.writeFileSync(p + '.tmp', JSON.stringify(obj, null, 2), 'utf8');
  fs.renameSync(p + '.tmp', p);
}
function copyDir(src, dst) {
  if (!fs.existsSync(src)) return 0;
  fs.mkdirSync(dst, { recursive: true });
  let n = 0;
  for (const e of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, e.name), d = path.join(dst, e.name);
    if (e.isDirectory()) n += copyDir(s, d);
    else { fs.copyFileSync(s, d); n += 1; }
  }
  return n;
}

function main() {
  const backupFile = arg('backup');
  const srcDir = arg('dir');
  if (!backupFile && !srcDir) {
    console.error('缺少参数：请指定 --backup <备份.json> 或 --dir <原 data 目录>');
    process.exit(1);
  }
  const dataDir = path.resolve(arg('data', process.env.REFUND_DATA_DIR || path.join(__dirname, '..', 'data')));
  const overwrite = process.argv.indexOf('--overwrite') >= 0;
  const publicBaseUrl = arg('public-base-url', '');
  const formsDir = path.join(dataDir, 'forms');
  const uploadsDir = path.join(dataDir, 'uploads');
  fs.mkdirSync(formsDir, { recursive: true });
  fs.mkdirSync(uploadsDir, { recursive: true });

  let forms = [], users = null, config = null, attachments = [], copiedFiles = 0;

  if (backupFile) {
    const data = readJSON(path.resolve(backupFile), null);
    if (!data || data.version !== 1 || !Array.isArray(data.forms)) {
      throw new Error('备份文件无效：version 应为 1 且包含 forms 数组');
    }
    forms = data.forms;
    users = data.users || null;
    config = data.config || null;
    attachments = data.attachments || [];
  } else {
    const root = path.resolve(srcDir);
    const srcForms = path.join(root, 'forms');
    if (fs.existsSync(srcForms)) {
      for (const f of fs.readdirSync(srcForms).filter((x) => x.endsWith('.json'))) {
        const obj = readJSON(path.join(srcForms, f), null);
        if (obj && obj.id) forms.push(obj);
      }
    }
    users = readJSON(path.join(root, 'users.json'), null);
    config = readJSON(path.join(root, 'config.json'), null);
    copiedFiles = copyDir(path.join(root, 'uploads'), uploadsDir);
  }

  let written = 0, skipped = 0, invalid = 0;
  for (const f of forms) {
    if (!safeId(f.id)) { invalid += 1; continue; }
    const dest = path.join(formsDir, f.id + '.json');
    if (fs.existsSync(dest) && !overwrite) { skipped += 1; continue; }
    writeJSON(dest, f);
    written += 1;
  }

  for (const a of attachments) {
    if (!safeId(a.formId) || !safeId(a.id) || !EXT_OK[a.ext]) { invalid += 1; continue; }
    const dir = path.join(uploadsDir, a.formId);
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, a.id + a.ext), Buffer.from(a.dataBase64 || '', 'base64'));
    copiedFiles += 1;
  }

  const usersFile = path.join(dataDir, 'users.json');
  if (users && (!fs.existsSync(usersFile) || overwrite)) writeJSON(usersFile, users);
  const sessionsFile = path.join(dataDir, 'sessions.json');
  if (!fs.existsSync(sessionsFile)) writeJSON(sessionsFile, {});

  const cfgFile = path.join(dataDir, 'config.json');
  if (config) {
    // 旧托管平台地址必须清除，否则签字链接与微信回调仍指向旧域名。
    const oldBase = config.publicBaseUrl || '';
    config.publicBaseUrl = publicBaseUrl;
    writeJSON(cfgFile, config);
    if (oldBase) console.log('已清除旧对外地址：' + oldBase);
  } else if (!fs.existsSync(cfgFile)) {
    writeJSON(cfgFile, { seq: 0, wechat: { nameLogin: true, nameLoginNeedPhone4: true }, publicBaseUrl: publicBaseUrl });
    console.log('注意：备份中无 config.json，已生成空配置；财务后台密码将在服务首次启动时随机生成并打印到日志。');
  }
  if (publicBaseUrl) console.log('已写入对外地址：' + publicBaseUrl);

  console.log('导入完成 → ' + dataDir);
  console.log('  单据：写入 ' + written + ' 张，跳过已存在 ' + skipped + ' 张，非法跳过 ' + invalid + ' 条');
  console.log('  附件：' + copiedFiles + ' 个');
  console.log('  账号：' + (users ? Object.keys(users).length + ' 个（会话不迁移，需重新登录）' : '未导入'));
  console.log('后续：确认 config.json 的 adminKey，重启退费模块服务后进入后台核对单据与统计。');
}

try {
  main();
} catch (e) {
  console.error('导入失败：' + e.message);
  process.exit(1);
}
