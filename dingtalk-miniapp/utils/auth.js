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
// 注意：钉钉纯血鸿蒙(HarmonyOS NEXT)真机下 dd.httpRequest 会被客户端安全策略拦截返回 error 14，
// 即使 request 合法域名已正确配置。改用 fetch（同样受 request 合法域名约束，但不走 dd 的 14 号拦截逻辑），
// 这是已知绕过方案，已在 Mate 80 / 卓易通环境验证可行。
function exchangeToken(authCode) {
  return new Promise((resolve, reject) => {
    console.log('[auth] POST /api/auth/login authCode=', authCode ? (authCode.slice(0, 8) + '...') : 'EMPTY');
    const url = config.apiBase + '/api/auth/login';
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ authCode: authCode })
    }).then((resp) => {
      return resp.json().then((data) => {
        console.log('[auth] /api/auth/login response', resp.status, data);
        // 后端统一信封: { code:0, data:{ token, user:{ id,is_admin } } }
        if (resp.status === 200 && data && data.code === 0 && data.data && data.data.token) {
          const payload = data.data;
          dd.setStorageSync({ key: 'sessionToken', value: payload.token });
          dd.setStorageSync({ key: 'userId', value: payload.user.id });
          resolve(payload.user);
        } else {
          const msg = (data && data.message) ? data.message : '免登失败';
          reject({ message: msg, raw: data });
        }
      });
    }).catch((err) => {
      console.error('[auth] /api/auth/login fetch fail', err);
      // fetch 抛错通常是网络层被拦：可能仍是白名单/证书/网络问题
      reject(wrapError('登录请求失败(fetch)', err));
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
