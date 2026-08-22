const config = require('../config.js');

function ensureAuth() {
  const app = getApp ? getApp() : null;
  if (!app || !app.globalData || !app.globalData.authReady) {
    return Promise.resolve();
  }
  return app.globalData.authReady;
}

// 统一请求封装：自动带登录态、标准化返回
function request(path, options = {}) {
  const doRequest = () => {
    const cached = dd.getStorageSync({ key: 'sessionToken' });
    const token = (cached && cached.data) || '';
    if (!token && path !== '/api/auth/login') {
      return Promise.reject({ message: '未登录' });
    }
    return new Promise((resolve, reject) => {
      // 同 auth.js：鸿蒙真机 dd.httpRequest 会被客户端拦截(error 14)，统一改用 fetch
      const headers = Object.assign(
        { 'Content-Type': 'application/json' },
        options.headers || {},
        token ? { 'Authorization': 'Bearer ' + token } : {}
      );
      // 超时保护：鸿蒙 fetch 偶发不触发 resolve/reject 导致页面永久 loading
      let settled = false;
      const timer = setTimeout(() => {
        if (!settled) { settled = true; reject({ message: '请求超时(10s)' }); }
      }, 10000);
      const finish = (fn, val) => {
        if (settled) return;
        settled = true; clearTimeout(timer); fn(val);
      };
      fetch(config.apiBase + path, {
        method: options.method || 'GET',
        headers: headers,
        body: options.data ? JSON.stringify(options.data) : undefined
      }).then((resp) => {
        // 先读 text 再 JSON.parse，避免 resp.json() 在异常 body 下静默挂起
        return resp.text().then((text) => {
          let data = null;
          try { data = text ? JSON.parse(text) : {}; } catch (e) { data = { message: '响应解析失败: ' + text }; }
          if (resp.status === 200 && data && data.code === 0) {
            finish(resolve, data.data);
          } else {
            finish(reject, data || { message: '请求失败' });
          }
        });
      }).catch((err) => finish(reject, err));
    });
  };

  // 登录接口本身不需要等 authReady；其余接口先等免登完成，避免 401
  if (path === '/api/auth/login') {
    return doRequest();
  }
  return ensureAuth().then(doRequest);
}

module.exports = { request };
