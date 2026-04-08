/**
 * Cloudflare Worker - Kimi Code API CORS 代理
 * 
 * 部署步骤：
 * 1. 打开 https://workers.cloudflare.com → 注册/登录
 * 2. 创建 Worker → 粘贴本文件内容 → 保存并部署
 * 3. 记下 Worker URL（如 https://kimi-proxy.xxx.workers.dev）
 * 4. 在 Dashboard 设置里填入此 URL
 */

const KIMI_API = 'https://api.kimi.com/coding/v1/messages';

export default {
  async fetch(request) {
    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Headers': '*',
          'Access-Control-Allow-Methods': 'POST, OPTIONS',
        }
      });
    }

    if (request.method !== 'POST') {
      return new Response('Method not allowed', { status: 405 });
    }

    try {
      const body = await request.text();
      const resp = await fetch(KIMI_API, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-api-key': request.headers.get('x-api-key') || '',
          'anthropic-version': '2023-06-01',
        },
        body: body,
      });

      // 流式转发
      const newHeaders = new Headers(resp.headers);
      newHeaders.set('Access-Control-Allow-Origin', '*');
      newHeaders.set('Access-Control-Allow-Headers', '*');

      return new Response(resp.body, {
        status: resp.status,
        headers: newHeaders,
      });
    } catch (e) {
      return new Response(JSON.stringify({ error: e.message }), {
        status: 502,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
        }
      });
    }
  }
};
