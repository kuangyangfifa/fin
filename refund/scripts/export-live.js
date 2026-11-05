#!/usr/bin/env node
'use strict';
/**
 * 从运行中的退费模块导出全量数据，用于迁移到自有服务器。
 *
 * 用法：
 *   node scripts/export-live.js --url "https://xxx/?sharecode=XXX" --key "财务后台密码" --out ./backup.json
 *
 * 可选参数：
 *   --api-base /refund   同域子路径部署时指定；默认按入口 URL 自动判断
 *   --no-files           不导出附件（仅单据与账号）
 *
 * 前提：目标站点须已运行包含 GET /api/admin/backup 的版本。
 * 若目标是旧版托管站点（无该接口），请先发布一次新版 server.js，
 * 或改用 import-backup.js --dir 直接导入平台导出的 data 目录。
 */
const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');

function arg(name, def) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 && process.argv[i + 1] && !process.argv[i + 1].startsWith('--')
    ? process.argv[i + 1] : def;
}

function request(urlStr, options) {
  const opts = options || {};
  return new Promise((resolve, reject) => {
    const u = new URL(urlStr);
    const lib = u.protocol === 'https:' ? https : http;
    const req = lib.request(u, { method: opts.method || 'GET', headers: opts.headers || {} }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const code = res.statusCode;
        if ([301, 302, 303, 307, 308].indexOf(code) >= 0 && res.headers.location && (opts.redirects || 0) < 3) {
          const next = new URL(res.headers.location, u).toString();
          resolve(request(next, Object.assign({}, opts, { redirects: (opts.redirects || 0) + 1 })));
          return;
        }
        resolve({ status: code, headers: res.headers, body: Buffer.concat(chunks) });
      });
    });
    req.on('error', reject);
    req.setTimeout(120000, () => req.destroy(new Error('请求超时')));
    req.end();
  });
}

function cookieHeader(setCookie) {
  if (!setCookie) return '';
  return (Array.isArray(setCookie) ? setCookie : [setCookie])
    .map((s) => String(s).split(';')[0]).join('; ');
}

async function main() {
  const entry = arg('url');
  const key = arg('key');
  if (!entry || !key) {
    console.error('缺少参数。示例：node scripts/export-live.js --url "https://xxx/?sharecode=XXX" --key "管理密码" --out ./backup.json');
    process.exit(1);
  }
  const entryUrl = new URL(entry);
  const out = path.resolve(arg('out', 'refund-backup-' + new Date().toISOString().slice(0, 10) + '.json'));
  const autoBase = /\/(index\.html)?$/.test(entryUrl.pathname)
    && entryUrl.pathname.replace(/\/(index\.html)?$/, '').endsWith('/refund') ? '/refund' : '';
  const apiBase = arg('api-base', autoBase).replace(/\/+$/, '');
  const withFiles = process.argv.indexOf('--no-files') < 0;
  const ua = { 'User-Agent': 'fin-remark-migrate/1.0' };

  // 托管平台靠首次访问写入的 Cookie 续期，先预热门户再调用接口。
  const warm = await request(entry, { headers: ua });
  const cookie = cookieHeader(warm.headers['set-cookie']);
  console.log('预热入口：HTTP ' + warm.status + (cookie ? '（已取得访问 Cookie）' : ''));

  const api = new URL(apiBase + '/api/admin/backup?adminKey=' + encodeURIComponent(key)
    + '&includeFiles=' + (withFiles ? '1' : '0'), entryUrl.origin).toString();
  const r = await request(api, { headers: Object.assign({}, ua, cookie ? { Cookie: cookie } : {}) });
  if (r.status !== 200) {
    throw new Error('备份接口返回 HTTP ' + r.status + '：' + r.body.toString('utf8').slice(0, 200));
  }
  let data;
  try {
    data = JSON.parse(r.body.toString('utf8'));
  } catch (e) {
    throw new Error('返回内容不是合法 JSON，可能被平台登录页拦截，或目标站点仍是旧版（无 /api/admin/backup）');
  }
  if (data.version !== 1 || !Array.isArray(data.forms)) {
    throw new Error('备份数据格式不符合预期（version 应为 1）');
  }
  fs.writeFileSync(out, JSON.stringify(data), 'utf8');
  console.log('导出完成：' + data.forms.length + ' 张单据、'
    + Object.keys(data.users || {}).length + ' 个账号、'
    + (data.attachments || []).length + ' 个附件');
  console.log('备份文件（含口令与附件，请妥善保管）：' + out);
}

main().catch((e) => {
  console.error('导出失败：' + e.message);
  process.exit(1);
});
