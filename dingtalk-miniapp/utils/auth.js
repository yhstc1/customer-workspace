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
    const opts = {
      corpId: corpId,
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

// 统一错误包装：把钉钉 SDK / httpRequest 的原始错误完整保留
function wrapError(prefix, raw) {
  let detail = '';
  if (typeof raw === 'string') detail = raw;
  else if (raw && raw.error) detail = raw.error;
  else if (raw && raw.errorMessage) detail = raw.errorMessage;
  else if (raw && raw.message) detail = raw.message;
  else if (raw && raw.originData) detail = String(raw.originData);
  else detail = JSON.stringify(raw);
  return { message: prefix + (detail ? ': ' + detail : ''), raw: raw };
}

// 后端登录：用 authCode 换 token
function exchangeToken(authCode) {
  return new Promise((resolve, reject) => {
    console.log('[auth] POST /api/auth/login authCode=', authCode ? (authCode.slice(0, 8) + '...') : 'EMPTY');
    dd.httpRequest({
      url: config.apiBase + '/api/auth/login',
      method: 'POST',
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
        reject(wrapError('登录请求失败', err));
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
