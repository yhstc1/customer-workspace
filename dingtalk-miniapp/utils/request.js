const config = require('../config.js');

// 统一请求封装：自动带登录态、标准化返回
function request(path, options = {}) {
  const cached = dd.getStorageSync({ key: 'sessionToken' });
  const token = (cached && cached.data) || '';
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
}

module.exports = { request };
