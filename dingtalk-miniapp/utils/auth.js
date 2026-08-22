const config = require('../config.js');

// 兜底 corpId：防止开发者工具热重载/缓存导致 config.corpId 为空
const FALLBACK_CORP_ID = 'ding49b7555f7b0e7c421b9a8c00fa015bc5';

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

// 兼容不同钉钉小程序运行时：开发者工具模拟器用 dd.requestAuthCode，真机用 dd.getAuthCode
function getAuthCode() {
  return new Promise((resolve, reject) => {
    const corpId = config.corpId || FALLBACK_CORP_ID;
    console.log('[auth] config.corpId=', config.corpId, 'useCorpId=', corpId);

    const options = {
      corpId: corpId,
      success: (res) => {
        const code = res && (res.authCode || res.code);
        console.log('[auth] getAuthCode success code=', code ? (code.slice(0, 8) + '...') : 'EMPTY');
        resolve(code);
      },
      fail: (err) => {
        console.error('[auth] getAuthCode fail', err);
        reject(wrapError('获取 authCode 失败', err));
      }
    };

    if (typeof dd.getAuthCode === 'function') {
      dd.getAuthCode(options);
    } else if (typeof dd.requestAuthCode === 'function') {
      dd.requestAuthCode(options);
    } else {
      reject({ message: '当前环境不支持钉钉免登' });
    }
  });
}

// 后端登录：用 authCode 换 token
// 关键：真机请求到 FC 后端往返可能较慢（gettoken+getuserinfo 链路可达 7-10s），
// 必须给足超时，不要用 10s 这种比后端处理还短的值。
function exchangeToken(authCode) {
  return new Promise((resolve, reject) => {
    console.log('[auth] POST /api/auth/login authCode=', authCode ? (authCode.slice(0, 8) + '...') : 'EMPTY');
    const url = config.apiBase + '/api/auth/login';

    let settled = false;
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        reject({ message: '登录请求超时(30s)：后端或网络响应过慢，请切换 4G/5G 后重试' });
      }
    }, 30000);

    const finish = (fn, val) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      fn(val);
    };

    const handleLoginRes = (res, source) => {
      console.log('[auth] /api/auth/login response', source, res);
      // dd.request 在 dataType:'json' 时，res.data 已经是后端返回的 JSON 对象
      // 标准后端信封: { code: 0, data: { token, user } }
      const data = (res && res.data) || null;
      if (res && res.status === 200 && data && data.code === 0 && data.data && data.data.token) {
        const payload = data.data;
        dd.setStorageSync({ key: 'sessionToken', value: payload.token });
        dd.setStorageSync({ key: 'userId', value: payload.user.id });
        finish(resolve, payload.user);
      } else {
        const msg = (data && data.message) ? data.message : '免登失败';
        finish(reject, { message: msg, raw: data, source: source });
      }
    };

    // 优先用 dd.request（钉钉官方新请求 API）
    if (typeof dd.request === 'function') {
      dd.request({
        url: url,
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        data: { authCode: authCode },
        dataType: 'json',
        success: (res) => handleLoginRes(res, 'dd.request'),
        fail: (err) => {
          console.error('[auth] dd.request fail', err);
          // 降级到 fetch（某些旧基础库没有 dd.request 时）
          tryFetch();
        }
      });
    } else {
      tryFetch();
    }

    function tryFetch() {
      fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ authCode: authCode })
      }).then((resp) => {
        return resp.text().then((text) => {
          let data = null;
          try { data = text ? JSON.parse(text) : {}; } catch (e) { data = { message: '响应解析失败: ' + text }; }
          handleLoginRes({ status: resp.status, data: data }, 'fetch');
        });
      }).catch((err) => {
        console.error('[auth] fetch fail', err);
        finish(reject, wrapError('登录请求失败(fetch)', err));
      });
    }
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
