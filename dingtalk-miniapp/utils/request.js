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
      // 鸿蒙真机网络请求策略：dd.request 优先，fetch 兜底，10s 超时保护
      const url = config.apiBase + path;
      const headers = Object.assign(
        { 'Content-Type': 'application/json' },
        options.headers || {},
        token ? { 'Authorization': 'Bearer ' + token } : {}
      );
      let settled = false;
      const timer = setTimeout(() => {
        if (!settled) { settled = true; reject({ message: '请求超时(10s)' }); }
      }, 10000);
      const finish = (fn, val) => {
        if (settled) return;
        settled = true; clearTimeout(timer); fn(val);
      };
      const handleRes = (status, bodyText, source) => {
        console.log('[request]', source, status, bodyText);
        let data = null;
        try { data = bodyText ? JSON.parse(bodyText) : {}; } catch (e) { data = { message: '响应解析失败: ' + bodyText }; }
        if (status === 200 && data && data.code === 0) {
          finish(resolve, data.data);
        } else {
          finish(reject, data || { message: '请求失败' });
        }
      };

      // 方案 A：dd.request（新 API，鸿蒙兼容更优）
      if (typeof dd.request === 'function') {
        dd.request({
          url: url,
          method: options.method || 'GET',
          headers: headers,
          data: options.data || {},
          dataType: 'json',
          success: (res) => {
            const status = (res && res.status) || 200;
            const body = res && res.data !== undefined ? JSON.stringify(res.data) : '';
            handleRes(status, body, 'dd.request');
          },
          fail: (err) => {
            console.error('[request] dd.request fail', err);
            tryFetch();
          }
        });
      } else {
        tryFetch();
      }

      function tryFetch() {
        fetch(url, {
          method: options.method || 'GET',
          headers: headers,
          body: options.data ? JSON.stringify(options.data) : undefined
        }).then((resp) => {
          return resp.text().then((text) => handleRes(resp.status, text, 'fetch'));
        }).catch((err) => finish(reject, err));
      }
    });
  };

  // 登录接口本身不需要等 authReady；其余接口先等免登完成，避免 401
  if (path === '/api/auth/login') {
    return doRequest();
  }
  return ensureAuth().then(doRequest);
}

module.exports = { request };
