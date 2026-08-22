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
      fetch(config.apiBase + path, {
        method: options.method || 'GET',
        headers: headers,
        body: options.data ? JSON.stringify(options.data) : undefined
      }).then((resp) => {
        return resp.json().then((data) => {
          if (resp.status === 200 && data && data.code === 0) {
            resolve(data.data);
          } else {
            reject(data || { message: '请求失败' });
          }
        });
      }).catch((err) => reject(err));
    });
  };

  // 登录接口本身不需要等 authReady；其余接口先等免登完成，避免 401
  if (path === '/api/auth/login') {
    return doRequest();
  }
  return ensureAuth().then(doRequest);
}

module.exports = { request };
