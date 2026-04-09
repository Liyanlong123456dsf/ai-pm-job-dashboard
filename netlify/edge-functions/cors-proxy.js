/**
 * Netlify Edge Function — 为 /api/* 路径添加 CORS 支持
 * 
 * - OPTIONS 预检请求 → 直接返回 204 + CORS 头
 * - 其他请求 → 继续走 netlify.toml 的 rewrite 规则，再追加 CORS 头
 * 
 * 这样 GitHub Pages 等外部域名也能调用 Netlify 代理的 API
 */
export default async (request, context) => {
  const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': '*',
    'Access-Control-Max-Age': '86400',
  };

  // CORS preflight
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  // 继续走下游（rewrite 规则代理到 Kimi/Coze API）
  const response = await context.next();

  // 给代理响应追加 CORS 头
  const newResponse = new Response(response.body, response);
  Object.entries(corsHeaders).forEach(([k, v]) => newResponse.headers.set(k, v));

  return newResponse;
};
