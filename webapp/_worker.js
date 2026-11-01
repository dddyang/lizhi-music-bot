/**
 * 李志全集音乐 Mini App - Cloudflare Pages Advanced 边缘网关
 * 职责：
 * 1. 静态资源托管（HTML/CSS/JS/Cover 封面图）
 * 2. 边缘反向代理音频流（/stream/:id）发往软路由原生公网 IPv6
 * 3. 自动注入安全防伪暗号 X-Stream-Secret
 * 4. 全球边缘 CDN 自动缓存静态音频切片，实现万人并发毫秒级秒开
 */

const BACKEND_IPV6 = '240e:324:9c04:3491:ac95:67db:9406:67da';
const BACKEND_PORT = '8880';
const STREAM_SECRET = 'lizhi-sec-7f89d3a1c5b4e208';

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // 拦截流媒体音频请求 /stream/:id
    if (url.pathname.startsWith('/stream/')) {
      const pathParts = url.pathname.split('/').filter(Boolean);
      const songId = pathParts[1] || '1';

      // 目标公网 IPv6 软路由后端
      const targetUrl = `http://[${BACKEND_IPV6}]:${BACKEND_PORT}/stream/${songId}`;

      // 构造携带鉴权暗号的转发请求
      const forwardHeaders = new Headers(request.headers);
      forwardHeaders.set('X-Stream-Secret', STREAM_SECRET);
      forwardHeaders.set('Host', 'stream.lizhi.internal');

      try {
        const backendResp = await fetch(targetUrl, {
          method: request.method,
          headers: forwardHeaders,
        });

        // 构造返回给客户端播放器的响应头
        const respHeaders = new Headers(backendResp.headers);
        respHeaders.set('Access-Control-Allow-Origin', '*');
        respHeaders.set('Access-Control-Allow-Methods', 'GET, HEAD, OPTIONS');
        respHeaders.set('Access-Control-Allow-Headers', 'Range, Origin, Content-Type, Accept');
        respHeaders.set('Access-Control-Expose-Headers', 'Content-Range, Content-Length, Accept-Ranges');
        
        // 允许 Cloudflare 全球边缘节点长效缓存该音频切片
        respHeaders.set('Cache-Control', 'public, max-age=2592000, s-maxage=2592000, immutable');

        return new Response(backendResp.body, {
          status: backendResp.status,
          statusText: backendResp.statusText,
          headers: respHeaders,
        });
      } catch (err) {
        return new Response(JSON.stringify({
          error: 'Backend Stream Proxy Error',
          message: err.message,
          hint: '软路由流媒体服务可能正在重连中'
        }), {
          status: 502,
          headers: {
            'Content-Type': 'application/json; charset=utf-8',
            'Access-Control-Allow-Origin': '*'
          }
        });
      }
    }

    // 默认回源拉取 Cloudflare Pages 静态页面资产 (index.html / data.js / covers)
    return env.ASSETS.fetch(request);
  }
};
