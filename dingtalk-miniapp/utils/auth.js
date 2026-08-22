const config = require('../config.js');

// 钉钉免登：requestAuthCode 拿 authCode → 后端用 app access_token 换 userId
function login() {
  return new Promise((resolve, reject) => {
    dd.requestAuthCode({
      corpId: config.corpId,
      success: (res) => {
        dd.httpRequest({
          url: config.apiBase + '/api/auth/login',
          method: 'POST',
          data: { authCode: res.code },
          success: (r) => {
            // 后端返回结构: { token, user: { id, is_admin } }
            if (r.status === 200 && r.data && r.data.token) {
              dd.setStorageSync({ key: 'sessionToken', value: r.data.token });
              dd.setStorageSync({ key: 'userId', value: r.data.user.id });
              resolve(r.data.user);
            } else {
              reject(r.data || { message: '免登失败' });
            }
          },
          fail: reject
        });
      },
      fail: reject
    });
  });
}

module.exports = { login };
