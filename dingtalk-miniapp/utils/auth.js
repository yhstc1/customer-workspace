const config = require('../config.js');

// 兜底 corpId：防止开发者工具热重载/缓存导致 config.corpId 为空
const FALLBACK_CORP_ID = 'ding49b7555f7b0e7c421b9a8c00fa015bc5';

// 兼容不同钉钉小程序运行时：
// - 开发者工具模拟器用 dd.requestAuthCode
// - 真机用 dd.getAuthCode
function getAuthCode() {
  return new Promise((resolve, reject) => {
    const corpId = config.corpId || FALLBACK_CORP_ID;
    console.log('[auth] config.corpId=', config.corpId, 'useCorpId=', corpId);

    const call = (options) => {
      if (typeof dd.requestAuthCode === 'function') {
        dd.requestAuthCode(options);
      } else if (typeof dd.getAuthCode === 'function') {
        dd.getAuthCode(options);
      } else {
        reject({ message: '当前环境不支持钉钉免登' });
      }
    };

    // 第 1 次：带 corpId（标准文档写法）
    call({
      corpId: corpId,
      success: (res) => resolve(res.authCode || res.code),
      fail: (err) => {
        console.error('[auth] getAuthCode with corpId failed', err);
        // 第 2 次兜底：不带 corpId（部分真机版本/鸿蒙钉钉传 corpId 会报 14）
        call({
          success: (res) => resolve(res.authCode || res.code),
          fail: (err2) => {
            console.error('[auth] getAuthCode without corpId failed', err2);
            reject(wrapError('获取 authCode 失败', err2));
          }
        });
      }
    });
  });
}

// 统一错误包装：把钉钉 SDK / httpRequest 的原始错误完整保留
function wrapError(prefix, raw) {
  const keys = ['error', 'errorCode', 'errorMessage', 'errMsg', 'errCode', 'subError', 'subErrorCode', 'message'];
  const parts = [];
  keys.forEach((k) => {
    if (raw && raw[k] !== undefined) parts.push(k + '=' + String(raw[k]));
  });
  let detail = parts.length ? parts.join(' | ') : '';
  if (!detail) {
    if (typeof raw === 'string') detail = raw;
    else if (raw && raw.originData) detail = String(raw.originData);
    else detail = JSON.stringify(raw);
  }
  return { message: prefix + (detail ? ': ' + detail : ''), raw: raw };
}

// 后端登录：用 authCode 换 token
function exchangeToken(authCode) {
  return new Promise((resolve, reject) => {
    console.log('[auth] POST /api/auth/login authCode=', authCode ? (authCode.slice(0, 8) + '...') : 'EMPTY');
    dd.httpRequest({
      url: config.apiBase + '/api/auth/login',
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      dataType: 'json',
      data: { authCode: authCode },
      success: (r) => {
        console.log('[auth] /api/auth/login response', r.status, r.data);
        // 后端统一信封: { code:0, data:{ token, user:{ id,is_admin } } }
        if (r.status === 200 && r.data && r.data.code === 0 && r.data.data && r.data.data.token) {
          const payload = r.data.data;
          dd.setStorageSync({ key: 'sessionToken', value: payload.token });
          dd.setStorageSync({ key: 'userId', value: payload.user.id });
          resolve(payload.user);
        } else {
          const msg = (r.data && r.data.message) ? r.data.message : '免登失败';
          reject({ message: msg, raw: r.data });
        }
      },
      fail: (err) => {
        console.error('[auth] /api/auth/login fail', err);
        const errCode = String(err && (err.error !== undefined ? err.error : err.errorCode));
        // 钉钉真机 httpRequest 失败常见错误码：
        // error:4  = 网络请求被客户端拦截（request 合法域名未配置）
        // error:14 = 证书/HTTPS/安全策略问题，或域名未加白名单但校验更严格
        if (errCode === '4') {
          reject({
            message: '网络请求被拦截(错误码4)：请在小程序后台「开发设置→服务器域名→request合法域名」添加 ' + config.apiBase,
            raw: err
          });
        } else if (errCode === '14') {
          reject({
            message: '网络请求被拦截(错误码14)：可能原因：① HTTPS 证书链不完整；② 域名未加 request 白名单；③ 真机网络受限。请确认已在开放平台「开发设置→服务器域名」添加 ' + config.apiBase + '，并尝试切换 4G/5G 流量。',
            raw: err
          });
        } else {
          reject(wrapError('登录请求失败', err));
        }
      }
    });
  });
}

// 手动输入 authCode（仅模拟器开发调试）
function manualAuthCode() {
  return new Promise((resolve, reject) => {
    if (!config.enableManualAuthCode) {
      reject({ message: '未开启手动 authCode 调试模式' });
      return;
    }
    dd.prompt({
      title: '模拟器调试',
      message: '自动获取 authCode 失败，请手动输入从真机/开放平台拿到的 authCode',
      placeholder: '粘贴 authCode',
      buttonText: '登录',
      success: (res) => {
        const code = (res.value || '').trim();
        if (code) resolve(code);
        else reject({ message: '未输入 authCode' });
      },
      fail: () => reject({ message: '取消手动输入' })
    });
  });
}

// 钉钉免登：拿 authCode → 后端用 app access_token 换 userId
function login() {
  return new Promise((resolve, reject) => {
    getAuthCode().then((code) => {
      exchangeToken(code).then(resolve).catch(reject);
    }).catch((err) => {
      console.error('[auth] getAuthCode failed, try manual mode', err);
      // 模拟器拿不到 authCode 时，允许手动输入继续调试
      manualAuthCode().then((code) => {
        exchangeToken(code).then(resolve).catch(reject);
      }).catch(reject);
    });
  });
}

module.exports = { login };
