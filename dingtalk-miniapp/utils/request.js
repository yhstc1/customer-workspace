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
      const url = config.apiBase + path;
      const headers = Object.assign(
        { 'Content-Type': 'application/json' },
        options.headers || {},
        token ? { 'Authorization': 'Bearer ' + token } : {}
      );

      // 业务请求给足 30s：后端可能调外部服务（钉钉/腾讯地图），不要设太短
      let settled = false;
      const timer = setTimeout(() => {
        if (!settled) {
          settled = true;
          reject({ message: '请求超时(30s)：后端响应过慢或网络异常，请切换网络后重试' });
        }
      }, 30000);

      const finish = (fn, val) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        fn(val);
      };

      const handleRes = (res, source) => {
        console.log('[request]', source, path, res);
        // dd.request dataType:'json' 时 res.data 是后端返回对象
        const data = (res && res.data) || null;
        if (res && res.status === 200 && data && data.code === 0) {
          finish(resolve, data.data);
        } else {
          finish(reject, data || { message: '请求失败' });
        }
      };

      // 方案 A：dd.request
      if (typeof dd.request === 'function') {
        dd.request({
          url: url,
          method: options.method || 'GET',
          headers: headers,
          data: options.data || {},
          dataType: 'json',
          success: (res) => handleRes(res, 'dd.request'),
          fail: (err) => {
            console.error('[request] dd.request fail', path, err);
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
          return resp.text().then((text) => {
            let data = null;
            try { data = text ? JSON.parse(text) : {}; } catch (e) { data = { message: '响应解析失败: ' + text }; }
            handleRes({ status: resp.status, data: data }, 'fetch');
          });
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
