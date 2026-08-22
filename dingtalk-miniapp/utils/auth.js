const config = require('../config.js');

// 兼容不同钉钉小程序运行时：
// - 开发者工具模拟器用 dd.requestAuthCode
// - 真机用 dd.getAuthCode
function getAuthCode() {
  return new Promise((resolve, reject) => {
    const opts = {
      corpId: config.corpId,
      success: (res) => resolve(res.authCode || res.code),
      fail: (err) => reject(err)
    };
    if (typeof dd.requestAuthCode === 'function') {
      dd.requestAuthCode(opts);
    } else if (typeof dd.getAuthCode === 'function') {
      dd.getAuthCode(opts);
    } else {
      reject({ message: '当前环境不支持钉钉免登' });
    }
  });
}

// 钉钉免登：拿 authCode → 后端用 app access_token 换 userId
function login() {
  return new Promise((resolve, reject) => {
    getAuthCode().then((code) => {
      dd.httpRequest({
        url: config.apiBase + '/api/auth/login',
        method: 'POST',
        data: { authCode: code },
        success: (r) => {
          // 后端统一信封: { code:0, data:{ token, user:{ id,is_admin } } }
          if (r.status === 200 && r.data && r.data.code === 0 && r.data.data && r.data.data.token) {
            const payload = r.data.data;
            dd.setStorageSync({ key: 'sessionToken', value: payload.token });
            dd.setStorageSync({ key: 'userId', value: payload.user.id });
            resolve(payload.user);
          } else {
            const msg = (r.data && r.data.message) ? r.data.message : '免登失败';
            reject({ message: msg });
          }
        },
        fail: reject
      });
    }).catch(reject);
  });
}

module.exports = { login };
