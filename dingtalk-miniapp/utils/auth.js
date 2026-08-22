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
      },
      fail: reject
    });
  });
}

module.exports = { login };
