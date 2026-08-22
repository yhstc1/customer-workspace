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
      dd.httpRequest({
        url: config.apiBase + path,
        method: options.method || 'GET',
        headers: Object.assign(
          { 'Content-Type': 'application/json' },
          options.headers || {},
          token ? { 'Authorization': 'Bearer ' + token } : {}
        ),
        data: options.data || {},
        success: (res) => {
          if (res.status === 200 && res.data && res.data.code === 0) {
            resolve(res.data.data);
          } else {
            reject(res.data || { message: '请求失败' });
          }
        },
        fail: (err) => reject(err)
      });
    });
  };

  // 登录接口本身不需要等 authReady；其余接口先等免登完成，避免 401
  if (path === '/api/auth/login') {
    return doRequest();
  }
  return ensureAuth().then(doRequest);
}

module.exports = { request };
