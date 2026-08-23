// ==================== 移动端逻辑 ====================

// 当前版本号（用于「关于」页展示）。
// 版本号规则（仅适用于 APK/移动端；PC 端模板改动不触发）：① 第一位=重大版本（用户判定，当前=4），大版本升级时二三位归零；② 有需 APK 的原生改动→中间位+1、末位保持（例 4.12.15→4.13.15）；③ H5/纯页面改动只发服务器热更、不 bump 中间位（用户无感）。
const APP_VERSION = '4.14.16';

// ==================== H5 密码登录浮层 ====================
// 纯账号密码登录。后端基于 session cookie 认证。
function showH5Login(defaultMsg) {
  // 避免重复弹
  if (document.getElementById('h5LoginMask')) return;
  const mask = document.createElement('div');
  mask.id = 'h5LoginMask';
  mask.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:9999;padding:24px;';
  mask.innerHTML = `
    <div style="background:#fff;border-radius:14px;width:100%;max-width:340px;padding:22px 20px;box-shadow:0 8px 30px rgba(0,0,0,.18);">
      <div style="font-size:18px;font-weight:700;margin-bottom:4px;color:#222;">客户管理平台</div>
      <div id="h5LoginTip" style="font-size:13px;color:#e0483c;min-height:18px;margin-bottom:12px;">${defaultMsg || ''}</div>
      <div style="margin-bottom:12px;">
        <input id="h5LoginPhone" type="tel" inputmode="numeric" placeholder="手机号" style="width:100%;box-sizing:border-box;padding:11px 12px;border:1px solid #ddd;border-radius:9px;font-size:15px;">
      </div>
      <div style="margin-bottom:16px;">
        <input id="h5LoginPwd" type="password" placeholder="密码" style="width:100%;box-sizing:border-box;padding:11px 12px;border:1px solid #ddd;border-radius:9px;font-size:15px;">
      </div>
      <button id="h5LoginBtn" style="width:100%;padding:12px;border:none;border-radius:9px;background:#1677ff;color:#fff;font-size:16px;font-weight:600;">登录</button>
    </div>`;
  document.body.appendChild(mask);

  function doLogin() {
    const phone = (document.getElementById('h5LoginPhone').value || '').trim();
    const pwd = document.getElementById('h5LoginPwd').value || '';
    const tip = document.getElementById('h5LoginTip');
    const btn = document.getElementById('h5LoginBtn');
    if (!phone || !pwd) { tip.textContent = '请输入手机号和密码'; return; }
    btn.disabled = true; btn.textContent = '登录中…';
    fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ phone: phone, password: pwd })
    }).then(r => r.json().catch(() => ({}))).then(d => {
      if (d.ok && d.user) {
        mask.remove();
        // 登录成功后刷新当前页数据
        if (typeof window.__mobileMarkDirty === 'function') window.__mobileMarkDirty();
        const cp = window.currentPage || 'tasks';
        if (typeof switchPage === 'function') switchPage(cp);
        if (typeof window.preloadAllData === 'function') window.preloadAllData();
      } else {
        tip.textContent = (d && d.message) ? d.message : '登录失败';
        btn.disabled = false; btn.textContent = '登录';
      }
    }).catch(err => {
      tip.textContent = '网络错误，请重试';
      btn.disabled = false; btn.textContent = '登录';
    });
  }

  document.getElementById('h5LoginBtn').addEventListener('click', doLogin);
  document.getElementById('h5LoginPwd').addEventListener('keydown', (e) => { if (e.key === 'Enter') doLogin(); });
}
window.showH5Login = showH5Login;

let currentPage = 'tasks';

// 运行环境标记：装在 App（APK）内时 window.CustomerApp 桥存在，给根节点加 m-apk 类，
// 供 CSS 区分两端（如底栏离底距离：APK 8px / 浏览器 15px）。浏览器端无该桥则不添加。
// 多重兜底：脚本加载时、DOM 就绪、load 事件、再加两次延时各查一次，确保 APK 内桥就绪后一定加上。
function applyApkMarker() {
    if (typeof window.CustomerApp !== 'undefined') {
        document.documentElement.classList.add('m-apk');
        return true;
    }
    return false;
}
applyApkMarker();
document.addEventListener('DOMContentLoaded', applyApkMarker);
window.addEventListener('load', applyApkMarker);
setTimeout(applyApkMarker, 50);
setTimeout(applyApkMarker, 300);

// 页面进入动画方向：'fade'（一级页面淡入上浮） / 'right'（二级页面从右滑入） / 'left'（返回时父页从左侧滑入）
var _pageEnterDir = 'fade';
// 是否正在执行"返回"导航（决定进入动画方向：左滑入 vs 右/淡入）
var _isBackNav = false;
// 页面切换动画锁，避免返回退场动画期间重复触发
var _pageAnimating = false;
// 关闭弹窗后刷新列表时抑制主界面进入动画（与四象限弹窗一致：主界面不动）
var _suppressPageAnim = false;

// 一级页面快照缓存：切 tab / 返回时直接恢复，避免重复拉取（地图页除外，因其含 Leaflet 实例）
var _pageCache = {};
var _pageDirty = {};
['customers', 'business', 'map', 'tasks', 'settings'].forEach(function(p) { _pageDirty[p] = true; });
function markAllPagesDirty() {
    ['customers', 'business', 'map', 'tasks', 'settings'].forEach(function(p) { _pageDirty[p] = true; });
}
window.__mobileMarkDirty = markAllPagesDirty;

// 进入软件自动预拉各 Tab 数据（后台并发、互不阻塞、失败静默）。
// 复用与 loadCustomersMobile / loadBusinessesMobile / loadMapMobile 同一批内存缓存变量
// （_allCustomersMobile / allBusinessesMobile / _mapData），不另建第二份存储，避免
// 内存冗余与数据不一致；切到对应 Tab 时这些变量已就位 → switchPage 跳过「加载中」直接本地渲染。
// 说明：事项页是启动默认页（boot 时 switchPage('tasks') 已拉取），无需在此重复预取。
// 地图的「地理定位」需用户授权、无法后台完成，但 settings+客户数据先备好，切到地图只差定位一环。
var _preloadStarted = false;
function preloadAllData() {
    if (_preloadStarted) return;
    _preloadStarted = true;
    // 客户：客户列表 + 子待办计数 + 我方坐标（loadCustomersMobile 渲染时复用，省去首次 2 次请求）
    if (!window._allCustomersMobile) {
        api('/api/customers').then(function(d) {
            window._allCustomersMobile = d;
            if (!window._custSubtaskCounts) {
                api('/api/customers/subtask-counts').then(function(sc) { window._custSubtaskCounts = sc || {}; }).catch(function() {});
            }
            if (window._myLat == null || window._myLon == null) {
                api('/api/settings').then(function(s) {
                    window._myLat = parseFloat(s.my_latitude) || 30.358935;
                    window._myLon = parseFloat(s.my_longitude) || 114.323843;
                }).catch(function() {});
            }
        }).catch(function() { window._allCustomersMobile = null; });
    }
    // 业务：全量业务（台账进入时按需再拉，不在预加载范围）
    if (!allBusinessesMobile || allBusinessesMobile.length === 0) {
        api('/api/business').then(function(d) { allBusinessesMobile = d || []; }).catch(function() { allBusinessesMobile = []; });
    }
    // 地图：settings + 客户（坐标/客户数据先备好，切到地图时不回源）
    if (!window._mapData) {
        Promise.all([
            api('/api/settings').catch(function() { return {}; }),
            (window._allCustomersMobile ? Promise.resolve(window._allCustomersMobile) : api('/api/customers').catch(function() { return []; }))
        ]).then(function(r) {
            var s = r[0] || {};
            var custs = r[1] || [];
            window._mapData = {
                lat: parseFloat(s.my_latitude) || 30.358935,
                lon: parseFloat(s.my_longitude) || 114.323843,
                customers: custs,
                timestamp: Date.now()
            };
            window._mapLat = window._mapData.lat;
            window._mapLon = window._mapData.lon;
            window._mapCustomers = custs;
            if (!window._allCustomersMobile && custs.length) window._allCustomersMobile = custs;
        }).catch(function() {});
    }
}
window.preloadAllData = preloadAllData;

// ==================== 全局导航栈 ====================
// 单一路由模型：手势返回与按钮返回都经由 popstate 统一处理，
// 保证「一次返回 = 弹出一个导航栈条目 = 消费一个历史状态」，杜绝游离状态导致的
// “多吞一次 / 卡在一级页 / 再点一次才提示退出”等抖动。
var _navStack = []; // 每个条目：{ fn, key }；同一 key（同一二级页重渲染）时去重，避免重复压栈

// 一级页面滚动位置记忆：离开一级列表时记录，返回时还原（item3：返回后留在原位）
var _savedScroll = {};
// 当前是否停留在一级页面（用于判断 enterSubPage 时是否应记录滚动）
var _isOnTopPage = false;

// navPush(key, returnFn)：进入二级页时压入「返回函数 + 历史状态」。
// key 为当前二级页标识（如 'cust:5'）；同一 key 的重渲染（详情页 refresh / 重复进入）
// 仅更新返回函数、不重复压栈/历史，杜绝「多点几次就要多返回几次」的游离状态累积。
function navPush(key, returnFn) {
    if (typeof key === 'function') { returnFn = key; key = 'auto_' + _navStack.length; }
    // 取「父页面模式」：enterSubPage 已在其首行捕获并暂存；若缺失（内联 navPush 抢先执行），
    // 直接按当前 header 推断（此时 header 仍反映父页）。取出后立即清空，避免被后续操作误用。
    var _hmode = (typeof window._pendingParentMode !== 'undefined') ? window._pendingParentMode : _detectHeaderMode();
    window._pendingParentMode = undefined;
    if (_navStack.length > 0 && _navStack[_navStack.length - 1].key === key) {
        _navStack[_navStack.length - 1].fn = returnFn;
        _navStack[_navStack.length - 1].mode = _hmode;
        return;
    }
    _navStack.push({ fn: returnFn, key: key, mode: _hmode });
    try { history.pushState({ sub: true }, '', window.location.href); } catch (e) {}
}

// 按钮返回（✕ / ← / 取消 / 保存）：只触发一次 history.back()，
// 真正的返回逻辑一律在 popstate 里完成，避免重复消费历史状态。
function navBack() {
    if (_navStack.length > 0) {
        try { history.back(); } catch (e) {}
    } else {
        // 无记录的兜底（如从顶栏菜单进入的二级页）：直接回退到最近一级页
        switchPage(_prevTopPage);
    }
}

// 执行返回动画并切回父页
function _runReturn(item) {
    // 若退场动画锁仍被占用（极少数 setTimeout 未触及的情况下），强制释放后再返回，
    // 防止动画锁卡死导致后续所有返回（含返回手势）全部失效。
    if (_pageAnimating) { _pageAnimating = false; }
    _isBackNav = true;
    // 返回动画统一：退出固定 pg-exit-right（旧页右滑出），进入强制左滑入（pg-left）。
    // 否则返回到「直接 innerHTML 重绘的详情页」（paintBizDetail/paintCustomerDetail 作返回目标时
    // 不调 switchPage/enterSubPage、不设 _pageEnterDir）会沿用进入时的 'right' → 右滑入，
    // 与「二级→一级」等其它返回（左滑入）不一致（v3.0.18 修）。
    _pageEnterDir = 'left';
    _pageAnimating = true;
    var content = document.getElementById('pageContent');
    var runReturn = function() {
        try { item.fn(); }
        finally {
            // 返回后的顶栏状态（返回键 / 设置键 / 底栏 / 刷新按钮）一律由 item.fn() 内部
            // 的 switchPage（一级页）或 enterSubPage（二级页）正确设置——两者都在首处
            // await 之前同步写好顶栏，因此此处不再做任何二次覆盖，避免把顶栏误置。
            // （v3.0.16 曾在此用 navPush 捕获的父模式二次覆盖，但该模式在「详情→另一
            // 详情/编辑页」路径下过期，导致返回一级页后底栏缺失、返回键残留；后又加的
            // 编辑页 X/✓ 防御性隐藏经确认是死代码——v3.0.14 起编辑页改底部按钮且
            // switchPage/enterSubPage 进入时均隐藏，现已一并移除，_runReturn 只负责跑
            // 返回函数与动画锁。）
            setTimeout(function() { _pageAnimating = false; }, 240);
        }
        setTimeout(function() { _isBackNav = false; }, 60);
    };
    if (content && content.children.length) {
        content.classList.remove('pg-fade', 'pg-right', 'pg-fade-plain', 'pg-left');
        void content.offsetWidth; // 强制回流以重启动画
        content.classList.add('pg-exit-right');
        setTimeout(runReturn, 160);
    } else {
        runReturn();
    }
}

// 重置所有三级页面：设置内容 + 强制滚动到顶部
function renderPage(html) {
    document.getElementById('pageContent').innerHTML = html;
    resetPageScroll();
}

// ==================== 图标定义（钉钉风格 SVG） ====================
var ICONS = {
    dashboard: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="8" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/><rect x="13" y="13" width="8" height="8" rx="1.5"/></svg>',
    customers: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="9.5" cy="7.5" rx="3.5" ry="4"/><path d="M1 21v-2a6 6 0 0 1 6-6h5a6 6 0 0 1 6 6v2"/><path d="M17.5 9.5a3 3 0 1 0 0-6"/><path d="M23 21v-1a4.5 4.5 0 0 0-3.5-4.33"/></svg>',
    business: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/></svg>',
    map: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a8 8 0 0 0-8 8c0 5.5 8 12 8 12s8-6.5 8-12a8 8 0 0 0-8-8z"/><circle cx="12" cy="10" r="3"/></svg>',
    tasks: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="m9 12 2 2 4-4"/></svg>',
    settings: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06-.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
    add: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v8"/><path d="M8 12h8"/></svg>',
    save: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>',
    edit: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>',
    del: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>',
    search: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>',
    people: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="9.5" cy="7.5" rx="3.5" ry="4"/><path d="M1 21v-2a6 6 0 0 1 6-6h5a6 6 0 0 1 6 6v2"/></svg>',
    clipboard: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="m9 12 2 2 4-4"/></svg>',
    location: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a8 8 0 0 0-8 8c0 5.5 8 12 8 12s8-6.5 8-12a8 8 0 0 0-8-8z"/><circle cx="12" cy="10" r="3"/></svg>',
    cal: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/></svg>',
    refresh: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>',
    detail: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 9h6"/><path d="M9 13h6"/><path d="M9 17h4"/></svg>',
    close: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
    done: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>',
    phone: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/></svg>',
    mail: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>',
    address: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a8 8 0 0 0-8 8c0 5.5 8 12 8 12s8-6.5 8-12a8 8 0 0 0-8-8z"/><circle cx="12" cy="10" r="3"/></svg>',
    tag: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2H2v10l9.29 9.29c.94.94 2.46.94 3.41 0l5.88-5.88c.94-.94.94-2.46 0-3.41L12 2z"/><circle cx="7" cy="7" r="2"/></svg>',
    note: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><line x1="10" y1="9" x2="8" y2="9"/></svg>',
    nav: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="3 11 22 2 13 21 11 13 3 11"/></svg>',
    logout: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>',
    loading: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"/><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"/><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"/></svg>',
    error: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    empty: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>',
    report: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><line x1="10" y1="9" x2="8" y2="9"/></svg>',
    clock: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
    back: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>',
    bolt: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
    folder: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
    party: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>',
    building: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4"/><path d="M8 6h.01"/><path d="M16 6h.01"/><path d="M8 10h.01"/><path d="M16 10h.01"/><path d="M8 14h.01"/><path d="M16 14h.01"/></svg>',
    ruler: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 6H3a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h18a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2z"/><path d="M5 10h.01"/><path d="M9 10h.01"/><path d="M13 10h.01"/><path d="M17 10h.01"/><path d="M7 14h.01"/><path d="M11 14h.01"/><path d="M15 14h.01"/><path d="M19 14h.01"/></svg>',
    pause: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="10" y1="15" x2="10" y2="9"/><line x1="14" y1="15" x2="14" y2="9"/></svg>',
    archive: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8"/><path d="M10 12h4"/></svg>',
    chevronRight: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>',
    chevronDown: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>',
    chevronUp: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 15 12 9 6 15"/></svg>',
    more: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></svg>',
    user: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
    eye: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>',
    eyeOff: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-6.5 0-10-7-10-7a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c6.5 0 10 7 10 7a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>'
};

// 将 HTML 中的 <i class="m-icon" data-icon="xxx"></i> 替换为对应 SVG
function renderIcons(root) {
    if (!root) root = document.body;
    if (!root.querySelectorAll) return;
    var nodes = root.querySelectorAll('.m-icon[data-icon]');
    for (var i = 0; i < nodes.length; i++) {
        var el = nodes[i];
        var key = el.getAttribute('data-icon');
        var svg = ICONS[key];
        if (svg) el.outerHTML = svg;
    }
}

// HTML 转义，防止客户/业务数据中的特殊字符破坏结构
function esc(s) {
    if (s === null || s === undefined) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// 客户分类对应的强调色（用于分组卡片左侧图标底色）
function catAccent(cat) {
    if (cat === '核心要客' || cat === 'VIP客户') return '#ff9f0a';
    if (cat === 'TOP20' || cat === '重要客户') return '#0a84ff';
    return '#8e8e93';
}

// ==================== 页面切换 ====================

// 一级页面列表（显示设置按钮 + 底栏）
var TOP_LEVEL_PAGES = ['customers', 'business', 'map', 'tasks', 'settings'];

// 记录最近访问的一级页面，用于二级页面返回
var _prevTopPage = 'tasks';

function goBack() {
    navBack();
}

// 进入二级页面：批量隐藏返回按钮、设置按钮、底栏，避免逐次触发布局
// 全局命令：进入新页面时滚动复位到顶部（避免新页面继承上一页的下滑位置）。
// 子页经 enterSubPage、一级页经 switchPage、通用渲染经 renderPage 统一调用；今后新增页面无需各自写 scrollTo。
function resetPageScroll() { window.scrollTo(0, 0); }

// 读取当前顶栏按钮可见性，推断所属页面模式：
//   'edit' 编辑页（X取消 / ✓保存 可见）
//   'top'  一级页（设置按钮 / 底栏 可见）
//   'sub'  二级非编辑页（仅返回按钮）
// 用于导航栈记录「父页面模式」，返回时据此复位 X/✓ 等按钮，避免编辑态残留。
function _detectHeaderMode() {
    var close = document.getElementById('mHeaderClose');
    var save = document.getElementById('mHeaderSave');
    var settings = document.getElementById('mHeaderSettings');
    var tabbar = document.querySelector('.mobile-tabbar');
    if ((close && close.style.display !== 'none') || (save && save.style.display !== 'none')) return 'edit';
    if ((settings && settings.style.display !== 'none') || (tabbar && tabbar.style.display !== 'none')) return 'top';
    return 'sub';
}

// 统一设置顶栏按钮可见性（不含滚动/磨砂等副作用），供返回复位复用。
// mode: 'top'（设置+底栏）/ 'sub'（返回按钮、无X/✓）/ 'edit'（X/✓、无返回按钮）。
function applyHeaderMode(mode) {
    var back = document.getElementById('mHeaderBack');
    var settings = document.getElementById('mHeaderSettings');
    var tabbar = document.querySelector('.mobile-tabbar');
    var close = document.getElementById('mHeaderClose');
    var save = document.getElementById('mHeaderSave');
    if (back) back.style.display = (mode === 'sub') ? '' : 'none';
    if (settings) settings.style.display = (mode === 'top') ? '' : 'none';
    if (tabbar) tabbar.style.display = (mode === 'top') ? '' : 'none';
    if (close) close.style.display = (mode === 'edit') ? '' : 'none';
    if (save) save.style.display = (mode === 'edit') ? '' : 'none';
}

function enterSubPage() {
    // 捕获「父页面（本页返回后要回到的页面）当前模式」存入导航栈，返回时复位 X/✓ 等按钮。
    // 必须在任何顶栏改动之前读取（此时 header 仍反映父页状态）。
    window._pendingParentMode = _detectHeaderMode();
    // 离开一级列表时记录当前滚动位置，返回时还原（避免返回后跳到顶部）
    // 注意：仅当当前确实停留在一级页面才记录；从详情→编辑时不应覆盖一级列表位置
    if (_isOnTopPage && TOP_LEVEL_PAGES.indexOf(currentPage) !== -1) {
        _savedScroll[currentPage] = window.scrollY;
    }
    _isOnTopPage = false;
    _subAutoScroll = true;   // 标记「待滚顶」：真正滚顶推迟到 #pageContent 内容渲染完成后（见下方观察器），避免异步加载时旧页闪现跳顶
    _pageEnterDir = _isBackNav ? 'left' : 'right';
    // 二级页面：表头字号变小（与一级页面区分）
    document.body.classList.add('m-subpage');
    // 离开客户列表/地图页进入二级页：标题栏恢复自身磨砂（移除连续磨砂带标记）
    document.body.classList.remove('m-map-frost');
    document.body.classList.remove('m-home-frost');
    var el1 = document.getElementById('mHeaderBack');
    var el2 = document.getElementById('mHeaderSettings');
    var el3 = document.querySelector('.mobile-tabbar');
    var elClose = document.getElementById('mHeaderClose');
    var elSave = document.getElementById('mHeaderSave');
    if (el1) el1.style.display = '';
    if (el2) el2.style.display = 'none';
    if (el3) el3.style.display = 'none';
    // 进入任意二级页默认隐藏编辑页专用按钮（X / ✓），由 enterEditPage 显式打开
    if (elClose) elClose.style.display = 'none';
    if (elSave) elSave.style.display = 'none';
}

// 子页进入时不再立即 window.scrollTo(0,0)——那会让仍在可见的旧页在异步加载期间先跳到顶，造成闪屏。
// 改为：enterSubPage 置 _subAutoScroll=true，待 #pageContent 的内容真正被替换（innerHTML 写入）后再滚顶，
// 保证新页从顶部开始、且旧页不闪。就地刷新（refresh=true）的视图会主动置 false 以保留原位。
var _subAutoScroll = false;
(function setupSubScrollObserver() {
    var pc = document.getElementById('pageContent');
    if (!pc) { setTimeout(setupSubScrollObserver, 50); return; }
    new MutationObserver(function() {
        if (_subAutoScroll) { window.scrollTo(0, 0); _subAutoScroll = false; }
    }).observe(pc, { childList: true, subtree: false });
})();

function setHeaderMode(mode) {
    // mode: 'home' (show settings icon), 'back' (show back button)
    var backBtn = document.getElementById('mHeaderBack');
    var settingsBtn = document.getElementById('mHeaderSettings');
    if (backBtn) backBtn.style.display = (mode === 'back') ? '' : 'none';
    if (settingsBtn) settingsBtn.style.display = (mode === 'home') ? '' : 'none';
}

function setTabBarVisible(visible) {
    var tabbar = document.querySelector('.mobile-tabbar');
    if (tabbar) tabbar.style.display = visible ? '' : 'none';
}

// 顶栏刷新按钮（标题右侧）：按当前一级页重新拉取数据并重绘。
// 原生下拉刷新已禁用（mobile.css 的 overscroll-behavior-y:none），此按钮是唯一下拉刷新替代入口。

async function switchPage(page) {
    // 到达一级页面：清空导航栈（任何遗留的二级页条目在此被丢弃），
    // 保证「在二级页点切换页面后返回一级页」不会残留游离栈条目导致多吞返回。
    _navStack = [];
    // 离开客户详情：清除详情标记，避免后续操作误刷新已离开的详情页
    window._viewingCustomerId = null;
    // 离开业务详情：清除标记，避免后续操作误刷新已离开的详情页
    window._viewingBizId = null;
    // 关闭所有打开的模态框（z-index:2000 和 z-index:1050 的遮罩/弹窗）
    var overlays = document.querySelectorAll('div[style*="z-index: 2000"], div[style*="z-index:2000"], div[style*="z-index: 1050"], div[style*="z-index:1050"]');
    overlays.forEach(function(el) { el.remove(); });

    // 离开当前一级列表时记录滚动位置 → 切换 Tab / 返回后停在原位（item3 全局生效，含业务/台账）
    // 仅当确实停留在一级列表（_isOnTopPage）才记录：在二级详情页返回时 currentPage 仍是该一级页，
    // 此时若记录会覆盖 enterSubPage 已存的列表滚动位置，导致返回后跳到顶部。
    if (_isOnTopPage && TOP_LEVEL_PAGES.indexOf(currentPage) !== -1) {
        _savedScroll[currentPage] = window.scrollY;
    }

    currentPage = page;
    // 进入新页面时复位滚动位置，避免新页面继承上一页的下滑位置
    resetPageScroll();
    _pageEnterDir = _isBackNav ? 'left' : 'fade';

    // 记录最后一次访问的一级页面（供二级页面返回使用）
    if (TOP_LEVEL_PAGES.indexOf(page) !== -1) {
        _prevTopPage = page;
    }

    // 更新 Tab 高亮
    document.querySelectorAll('.tab-item').forEach(t => t.classList.remove('active'));
    var tab = document.querySelector('.tab-item[data-page="' + page + '"]');
    if (tab) tab.classList.add('active');

    // 更新标题
    var titles = {
        customers: '客户管理',
        business: '业务管理',
        map: '地图视图',
        tasks: '事项看板',
        settings: '设置'
    };
    document.getElementById('pageTitle').textContent = titles[page] || '';

    // 一级页面：显示设置按钮 + 底栏；二级页面：显示返回按钮 + 隐藏底栏
    var isTop = TOP_LEVEL_PAGES.indexOf(page) !== -1;
    _isOnTopPage = isTop;
    setHeaderMode(isTop ? 'home' : 'back');
    setTabBarVisible(isTop);
    // 进入任意页面（含一级）时复位编辑页专用按钮（X / ✓），避免从上一个编辑页残留
    var _ec = document.getElementById('mHeaderClose');
    var _es = document.getElementById('mHeaderSave');
    if (_ec) _ec.style.display = 'none';
    if (_es) _es.style.display = 'none';

    // 一级页面：表头字号恢复默认（移除二级页的小字号标记）
    document.body.classList.remove('m-subpage');
    // 地图页：顶栏与地图控件之间的空隙由单一连续磨砂带覆盖（消除割裂线）。
    document.body.classList.toggle('m-map-frost', page === 'map');
    // 列表首页（客户/业务/事项）：顶栏磨砂遮罩延伸至 105+S，标题栏透出 #mHeaderVeil 连续磨砂
    document.body.classList.toggle('m-home-frost', page === 'customers' || page === 'business' || page === 'tasks');

    // 恢复 body / html 可滚动（弹窗可能锁了滚动）
    document.documentElement.style.overflow = '';
    document.body.style.overflow = '';
    const content = document.getElementById('pageContent');
    if (content) {
        content.style.display = '';
        content.style.flexDirection = '';
        content.style.height = '';
        content.style.overflow = '';
        content.style.padding = '';
    }

    // 命中快照（非地图页、有缓存、未失效）→ 直接恢复，跳过网络请求与"加载中"闪现
    // 业务页：缓存恢复后同步子 Tab 显隐 + 重新绑定长按，避免快照状态错乱
    // 客户页：若刚做过新增/编辑/删除，丢弃快照与数据缓存，强制重新拉取（令改动立即可见）。
    if (page === 'customers' && window._customersNeedRefresh) {
        window._customersNeedRefresh = false;
        window._allCustomersMobile = null;
        _pageCache['customers'] = null;
        _pageDirty['customers'] = true;
    }
    // 业务页：刚新增/编辑/删除过 → 丢弃快照，返回时强制重新拉取最新数据（与事项看板一致）
    if (page === 'business' && window._businessNeedRefresh) {
        window._businessNeedRefresh = false;
        _pageCache['business'] = null;
        _pageDirty['business'] = true;
        allBusinessesMobile = []; // 强制重新拉取全部业务
        _ledgerLoaded = false;    // 台账(ledgers) 一并重新拉取
        _ledgerData = [];
    }
    if (page !== 'map' && _pageCache[page] && !_pageDirty[page]) {
        restorePageFromCache(page);
        // 返回一级页面时还原离开前的滚动位置（item3）
        setTimeout(function() { window.scrollTo(0, _savedScroll[page] || 0); }, 0);
        // 快照恢复只还原 innerHTML，JS 绑定的长按事件丢失，需重新绑定
        function _bindBizItems(containerId, dataSource, action) {
            var _c = document.getElementById(containerId);
            if (!_c) return;
            _c.querySelectorAll('.m-group-item[data-id]').forEach(function(el) {
                var _id = parseInt(el.getAttribute('data-id'), 10);
                var _d = (dataSource || []).find(function(x) { return x.id === _id; });
                if (!_d) return;
                bindLongPress(el, function() { action(_id, _d); });
            });
        }
        if (page === 'customers') {
            var _cl = document.getElementById('mCustList');
            if (_cl) {
                // 一次性构建 id→客户 哈希索引（O(1) 查询），避免对每个列表项都线性扫描全量客户（原 O(n²)）
                var _custById = new Map();
                (window._allCustomersMobile || []).forEach(function(x) { _custById.set(x.id, x); });
                _cl.querySelectorAll('.m-group-item[data-id]').forEach(function(el) {
                    var id = parseInt(el.getAttribute('data-id'), 10);
                    var c = _custById.get(id);
                    if (!c) return;
                    var cname = c.company || c.name || '';
                    bindLongPress(el, function() {
                        mConfirm('删除客户', '确定删除「' + cname + '」？此操作不可撤销。', function() {
                            deleteCustomerMobile(id, cname);
                        });
                    });
                });
            }
        } else if (page === 'tasks') {
            var _tl = document.getElementById('mTaskList');
            if (_tl) {
                _tl.querySelectorAll('.m-task-item[data-tid]').forEach(function(el) {
                    bindLongPress(el, function() {
                        var tid = parseInt(el.getAttribute('data-tid'), 10);
                        var ttitle = el.getAttribute('data-ttitle') || '该事项';
                        var pinned = el.classList.contains('pinned');
                        showTaskActionSheet(tid, ttitle, pinned);
                    });
                });
            }
        } else if (page === 'business') {
            // 仅同步“标签/下拉高亮”，再按当前标签用已缓存的 allBusinessesMobile 重绘列表并绑定长按
            // （不发网络；allBusinessesMobile 为空时 renderBizList 会回源拉取一次）
            // 返回一级页时还原搜索框内容：innerHTML 快照不序列化 input.value，须手动回填再重绘
            var _bSel = document.getElementById('mBizSearch');
            if (_bSel) _bSel.value = _bizSearchCache || '';
            syncBizTabUI(activeBizTabMobile);
            await renderBizList(activeBizTabMobile, _bizCurrentSearch());
        }
        return;
    }

    // 无快照：若底层数据已在内存预取到位（preloadAllData 命中），直接渲染、不闪「加载中」；
    // 否则先显示加载占位再回源拉取。地图页：_mapData 命中即跳过「加载中」字样（Leaflet 加载 +
    // 地理定位仍需片刻，但容器与缓存客户数据已即时呈现），未命中则照常显示加载占位。
    var _memReady = (page === 'customers' && window._allCustomersMobile) ||
                    (page === 'business' && allBusinessesMobile && allBusinessesMobile.length > 0) ||
                    (page === 'map' && window._mapData && (Date.now() - window._mapData.timestamp < 60000));
    if (!_memReady) {
        content.innerHTML = '<div class="m-empty"><div class="icon"><i class="m-icon" data-icon="loading"></i></div><div>加载中...</div></div>';
    }

    var loaded = false;
    try {
        switch (page) {
            case 'customers': await loadCustomersMobile(); break;
            case 'business': await loadBusinessesMobile(); break;
            case 'map': await loadMapMobile(); break;
            case 'tasks': await loadTasksMobile(); break;
            case 'settings': await loadSettingsMobile(); break;
        }
        loaded = true;
        // 返回一级页面时还原离开前的滚动位置（item3）
        setTimeout(function() { window.scrollTo(0, _savedScroll[page] || 0); }, 0);
    } catch (e) {
        content.innerHTML = `<div class="m-empty"><div class="icon"><i class="m-icon" data-icon="error"></i></div><div>加载失败: ${e.message}</div></div>`;
    }

    // 底部加 60px 间隔，防止被固定底栏遮挡（直接追加到 DOM，不依赖 CSS）
    if (TOP_LEVEL_PAGES.indexOf(page) !== -1) {
        if (content && !content.querySelector('.m-bottom-spacer')) {
            content.insertAdjacentHTML('beforeend', '<div class="m-bottom-spacer" style="height:60px;width:100%;flex-shrink:0;"></div>');
        }
    }

    // 渲染成功 → 快照缓存当前页（地图页不缓存，因其含 Leaflet 实例）
    if (loaded && page !== 'map') snapshotCurrentPage(page);
}

// 从快照恢复一级页面（含内联样式与滚动位置），瞬时无网络
function restorePageFromCache(page) {
    var snap = _pageCache[page];
    var content = document.getElementById('pageContent');
    if (!content || !snap) return;
    if (snap.style) content.setAttribute('style', snap.style);
    else content.removeAttribute('style');
    content.innerHTML = snap.html;
    setTimeout(function() { window.scrollTo(0, snap.scroll || 0); }, 0);
}

// 快照当前一级页面渲染结果（供之后瞬时恢复）
function snapshotCurrentPage(page) {
    var content = document.getElementById('pageContent');
    if (!content) return;
    _pageCache[page] = {
        html: content.innerHTML,
        style: content.getAttribute('style') || '',
        scroll: window.pageYOffset || 0
    };
    _pageDirty[page] = false;
}

// ==================== 通用：编辑页头部 / 长按删除 / 顶部菜单 ====================

// 注入 fadeIn 动画（确认框 / 提示框 / 顶部菜单复用）
(function() {
    var style = document.createElement('style');
    style.textContent = '@keyframes fadeIn{from{opacity:0}to{opacity:1}}';
    document.head.appendChild(style);
})();

// 进入「编辑页」：统一采用底部「保存 / 取消」操作栏（各页面 render 中调用 editActionBarHtml 注入），
// 不再使用顶栏 X（取消）/ ✓（保存）。复用二级页设置（隐藏设置/底栏、显示返回按钮）。
// saveFn: 点击底部「保存」时执行的保存函数（如 function(){ saveEditCustomerMobile(id); }）。
function enterEditPage(saveFn) {
    enterSubPage(); // 复用二级页设置：隐藏设置按钮、隐藏底栏、标记 m-subpage
    window._editSaveHandler = saveFn;
}

// 编辑页：X（取消）— 返回上一页（即详情页）
function editPageCancel() {
    navBack();
}

// 编辑页：✓（保存）— 执行注册的保存函数
function editPageSave() {
    if (typeof window._editSaveHandler === 'function') {
        window._editSaveHandler();
    }
}

// 统一「新增/编辑页」底部操作栏：取消（左，描边）/ 保存（右，主按钮）。
// 替代旧版顶栏 X（取消）/ ✓（保存），与「新增客户」页一致；按钮顺序固定为「取消 / 保存」。
function editActionBarHtml(saveLabel) {
    return '<div style="display:flex;gap:8px;margin-top:12px;">' +
        '<button class="btn btn-outline" style="flex:1;padding:12px;justify-content:center;" onclick="editPageCancel()">取消</button>' +
        '<button class="btn btn-primary" style="flex:1;padding:12px;justify-content:center;" onclick="editPageSave()"><i class="m-icon" data-icon="save"></i> ' + (saveLabel || '保存') + '</button>' +
        '</div>';
}

// 通用长按：按住 500ms 触发回调；触发后抑制随后的 click（避免误触进入详情/编辑）
function bindLongPress(el, cb) {
    if (!el) return;
    var timer = null, longFired = false;
    function start() {
        longFired = false;
        if (timer) clearTimeout(timer);
        timer = setTimeout(function() { longFired = true; cb(); }, 500);
    }
    function cancel() { if (timer) { clearTimeout(timer); timer = null; } }
    el.addEventListener('touchstart', start, { passive: true });
    el.addEventListener('touchend', cancel);
    el.addEventListener('touchmove', cancel);
    el.addEventListener('touchcancel', cancel);
    el.addEventListener('mousedown', start);
    el.addEventListener('mouseup', cancel);
    el.addEventListener('mouseleave', cancel);
    el.addEventListener('click', function(e) {
        if (longFired) { e.stopPropagation(); e.preventDefault(); longFired = false; }
    }, true);
}

// 全局「点击即响应」命令：用同一套逻辑统一所有异步点击/输入的反馈，取代各按钮零散的
// disabled+spinner 写法（如刷新位置按钮 mRefreshBtn）。点击瞬间锁定元素并给出 loading 反馈，
// 防重复点击，异步完成后自动恢复。run 返回 Promise；opts: {spinner, loadingText, loadingHTML, keepHTML}
async function withTapFeedback(elRef, run, opts) {
    opts = opts || {};
    var el = (typeof elRef === 'string') ? document.getElementById(elRef) : elRef;
    if (!el) { try { await run(); } catch (e) {} return; }
    if (el.__tapBusy) return;                 // 防重复点击
    el.__tapBusy = true;
    var prevHTML = el.innerHTML;
    var isBtn = (el.tagName === 'BUTTON');
    if (isBtn) el.disabled = true;
    el.style.opacity = '0.55';
    el.style.pointerEvents = 'none';
    if (opts.loadingHTML != null) {
        el.innerHTML = opts.loadingHTML;
    } else if (opts.loadingText) {
        el.innerHTML = (opts.spinner === false ? '' : '<i class="m-icon" data-icon="loading"></i> ') + opts.loadingText;
    }
    if ((opts.loadingHTML != null) || opts.loadingText) renderIcons(el);
    try {
        await run();
    } catch (e) { /* 错误由 run 内部或调用方提示，这里只负责恢复 */ }
    finally {
        el.__tapBusy = false;
        el.style.opacity = '';
        el.style.pointerEvents = '';
        if (isBtn) el.disabled = false;
        if (!opts.keepHTML) el.innerHTML = prevHTML;
    }
}

// 乐观更新（optimistic UI）公共命令：本地先变 → 后台提交 → 成功/失败
// applyLocal 同步执行"本地乐观变更 + 触发返回页重绘"（如 push 临时记录 + navBack）；
// submit 返回 Promise（后台请求）；onSuccess 负责"移除临时态 + 刷新真实数据"；
// rollback(err) 负责"移除临时态 + 提示失败"。与 withTapFeedback 互补：
// 写操作 = 乐观更新(立即变) + withTapFeedback(防连点+微反馈)，切勿只乐观不回滚（网络失败会悄悄丢数据）。
var _pendingCreates = [];
function optimisticWrite(opts) {
    opts = opts || {};
    var applyLocal = opts.applyLocal, submit = opts.submit,
        onSuccess = opts.onSuccess, rollback = opts.rollback;
    try { if (applyLocal) applyLocal(); } catch (e) { console.error('optimisticWrite.applyLocal', e); }
    if (!submit) return;
    Promise.resolve().then(submit).then(function() {
        try { if (onSuccess) onSuccess(); } catch (e) { console.error('optimisticWrite.onSuccess', e); }
    }).catch(function(err) {
        try { if (rollback) rollback(err); } catch (e) { console.error('optimisticWrite.rollback', e); }
    });
}
// 简洁版乐观写入：用于保存/删除后直接返回、无需 pending 跟踪与 rollback 的场景
function quickSave(apiPromise, opts) {
    if (opts && opts.before) { try { opts.before(); } catch(e) {} }
    showToast((opts && opts.successMsg) || '操作成功', 'success');
    if (opts && opts.after) opts.after();
    apiPromise.catch(function(e) {
        showToast(((opts && opts.errorMsg) || '操作失败') + '，请重试', 'error');
    });
}
function removePending(tmpId) {
    if (!window._pendingCreates) return;
    for (var i = window._pendingCreates.length - 1; i >= 0; i--) {
        if (window._pendingCreates[i].tmpId === tmpId) { window._pendingCreates.splice(i, 1); break; }
    }
}
// 提交成功/失败后刷新当前可见的返回页，让临时记录消失 / 真实记录出现
function refreshReturnPagesForCustomer(custId) {
    try {
        if (currentPage === 'business') {
            renderBizList(activeBizTabMobile, _bizCurrentSearch()); // 会重拉 ledgers（_ledgerLoaded 已被置 false）
        }
    } catch (e) {}
    try {
        if (window._viewingCustomerId && String(window._viewingCustomerId) === String(custId)) {
            viewCustomerMobile(custId, true);
        }
    } catch (e) {}
}

// ===== 乐观更新：删除 / 分类派生 / 通用重绘 辅助 =====
// 待删除标记（乐观删除：本地先隐藏，后台 DELETE，失败回滚恢复显示）
var _pendingDeletes = [];
function addPendingDelete(key) {
    if (!window._pendingDeletes.some(function(k) { return k === key; })) window._pendingDeletes.push(key);
}
function removePendingDelete(key) {
    for (var i = window._pendingDeletes.length - 1; i >= 0; i--) {
        if (window._pendingDeletes[i] === key) { window._pendingDeletes.splice(i, 1); break; }
    }
}
function isPendingDelete(key) {
    return window._pendingDeletes.some(function(k) { return k === key; });
}
// 提交成功/失败后重绘当前可见视图（业务列表 / 事项列表 / 客户详情），让临时态消失或真实态出现
function rerenderVisibleAfterMutation() {
    try { if (currentPage === 'business') renderBizListSync(activeBizTabMobile, _bizCurrentSearch()); } catch (e) {}
    try { if (currentPage === 'tasks') renderTaskList(); } catch (e) {}
    if (window._viewingCustomerId) { try { viewCustomerMobile(window._viewingCustomerId, true); } catch (e) {} }
    if (window._viewingBizId) { try { paintBizDetail(window._viewingBizId); } catch (e) {} }
}
// 提交成功后重拉真实数据（用于新建：临时态移除后需展示真实记录）
function refetchVisibleAfterCreate() {
    try { if (currentPage === 'tasks') loadTasksMobile(); } catch (e) {}
    if (window._viewingCustomerId) { try { viewCustomerMobile(window._viewingCustomerId, true); } catch (e) {} }
}

// 通用确认框（删除等危险操作）：居中卡片 + 取消/删除
// 通用弹窗底座：统一「毛玻璃遮罩 + 居中卡片」外观，供确认/提示/选项面板复用，消除重复内联样式。
// 返回已建好的 overlay 元素（尚未 append）；调用方填 innerHTML 后 document.body.appendChild(overlay)。
// onMaskClick 可选：点击遮罩（非卡片）关闭时的额外回调。
function mPopupBase(opts) {
    opts = opts || {};
    var ex = document.getElementById(opts.id);
    if (ex) ex.remove();  // 兜底：先移除可能残留的同名遮罩，避免双层叠加
    var overlay = document.createElement('div');
    overlay.id = opts.id;
    overlay.style.cssText = 'position:fixed;inset:0;z-index:2000;background:rgba(0,0,0,0.35);display:flex;align-items:center;justify-content:center;animation:fadeIn .15s ease;-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);';
    overlay.addEventListener('click', function(e) { if (e.target === overlay) { overlay.remove(); if (opts.onMaskClick) opts.onMaskClick(); } });
    return overlay;
}

// 卡片外壳：与全局确认/提示弹窗同一套背景/圆角/阴影；cardStyle 可追加（如 max-height / 宽度比例）。
function mPopupCard(innerHtml, cardStyle) {
    return '<div class="m-popup-card" style="background:var(--m-card,#1c1c1e);color:var(--m-text,#fff);width:80%;max-width:300px;overflow:hidden;animation:fadeIn .15s ease;box-shadow:0 12px 40px rgba(0,0,0,0.4);' + (cardStyle || '') + '">' + innerHtml + '</div>';
}

function mConfirm(title, message, onConfirm) {
    var overlay = mPopupBase({ id: 'mConfirmOverlay' });
    overlay.innerHTML = mPopupCard(
        '<div style="padding:20px 20px 20px;font-size:14px;color:var(--m-text-secondary,#aaa);line-height:1.5;text-align:center;">' + esc(message) + '</div>' +
        '<div class="m-popup-divider"></div>' +
        '<button onclick="(function(){var o=document.getElementById(\'mConfirmOverlay\');if(o)o.remove();})()" style="width:100%;padding:14px;border:none;background:transparent;color:var(--m-text-secondary,#aaa);font-size:15px;cursor:pointer;">取消</button>' +
        '<div class="m-popup-divider"></div>' +
        '<button onclick="(function(){var o=document.getElementById(\'mConfirmOverlay\');if(o)o.remove();if(window.__mConfirmCb)window.__mConfirmCb();})()" style="width:100%;padding:14px;border:none;background:transparent;color:#ff453a;font-size:15px;font-weight:600;cursor:pointer;">删除</button>'
    );
    window.__mConfirmCb = onConfirm;
    document.body.appendChild(overlay);
}

// 通用提示框（关于等）：居中卡片 + 知道了
function mAlert(title, message) {
    var overlay = mPopupBase({ id: 'mAlertOverlay' });
    overlay.innerHTML = mPopupCard(
        '<div style="padding:20px 20px 4px;font-size:16px;font-weight:700;text-align:center;">' + esc(title) + '</div>' +
        '<div style="padding:8px 20px 24px;font-size:14px;color:var(--m-text-secondary,#aaa);line-height:1.6;text-align:center;white-space:pre-line;">' + esc(message) + '</div>' +
        '<div class="m-popup-divider"></div>' +
        '<button onclick="(function(){var o=document.getElementById(\'mAlertOverlay\');if(o)o.remove();})()" style="width:100%;padding:14px;border:none;background:transparent;color:var(--m-accent,#0a84ff);font-size:15px;font-weight:600;cursor:pointer;">知道了</button>'
    );
    document.body.appendChild(overlay);
}

// 双选项确认框（如「删除主卡」询问是否级联子卡）：取消遮罩 + 两个动作按钮
function mConfirm2(title, message, noLabel, yesLabel, onNo, onYes) {
    var overlay = mPopupBase({ id: 'mConfirm2Overlay' });
    overlay.innerHTML = mPopupCard(
        '<div style="padding:20px 20px 18px;font-size:15px;font-weight:700;text-align:center;">' + esc(title) + '</div>' +
        '<div style="padding:0 20px 20px;font-size:14px;color:var(--m-text-secondary,#aaa);line-height:1.6;text-align:center;">' + esc(message) + '</div>' +
        '<div class="m-popup-divider"></div>' +
        '<button id="mC2No" style="width:100%;padding:14px;border:none;background:transparent;color:var(--m-text-secondary,#aaa);font-size:15px;cursor:pointer;">' + esc(noLabel) + '</button>' +
        '<div class="m-popup-divider"></div>' +
        '<button id="mC2Yes" style="width:100%;padding:14px;border:none;background:transparent;color:#ff453a;font-size:15px;font-weight:600;cursor:pointer;">' + esc(yesLabel) + '</button>'
    , 'width:84%;max-width:320px;');
    overlay.querySelector('#mC2No').addEventListener('click', function() { overlay.remove(); if (onNo) onNo(); });
    overlay.querySelector('#mC2Yes').addEventListener('click', function() { overlay.remove(); if (onYes) onYes(); });
    document.body.appendChild(overlay);
}

// 删除业务统一入口：主卡含子卡时弹「是否一并删除子卡」，否则普通确认
function confirmDeleteBusiness(id, name) {
    var kids = (allBusinessesMobile || []).filter(function(b) { return b.parent_id === id; });
    if (kids.length === 0) {
        mConfirm('删除业务', '确定删除「' + (name || '该业务') + '」？此操作不可撤销。', function() {
            deleteBusinessMobile(id, name);
        });
        return;
    }
    mConfirm2('删除主卡',
        '「' + (name || '该主卡') + '」下还有 ' + kids.length + ' 张副卡/宽带/固话，是否一并删除？',
        '仅删主卡（子卡保留）',
        '一并删除（含子卡）',
        function() { deleteBusinessMobile(id, name, false); }, // 否：仅删主卡，子卡变孤儿
        function() { deleteBusinessMobile(id, name, true); }   // 是：级联删除全部子卡
    );
}

// 右上角「···」菜单（微信风格：顶部右侧弹出小窗，含上指箭头）
function showTopMenu() {
    var existing = document.getElementById('mTopMenu');
    if (existing) { existing.remove(); return; }
    var overlay = document.createElement('div');
    overlay.id = 'mTopMenu';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:1500;background:rgba(0,0,0,0.35);animation:fadeIn .12s ease;';
    overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });
    var infoIcon = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';
    overlay.innerHTML =
        '<div style="position:absolute;top:58px;right:12px;background:#fff;color:#111;border-radius:12px;min-width:150px;box-shadow:0 8px 30px rgba(0,0,0,0.3);overflow:hidden;animation:fadeIn .12s ease;">' +
            '<div style="position:absolute;top:-5px;right:16px;width:11px;height:11px;background:#fff;transform:rotate(45deg);"></div>' +
            '<div onclick="mTopMenuAction(\'settings\')" style="display:flex;align-items:center;gap:10px;padding:13px 16px;font-size:15px;cursor:pointer;border-bottom:1px solid #f0f0f0;">' + ICONS.settings.replace(/1em/g, '18px') + ' 设置</div>' +
            '<div onclick="mTopMenuAction(\'clearCache\')" style="display:flex;align-items:center;gap:10px;padding:13px 16px;font-size:15px;cursor:pointer;border-bottom:1px solid #f0f0f0;">' +
                '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg> 清除本地缓存</div>' +
            '<div onclick="mTopMenuAction(\'about\')" style="display:flex;align-items:center;gap:10px;padding:13px 16px;font-size:15px;cursor:pointer;">' + infoIcon + ' 关于</div>' +
        '</div>';
    document.body.appendChild(overlay);
}

// 关于：全屏界面（版本信息 + 完整更新日志，不再截断为 10 条），沿返回键/手势退回来源页
function openAbout() {
    var prev = _prevTopPage || 'tasks';
    var menu = document.getElementById('mTopMenu');
    if (menu) menu.remove();
    enterSubPage();          // 隐藏底栏 + 设置按钮、显示返回按钮、标记 m-subpage
    setHeaderMode('back');
    var titleEl = document.getElementById('pageTitle');
    if (titleEl) titleEl.textContent = '关于';
    navPush('about', function() { switchPage(prev); });
    renderAboutMobile();
}

// 关于页内容：渲染进 #pageContent（与设置页同一套全屏子页骨架）
function renderAboutMobile() {
    var content = document.getElementById('pageContent');
    content.innerHTML =
        '<div class="m-card m-about-card">' +
            '<div class="m-about-logo-wrap">' +
                '<img class="m-about-logo" src="/static/images/about-logo.png?v=' + (window.STATIC_VER || APP_VERSION.replace(/\./g, "")) + '" alt="logo">' +
            '</div>' +
            '<div class="m-about-title">客户管理平台</div>' +
            '<div class="m-about-version">版本 v' + esc(APP_VERSION) + ' · 构建 ' + esc(window.STATIC_VER || APP_VERSION.replace(/\./g, "")) + '</div>' +
            '<div class="m-about-credit">余辉制作</div>' +
        '</div>';
}

function mTopMenuAction(action) {
    var m = document.getElementById('mTopMenu');
    if (m) m.remove();
    if (action === 'settings') openSettingsAsSubPage();
    else if (action === 'about') openAbout();
    else if (action === 'clearCache') clearLocalCache();
}

// 清除本地缓存：仅清前端应用缓存（localStorage / sessionStorage），随后刷新页面重新拉取最新数据。
// 注意：不再调用原生 CustomerApp.clearAppCache()——其实现会 removeAllCookies 清掉 Flask 登录会话 cookie，
// 导致「清除缓存」后退出登录。登录态由服务端 session cookie 维持，与本地缓存无关，故跳过原生清缓存以保留登录。
// 主题偏好 mTheme 一并保留，避免清缓存后主题被重置。
function clearLocalCache() {
    try {
        var keepTheme = null;
        try { keepTheme = localStorage.getItem('mTheme'); } catch (e) {}
        localStorage.clear();
        sessionStorage.clear();
        if (keepTheme != null) { try { localStorage.setItem('mTheme', keepTheme); } catch (e) {} }
    } catch (e) {}
    showToast('缓存已清除，正在刷新…', 'success');
    setTimeout(function() { location.reload(true); }, 800);
}

// 设置页以「子页」方式进入：隐藏底栏（#1）、显示返回按钮、返回手势/按钮回到进入前的一级页（#2）。
// 不调用 switchPage，避免被当成顶级页（那样会显示底栏且返回走退出确认）。
function openSettingsAsSubPage() {
    var prev = _prevTopPage || 'tasks';
    var menu = document.getElementById('mTopMenu');
    if (menu) menu.remove();
    enterSubPage();          // 隐藏底栏 + 设置按钮、显示返回按钮、标记 m-subpage
    setHeaderMode('back');
    var titleEl = document.getElementById('pageTitle');
    if (titleEl) titleEl.textContent = '设置';
    // 返回函数：回到进入设置前的一级页
    navPush('settings', function() { switchPage(prev); });
    loadSettingsMobile();
}

// 删除事项（移动端长按触发）
async function deleteTaskMobile(id, title) {
    mConfirm('删除事项', '确定删除「' + (title || '该事项') + '」？此操作不可撤销。', function() {
        var key = 'task:' + id;
        optimisticWrite({
            applyLocal: function() {
                addPendingDelete(key);
                rerenderVisibleAfterMutation(); // 立即从当前可见视图隐藏（事项列表或客户详情）
            },
            submit: async function() { await api('/api/tasks/' + id, { method: 'DELETE' }); },
            onSuccess: function() {
                if (_allTasksMobile) _allTasksMobile = _allTasksMobile.filter(function(t) { return t.id !== id; });
                removePendingDelete(key);
                showToast('已删除', 'success');
            },
            rollback: function(err) {
                removePendingDelete(key);
                showToast('删除失败: ' + (err && err.message ? err.message : err), 'error');
                rerenderVisibleAfterMutation();
            }
        });
    });
}

// ==================== 客户管理 ====================

async function loadCustomersMobile(search = '', selectedCats = [], forceRefresh = false) {
    // selectedCats 支持字符串（兼容旧调用）和数组
    if (typeof selectedCats === 'string') {
        selectedCats = selectedCats ? [selectedCats] : [];
    }

    // 复用已拉取的客户数据：首次或强制刷新时才请求网络。
    if (forceRefresh || !window._allCustomersMobile) {
        window._allCustomersMobile = await api('/api/customers');
    }
    const allCustomers = window._allCustomersMobile;
    const content = document.getElementById('pageContent');

    // 分类数量统计逻辑已下移（见首次构建之后），确保 #mCustTypeMenu 已渲染进 DOM 后再写入数量。

    // 距离：优先复用已缓存的我方坐标，缺失时再请求一次设置
    let myLat = window._myLat, myLon = window._myLon;
    if (myLat == null || myLon == null) {
        let settings = {};
        try { settings = await api('/api/settings'); } catch(e) {}
        myLat = window._myLat = parseFloat(settings.my_latitude) || 30.358935;
        myLon = window._myLon = parseFloat(settings.my_longitude) || 114.323843;
    }
    allCustomers.forEach(c => {
        if (c.latitude && c.longitude) {
            c._dist = calcDistance(myLat, myLon, c.latitude, c.longitude);
        }
    });

    // 拉取每个客户的子待办数量（用于客户列表按子待办数量从高到低排序）
    // 子待办计数优先复用预加载缓存（preloadAllData 已填 window._custSubtaskCounts），
    // 缺失时才回源一次并写回缓存，避免每次进入客户页都多打一次接口。
    let subCounts = window._custSubtaskCounts;
    if (!subCounts) {
        try { subCounts = await api('/api/customers/subtask-counts') || {}; } catch (e) { subCounts = {}; }
        window._custSubtaskCounts = subCounts;
    }
    allCustomers.forEach(c => { c._subtaskCount = subCounts[c.id] || 0; });

    window._mCat = selectedCats;
    window._mSearch = search;

    // 首次进入才构建骨架（搜索栏+标签筛选固定不动）；之后只重渲染列表与标签，
    // 避免每次输入/点标签都重建搜索框导致光标跳走、页面整体重排（打字跳动、上移过度）。
    const firstBuild = !document.getElementById('mCustControls');

    const initialCat = (selectedCats && selectedCats[0]) || '';
    const catLabel = initialCat || '全部';

    if (firstBuild) {
        content.innerHTML = `
            <div class="m-biz-controls" id="mCustControls">
                <button type="button" class="m-biz-type-btn" id="mCustTypeBtn" onclick="toggleCustTypeMenu()">
                    <span id="mCustTypeLabel">${esc(catLabel)}</span>
                    <i class="m-icon m-biz-type-arrow" data-icon="chevronDown"></i>
                </button>
                <div class="m-biz-search">
                    <input id="mCustSearchInput" type="text" placeholder="搜索" value="${esc(search).replace(/"/g,'&quot;')}"
                        oninput="var v=this.value;clearTimeout(window._custTimer);window._custTimer=setTimeout(function(){onCustSearchInput(v)},200)">
                </div>
                <div class="m-biz-type-menu" id="mCustTypeMenu" style="display:none;">
                    <div class="m-biz-type-item ${initialCat === '' ? 'active' : ''}" data-cat="" onclick="selectCustType('')"><span class="m-biz-type-name">全部</span><span class="m-biz-type-count"></span></div>
                    <div class="m-popup-divider"></div>
                    <div class="m-biz-type-item ${initialCat === '核心要客' ? 'active' : ''}" data-cat="核心要客" onclick="selectCustType('核心要客')"><span class="m-biz-type-name">核心要客</span><span class="m-biz-type-count"></span></div>
                    <div class="m-popup-divider"></div>
                    <div class="m-biz-type-item ${initialCat === 'TOP20' ? 'active' : ''}" data-cat="TOP20" onclick="selectCustType('TOP20')"><span class="m-biz-type-name">TOP20</span><span class="m-biz-type-count"></span></div>
                    <div class="m-popup-divider"></div>
                    <div class="m-biz-type-item ${initialCat === '普通客户' ? 'active' : ''}" data-cat="普通客户" onclick="selectCustType('普通客户')"><span class="m-biz-type-name">普通客户</span><span class="m-biz-type-count"></span></div>
                </div>
            </div>
            <div id="mCustList"></div>
            <div style="height:72px;"></div>
            <button class="m-fab" onclick="addCustomerMobile()" aria-label="新增客户">${ICONS.add}</button>
        `;
        // 菜单关闭由 toggleCustTypeMenu 和 document click 自动处理
    } else {
        // 仅当搜索框未聚焦时才同步外部传入的值，避免打断用户正在进行的输入
        const input = document.getElementById('mCustSearchInput');
        if (input && document.activeElement !== input) input.value = search;
    }

    // 分类筛选菜单：各分类名称后追加（数量）。「全部」显示客户总数。
    // 必须放在下拉菜单渲染进 DOM 之后，否则首次进入时 #mCustTypeMenu 尚不存在、数量不生效。
    try {
        const _counts = {};
        allCustomers.forEach(c => {
            const _cat = c.category || '普通客户';
            _counts[_cat] = (_counts[_cat] || 0) + 1;
        });
        const _total = allCustomers.length;
        document.querySelectorAll('#mCustTypeMenu .m-biz-type-item').forEach(it => {
            const _cat = it.getAttribute('data-cat') || '';
            const _nameEl = it.querySelector('.m-biz-type-name');
            const _cntEl = it.querySelector('.m-biz-type-count');
            if (!_nameEl || !_cntEl) return;
            const _n = _cat ? (_counts[_cat] || 0) : _total;
            _cntEl.textContent = '（' + _n + '）';
        });
    } catch (e) { /* 静默 */ }

    renderCustomerList(search, selectedCats);
}


// 筛选下拉遮罩（复用长按弹窗效果：半透明+毛玻璃）
function _showMenuBackdrop(onClick) {
    var overlay = document.createElement('div');
    overlay.id = '_mb_backdrop';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:1050;background:rgba(0,0,0,0.35);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);animation:fadeIn .15s ease;';
    overlay.addEventListener('click', function(e) {
        if (onClick) onClick(e);
        overlay.remove();
    });
    document.body.appendChild(overlay);
}

// 点击左侧「企业类型」按钮：展开/收起下拉（与业务页一致的并排圆角胶囊样式）
function toggleCustTypeMenu() {
    var menu = document.getElementById('mCustTypeMenu');
    var btn = document.getElementById('mCustTypeBtn');
    if (!menu) return;
    var open = (menu.style.display === 'none' || menu.style.display === '');
    var bak = document.getElementById('_mb_backdrop');
    if (bak) { bak.remove(); bak = null; }
    if (open) {
        menu.style.display = 'block';
        menu.style.animation = 'fadeIn 0.15s ease';
        if (btn) btn.classList.add('is-open');
        _showMenuBackdrop(function() {
            menu.style.display = 'none';
            if (btn) btn.classList.remove('is-open');
        });
    } else {
        menu.style.display = 'none';
        if (btn) btn.classList.remove('is-open');
    }
}

// 选择企业类型：更新标签 + 高亮 + 收起 + 重新筛选列表
function selectCustType(cat) {
    var label = document.getElementById('mCustTypeLabel');
    var menu = document.getElementById('mCustTypeMenu');
    var btn = document.getElementById('mCustTypeBtn');
    if (label) label.textContent = cat || '全部';
    document.querySelectorAll('#mCustTypeMenu .m-biz-type-item').forEach(function(it) {
        it.classList.toggle('active', (it.getAttribute('data-cat') || '') === (cat || ''));
    });
    if (menu) menu.style.display = 'none';
    if (btn) btn.classList.remove('is-open');
    var _bak = document.getElementById('_mb_backdrop');
    if (_bak) _bak.remove();
    window._mCat = cat ? [cat] : [];
    loadCustomersMobile(window._mSearch || '', window._mCat);
}

// 搜索：按当前关键词过滤客户列表
function onCustSearchInput(v) {
    loadCustomersMobile(v, window._mCat || []);
}

// 渲染客户列表：仅更新列表区域（#mCustList），搜索框与标签保持不变
function renderCustomerList(search, selectedCats) {
    const listBox = document.getElementById('mCustList');
    if (!listBox) return;
    const allCustomers = window._allCustomersMobile || [];
    const searchLower = (search || '').toLowerCase();
    let filtered = allCustomers;
    if (search) {
        filtered = filtered.filter(c =>
            (c.company && c.company.toLowerCase().includes(searchLower)) ||
            (c.name && c.name.toLowerCase().includes(searchLower)) ||
            (c.phone && c.phone.includes(search))
        );
    }
    if (selectedCats.length > 0) {
        filtered = filtered.filter(c => selectedCats.includes(c.category || '普通客户'));
    }
    // 按子待办数量从高到低排序（相同数量时按原优先级排序，作为稳定兜底）
    const _prioRank = {
        '重要且紧急': 1, '高': 1,
        '重要不紧急': 2, '中': 2,
        '紧急不重要': 3,
        '不重要不紧急': 4, '低': 4
    };
    filtered.sort((a, b) =>
        (b._subtaskCount || 0) - (a._subtaskCount || 0) ||
        (_prioRank[a.priority] || 9) - (_prioRank[b.priority] || 9)
    );

    listBox.innerHTML = filtered.length === 0
        ? '<div class="m-empty"><div class="icon"><i class="m-icon" data-icon="empty"></i></div>暂无客户</div>'
        : `<div class="m-group-list">${filtered.map(c => {
            const cNames = (c.contact || '').split('||');
            const cPhones = (c.phone || '').split('||');
            const primaryName = cNames[0] || c.name || '';
            const primaryPhone = cPhones[0] || '';
            // 第二行显示联系人/电话/优先级（不展示子待办数量，仅作为排序依据）
            const sub = [primaryName, primaryPhone, c.priority].filter(Boolean).join(' · ');
            return `
            <div class="m-group-item" data-id="${c.id}" onclick="navPush('cust:'+${c.id}, function(){switchPage('customers')});viewCustomerMobile(${c.id})">
                <div class="m-group-info">
                    <div class="m-group-title">${esc(c.company || c.name || '-')}</div>
                    <div class="m-group-subtitle">${esc(sub)}</div>
                </div>
                <div class="m-group-chevron"><i class="m-icon" data-icon="chevronRight"></i></div>
            </div>`;
        }).join('')}</div>`;
    renderIcons(listBox); // 嵌套重绘后补图标，否则右侧箭头不显示
    // 一级页面长按删除——客户列表
    // 构建 id→客户 哈希索引（O(1)），替代每个列表项的线性扫描（原 O(n²)）
    var _custById = new Map();
    filtered.forEach(function(x) { _custById.set(x.id, x); });
    listBox.querySelectorAll('.m-group-item[data-id]').forEach(function(el) {
        var id = parseInt(el.getAttribute('data-id'), 10);
        var c = _custById.get(id);
        if (!c) return;
        var cname = c.company || c.name || '';
        bindLongPress(el, function() {
            mConfirm('删除客户', '确定删除「' + cname + '」？此操作不可撤销。', function() {
                deleteCustomerMobile(id, cname);
            });
        });
    });
}

// ==================== 业务管理（业务 / 具体业务类型，按业务类型 business_type/package_type 直接归类） ====================

let allBusinessesMobile = [];
let activeBizTabMobile = 'all';

// ⚠️ 架构约定（2.6.1 合并重构）：businesses / ledgers 两表已合并为单表 businesses（超集字段池）。
// 业务页直接以【具体业务类型】作为筛选维度：业务(全部) + 各具体类型（10 个）。
// 每条记录按自身 business_type 归类；字段按「业务类型 → 字段清单(BIZ_TYPE_FIELDS)」模块化选配。
// 移网 已彻底移除；融合 → 宽带；字段「层级」→「业务层级」；关联主卡由串号 parent_number 改为 FK parent_id（指向 businesses.id）。
var BIZ_TYPE_LIST = ['互联网专线', '电路', '算网项目', 'U+产品', '数智惠企', '冰激凌', '魔方卡', '副卡', '宽带', '固话'];
// 业务类型下拉分两竖排（2.6.9）：左竖排 / 右竖排。两者并集 = BIZ_TYPE_LIST，确保全部类型仍可选。
var BIZ_TYPE_LIST_LEFT = ['互联网专线', '电路', '算网项目', 'U+产品', '数智惠企'];
var BIZ_TYPE_LIST_RIGHT = ['冰激凌', '魔方卡', '副卡', '宽带', '固话'];
function bizTabLabel(tab) { return tab === 'all' ? '全部业务' : tab; }
function bizTypeMenuHtml() {
    function colHtml(list) {
        return '<div class="m-biz-type-col">' + list.map(function(t) {
            return '<div class="m-biz-type-item ' + (activeBizTabMobile === t ? 'active' : '') + '" data-tab="' + t + '" onclick="selectBizType(\'' + t + '\')">' + t + '</div>';
        }).join('') + '</div>';
    }
    var h = '<div class="m-biz-type-item m-biz-type-item--all ' + (activeBizTabMobile === 'all' ? 'active' : '') + '" data-tab="all" onclick="selectBizType(\'all\')">全部业务</div>';
    h += '<div class="m-popup-divider"></div>';
    h += '<div class="m-biz-type-cols">' + colHtml(BIZ_TYPE_LIST_LEFT) + colHtml(BIZ_TYPE_LIST_RIGHT) + '</div>';
    return h;
}

// 业务列表项（业务 Tab 列表 / 客户详情业务区块 共用，保证两处展示完全一致，消除重复 markup）。
// navigateExpr：点击项的导航表达式（不同入口返回目标不同）。
function bizGroupItemHtml(b, navigateExpr) {
    var sub = [esc(b.sub_type || '-'), esc(b.business_level || ''), esc(b.business_number || ''), (b.date || '')].filter(Boolean).join(' · ');
    var pendingTag = b._pending ? ' <span style="color:#ff9f0a;font-size:11px;margin-left:4px;">同步中…</span>' : '';
    var click = b._pending ? 'void(0)' : navigateExpr;
    return '<div class="m-group-item" data-id="' + b.id + '" onclick="' + click + '">' +
        '<div class="m-group-info">' +
            '<div class="m-group-title">' + esc(b.company_name || '-') + pendingTag + '</div>' +
            '<div class="m-group-subtitle">' + sub + '</div>' +
        '</div>' +
        '<div class="m-group-chevron"><i class="m-icon" data-icon="chevronRight"></i></div>' +
    '</div>';
}

// ===== 模块化字段：字段单一数据源（2.6.1）=====
// BIZ_FIELD_POOL：每个字段的元数据（key 与 businesses 表列名一致）；label/type 仅控制前端展示与输入控件。
// BIZ_TYPE_FIELDS：每个业务类型选配的字段 key 有序列表（取代原 BIZ_SCHEMA/CONTRACT_FIELDS/LEDGER_FIELDS）。
// 日后某类型要加/改字段，只改它自己的 BIZ_TYPE_FIELDS 条目，不动通用渲染器、不影响其他类型。
var BIZ_FIELD_POOL = {
    business_level:  { key: 'business_level', label: '业务层级', type: 'text' },
    contract_amount: { key: 'contract_amount', label: '合同金额 (¥)', type: 'number' },
    number:          { key: 'number', label: '号码', type: 'text' },
    contract_code:   { key: 'contract_code', label: '合同编码', type: 'text' },
    start_date:      { key: 'start_date', label: '开始时间', type: 'date' },
    end_date:        { key: 'end_date', label: '结束时间', type: 'date' },
    business_address:{ key: 'business_address', label: '业务地址', type: 'text' },
    date:            { key: 'date', label: '办理日期', type: 'date' },
    user_name:       { key: 'user_name', label: '使用人', type: 'text' },
    parent_id:       { key: 'parent_id', label: '关联主卡', type: 'parent' },
    notes:           { key: 'notes', label: '备注', type: 'textarea' }
};
// 10 个业务类型 → 选配字段 key 列表（顺序即表单顺序）
var BIZ_TYPE_FIELDS = {
    '互联网专线': ['business_level', 'contract_amount', 'number', 'start_date', 'end_date', 'business_address', 'contract_code', 'notes'],
    '电路':       ['business_level', 'contract_amount', 'number', 'start_date', 'end_date', 'business_address', 'contract_code', 'notes'],
    '算网项目':   ['business_level', 'contract_amount', 'number', 'start_date', 'end_date', 'contract_code', 'notes'],
    'U+产品':     ['business_level', 'contract_amount', 'number', 'start_date', 'end_date', 'contract_code', 'notes'],
    '数智惠企':   ['date', 'number', 'business_level', 'user_name', 'notes'],
    '冰激凌':     ['date', 'number', 'business_level', 'user_name', 'notes'],
    '魔方卡':     ['date', 'number', 'user_name', 'notes'],
    '副卡':       ['date', 'number', 'user_name', 'notes', 'parent_id'],
    '宽带':       ['date', 'number', 'user_name', 'business_address', 'notes', 'parent_id'],
    '固话':       ['date', 'number', 'user_name', 'business_address', 'notes', 'parent_id']
};
// 主卡 / 子卡类型：子卡（副卡/宽带/固话）的 关联主卡 下拉列出主卡（数智惠企/冰激凌）
var BIZ_MAIN_TYPES = ['数智惠企', '冰激凌'];
var BIZ_CHILD_TYPES = ['副卡', '宽带', '固话'];
// 内联子卡（在主卡新增/编辑界面挂接）的录入字段：与「编辑该子卡」(syncBizEditTypeUI) 完全对齐——
// 直接取 BIZ_TYPE_FIELDS[子卡类型] 去掉关联主卡(parent_id，内联子卡固定关联当前主卡) 的字段集，
// 子卡本身无「业务层级」字段故不在其中。改字段只改 BIZ_TYPE_FIELDS 一处即双路径同步，无需两处维护。
var BIZ_SUB_INLINE_FIELDS = {};
BIZ_CHILD_TYPES.forEach(function(t) {
    BIZ_SUB_INLINE_FIELDS[t] = (BIZ_TYPE_FIELDS[t] || []).filter(function(k) { return k !== 'parent_id'; });
});
// 主卡底部内联子卡上限（需求：副卡≤4、宽带≤2、固话≤1）
var BIZ_SUB_MAX = { '副卡': 4, '宽带': 2, '固话': 1 };
// 取当前搜索框内容（缓存恢复/切换标签时保持搜索词）
var _bizSearchCache = ''; // 业务页搜索词持久化：跨「进入详情→返回列表」的 pageContent 重建不丢失
function _bizCurrentSearch() {
    var el = document.getElementById('mBizSearch');
    if (el && el.value) return el.value;
    return _bizSearchCache || '';
}

// 客户列表「新增/编辑/删除后自动刷新」标记：
// 平时进入「客户」页走会话缓存（数据缓存 window._allCustomersMobile + switchPage 快照缓存），
// 仅在增删改成功后置位，下次进入时由 switchPage 强制重新拉取并渲染，令改动立即可见。
window._customersNeedRefresh = false;

async function loadBusinessesMobile() {
    var content = document.getElementById('pageContent');
    // 兼容旧会话快照：若 activeBizTabMobile 不是合法 tab（旧 dual/compute/other），归位到「业务」
    if (activeBizTabMobile !== 'all' && BIZ_TYPE_LIST.indexOf(activeBizTabMobile) === -1) activeBizTabMobile = 'all';

    // 首次渲染：左侧类型下拉按钮 + 右侧搜索框（并排圆角）
    if (!document.getElementById('mBizControls')) {
        content.innerHTML =
            '<div class="m-biz-controls" id="mBizControls">' +
                '<button type="button" class="m-biz-type-btn" id="mBizTypeBtn" onclick="toggleBizTypeMenu()">' +
                    '<span id="mBizTypeLabel">' + bizTabLabel(activeBizTabMobile) + '</span>' +
                    '<i class="m-icon m-biz-type-arrow" data-icon="chevronDown"></i>' +
                '</button>' +
                '<div class="m-biz-search">' +
                    '<input type="text" id="mBizSearch" placeholder="搜索"' +
                    ' oninput="var v=this.value;clearTimeout(window._bizTimer);window._bizTimer=setTimeout(function(){onBizSearchInput(v)},200)">' +
                '</div>' +
                '<div class="m-biz-type-menu m-biz-type-menu--cols" id="mBizTypeMenu" style="display:none;max-height:62vh;overflow-y:auto;-webkit-overflow-scrolling:touch;">' +
                    bizTypeMenuHtml() +
                '</div>' +
            '</div>' +
            '<div id="mBizResultContainer" style="padding-bottom:72px;"></div>' +
            '<button class="m-fab" onclick="mBizAdd()" aria-label="新增">' + ICONS.add + '</button>';
        var _sNew = document.getElementById('mBizSearch');
        if (_sNew) _sNew.value = _bizSearchCache || ''; // 回填搜索词，避免返回后框空但列表已筛
        await renderBizList(activeBizTabMobile, _bizCurrentSearch());
    } else {
        // 控件已存在（非首次、无缓存重建），刷新当前标签列表
        var _sOld = document.getElementById('mBizSearch');
        if (_sOld) _sOld.value = _bizSearchCache || '';
        await renderBizList(activeBizTabMobile, _bizCurrentSearch());
    }
}

// 拉取全部业务（带缓存），再按标签 + 搜索渲染
async function renderBizList(tab, search) {
    if (!allBusinessesMobile || allBusinessesMobile.length === 0) {
        try {
            allBusinessesMobile = await api('/api/business');
        } catch(e) {
            allBusinessesMobile = [];
        }
    }
    renderBizListSync(tab, search);
}

// 仅用已加载的 allBusinessesMobile 重新渲染当前标签列表（不发起网络请求）。
// 单表 businesses 统一展示，按具体业务类型(business_type)归类；业务=全部。
function renderBizListSync(tab, search) {
    var container = document.getElementById('mBizResultContainer');
    if (!container) return;
    var kw = (search || '').trim().toLowerCase();

    // 归一化：每条记录携带 sub_type(具体业务类型，作为筛选依据) 与展示字段
    var items = [];
    (allBusinessesMobile || []).forEach(function(b) {
        items.push({
            id: b.id,
            company_name: b.company_name || '-',
            sub_type: b.business_type || '',
            business_level: b.business_level || '',
            contract_amount: b.contract_amount,
            contract_code: b.contract_code || '',
            business_number: b.number || '',
            date: b.date || '',
            parent_id: b.parent_id
        });
    });
    // 拼接乐观更新的临时记录（提交成功后由 onSuccess 移除，失败由 rollback 移除）
    (window._pendingCreates || []).forEach(function(p) {
        if (p.src !== 'business') return;
        if (BIZ_CHILD_TYPES.indexOf(p.sub_type) !== -1) return; // 内联创建的子卡不单独展示
        items.push({
            id: 'P' + p.tmpId,
            rawId: -1,
            _pending: true,
            company_name: p.company_name,
            sub_type: p.sub_type,
            business_level: p.business_level || '',
            contract_amount: p.contract_amount,
            contract_code: p.contract_code || '',
            business_number: p.business_number || '',
            date: p.date || '',
            parent_id: null
        });
    });

    // 乐观删除：过滤掉标记为待删除的记录
    items = items.filter(function(b) {
        if (b._pending) return true;
        var key = 'biz:' + b.id;
        return !isPendingDelete(key);
    });

    var list = items.filter(function(b) {
        if (b.parent_id) return false; // 子卡（关联主卡存在）不在列表展示，仅展示主卡
        if (b._pending && BIZ_CHILD_TYPES.indexOf(b.sub_type) !== -1) return false; // 内联子卡临时态不展示（已落库/孤儿子卡照常展示）
        if (tab !== 'all' && b.sub_type !== tab) return false;
        if (kw) {
            var hay = ((b.company_name || '') + ' ' + (b.sub_type || '') + ' ' + (b.contract_code || '') + ' ' + (b.business_number || '')).toLowerCase();
            if (hay.indexOf(kw) === -1) return false;
        }
        return true;
    });

    // 业务类型与数据未匹配提醒：存在 business_type 不在标准 BIZ_TYPE_LIST 的记录
    // （如历史遗留「移网 / 融合」或空值），其详情将无法按字段正常渲染。
    // 统计主卡（含临时态）中类型不匹配的条数，在列表顶部加提醒 banner。
    var _mm = 0;
    (allBusinessesMobile || []).forEach(function(b) { if (BIZ_TYPE_LIST.indexOf(b.business_type) === -1) _mm++; });
    (window._pendingCreates || []).forEach(function(p) {
        if (p.src === 'business' && BIZ_TYPE_LIST.indexOf(p.sub_type) === -1) _mm++;
    });
    var _warnHtml = _mm > 0
        ? '<div class="m-warn-banner">⚠️ 有 ' + _mm + ' 条业务的「业务类型」不在标准类型中（如历史遗留的「移网 / 融合」或空值），类型与数据未匹配，详情可能无法正常显示字段。建议在 PC 端校正。</div>'
        : '';

    var _listHtml = list.length === 0
        ? '<div class="m-empty" style="padding:20px;"><div class="icon"><i class="m-icon" data-icon="empty"></i></div><div class="title">暂无业务</div></div>'
        : '<div class="m-group-list">' + list.map(function(b) {
            return bizGroupItemHtml(b, "navPush('biz:'+" + b.id + ", function(){switchPage('business')});viewBusinessMobile(" + b.id + ")");
        }).join('') + '</div>';
    container.innerHTML = _warnHtml + _listHtml;
    renderIcons(container); // 嵌套重绘后补图标，否则右侧箭头不显示

    // 长按删除：全部走 businesses 删除逻辑
    container.querySelectorAll('.m-group-item[data-id]').forEach(function(el) {
        var idAttr = el.getAttribute('data-id');
        if (idAttr && idAttr.charAt(0) === 'P') return; // 临时记录不绑定删除
        var id = parseInt(idAttr, 10);
        var b = (allBusinessesMobile || []).find(function(x) { return x.id === id; });
        if (!b) return;
        bindLongPress(el, function() {
            confirmDeleteBusiness(id, b.company_name || '');
        });
    });
}

async function switchBizTab(tab) {
    activeBizTabMobile = tab;
    syncBizTabUI(tab);
    await renderBizList(tab, _bizCurrentSearch());
}

// 仅同步业务页子 Tab 的“显隐 / 标签 / 下拉高亮”到指定 tab（不发起网络请求）。
// 用于快照恢复时让展示与 activeBizTabMobile 保持一致：快照已含两个子 Tab 的数据，
// 只需切换可见性，避免每次返回都重新拉取（消除黑屏/重载闪烁）。
function syncBizTabUI(tab) {
    if (tab !== 'all' && BIZ_TYPE_LIST.indexOf(tab) === -1) tab = 'all';
    var label = document.getElementById('mBizTypeLabel');
    if (label) label.textContent = bizTabLabel(tab);
    document.querySelectorAll('#mBizTypeMenu .m-biz-type-item').forEach(function(it) {
        it.classList.toggle('active', it.getAttribute('data-tab') === tab);
    });
}

// 点击左侧类型按钮：展开/收起下拉
function toggleBizTypeMenu() {
    var menu = document.getElementById('mBizTypeMenu');
    var btn = document.getElementById('mBizTypeBtn');
    if (!menu) return;
    var open = (menu.style.display === 'none' || menu.style.display === '');
    var bak = document.getElementById('_mb_backdrop');
    if (bak) { bak.remove(); bak = null; }
    if (open) {
        menu.style.display = 'block';
        menu.style.animation = 'fadeIn 0.15s ease';
        if (btn) btn.classList.add('is-open');
        _showMenuBackdrop(function() {
            menu.style.display = 'none';
            if (btn) btn.classList.remove('is-open');
        });
    } else {
        menu.style.display = 'none';
        if (btn) btn.classList.remove('is-open');
    }
}

// 选择类型：更新标签 + 高亮 + 收起 + 切换列表
async function selectBizType(tab) {
    var label = document.getElementById('mBizTypeLabel');
    var menu = document.getElementById('mBizTypeMenu');
    var btn = document.getElementById('mBizTypeBtn');
    if (label) label.textContent = bizTabLabel(tab);
    document.querySelectorAll('#mBizTypeMenu .m-biz-type-item').forEach(function(it) {
        it.classList.toggle('active', it.getAttribute('data-tab') === tab);
    });
    if (menu) menu.style.display = 'none';
    if (btn) btn.classList.remove('is-open');
    var _bak2 = document.getElementById('_mb_backdrop');
    if (_bak2) _bak2.remove();
    await switchBizTab(tab);
}

// 搜索：按当前激活的选项卡过滤对应列表
function onBizSearchInput(v) {
    _bizSearchCache = v || ''; // 实时缓存，使返回列表后搜索词仍生效
    renderBizListSync(activeBizTabMobile, v);
}

// 业务页悬浮加号：直接打开业务引导页（关联客户 + 业务类型），由 addBusinessEntryMobile 渲染。
// ledgers 表在 2.1.1 起并入业务统一展示，新增入口即引导页里的「业务类型」下拉（含数智惠企/冰激凌/魔方卡/副卡等）。
function mBizAdd() {
    // 在业务标签页内点加号：业务类型默认选中当前标签（2.6.9）
    var t = (activeBizTabMobile && activeBizTabMobile !== 'all') ? activeBizTabMobile : '';
    addBusinessEntryMobile(null, null, t);
}

// ==================== 业务新增统一引导页（关联客户 + 业务类型，下方动态出子表单） ====================

var _bizEntryCustomer = null; // {id, name}

// 关联客户搜索无匹配时，用输入框中的新名称新建客户并自动选中（新增业务/事项/编辑业务通用）
function createCustomerAndSelect(ev, opts) {
    var input = document.getElementById(opts.searchInputId);
    var name = (input ? input.value : '').trim();
    if (!name) { showToast('请先输入客户名', 'error'); return; }
    var tmpId = 'T' + Date.now() + '_' + Math.floor(Math.random() * 1e4);
    var created = null;
    // 乐观选择：立即显示「已选择」，后台建客户；提交成功换真实 id，失败回滚清空选择
    optimisticWrite({
        applyLocal: function() {
            var hid = document.getElementById(opts.hiddenId);
            var lab = document.getElementById(opts.labelId);
            var lst = document.getElementById(opts.listId);
            if (hid) hid.value = tmpId;
            if (lab) lab.innerHTML = '<i class="m-icon" data-icon="done"></i> 已选择: <strong>' + esc(name) + '</strong>';
            if (lst) lst.style.display = 'none';
            if (opts.onType === 'bizentry') { _bizEntryCustomer = { id: tmpId, name: name }; }
            var pcr, pcj;
            window._pendingCustomerCreate = new Promise(function(res, rej) { pcr = res; pcj = rej; });
            window._pcr = pcr; window._pcj = pcj;
        },
        submit: async function() {
            try {
                created = await api('/api/customers', { method: 'POST', body: JSON.stringify({ company: name, name: name }) });
                return created;
            } catch (e) {
                var msg = (e && e.message) ? e.message : '';
                if (msg.indexOf('已存在') !== -1) {
                    var all = (window._allBizEntryCustomers || []).concat(window._allTaskCustomers || [], window._allBizCustomers || []);
                    var hit = all.find(function(x) { return (x.company || x.name || '') === name; });
                    if (hit) { created = hit; return hit; }
                    try { var cs = await api('/api/customers'); var h2 = cs.find(function(x) { return (x.company || x.name || '') === name; }); if (h2) { created = h2; return h2; } } catch (_) {}
                }
                throw e;
            }
        },
        onSuccess: function() {
            var c = created;
            var realId = c && c.id;
            var hid = document.getElementById(opts.hiddenId);
            var lab = document.getElementById(opts.labelId);
            var lst = document.getElementById(opts.listId);
            if (hid) hid.value = realId;
            if (lab) lab.innerHTML = '<i class="m-icon" data-icon="done"></i> 已选择: <strong>' + esc(c.company || c.name || name) + '</strong>';
            if (lst) lst.style.display = 'none';
            if (opts.onType === 'bizentry') { _bizEntryCustomer = { id: realId, name: c.company || c.name || name }; }
            // 合并进各表单客户缓存，避免再次搜索时重复新建
            [window._allBizEntryCustomers, window._allTaskCustomers, window._allBizCustomers].forEach(function(arr) {
                if (arr && arr.length && !arr.some(function(x) { return String(x.id) === String(realId); })) arr.push(c);
            });
            // 关联新建的客户同步进「客户」列表：丢弃客户缓存并置位需刷新标记，
            // 切到客户页时 switchPage 会强制重拉，确保新客户立即可见（2.6.9 修复：关联新建后客户列表不更新）
            markCustomersDirty();
            if (window._pcr) window._pcr(realId);
            window._pendingCustomerCreate = null;
            showToast('已新建并选择客户：' + (c.company || c.name || name), 'success');
        },
        rollback: function(err) {
            var hid = document.getElementById(opts.hiddenId);
            var lab = document.getElementById(opts.labelId);
            var lst = document.getElementById(opts.listId);
            if (hid) hid.value = '';
            if (lab) lab.innerHTML = '请搜索并选择客户';
            if (lst) lst.style.display = 'block';
            if (opts.onType === 'bizentry') { _bizEntryCustomer = null; }
            if (window._pcj) window._pcj(err);
            window._pendingCustomerCreate = null;
            showToast('新建失败：' + (err && err.message ? err.message : err), 'error');
        }
    });
}

// 无匹配时的「用新名称新建」条目 HTML
function custCreateRowHtml(opts) {
    var id = opts.searchInputId, hid = opts.hiddenId, lab = opts.labelId, lst = opts.listId, onType = opts.onType || '';
    var kw = esc(opts.kw || '');
    return '<div class="m-cust-create" onclick="createCustomerAndSelect(event, {searchInputId:\'' + id + '\',hiddenId:\'' + hid + '\',labelId:\'' + lab + '\',listId:\'' + lst + '\',onType:\'' + onType + '\'})" ' +
        'style="padding:14px 12px;text-align:center;color:var(--m-accent,#007AFF);font-size:13px;cursor:pointer;line-height:1.6;">' +
        '未找到匹配客户，使用 <strong>' + kw + '</strong> 新建数据</div>';
}

// 关联客户：完全复用「事项」的搜索选择逻辑与样式（m-cust-option 列表、done 标签）
function filterBizEntryCustomers(kw) {
    var k = (kw || '').trim().toLowerCase();
    var list = document.getElementById('mBizEntryCustList');
    var label = document.getElementById('mBizEntryCustLabel');
    if (!list || !label) return;
    if (!window._allBizEntryCustomers) {
        api('/api/customers').then(function(cs) {
            window._allBizEntryCustomers = cs;
            filterBizEntryCustomers(k);
        });
        return;
    }
    if (!k) { list.style.display = 'none'; label.textContent = '请搜索并选择客户'; return; }
    var cs = window._allBizEntryCustomers || [];
    var filtered = cs.filter(function(c) { return (c.company || c.name || '').toLowerCase().includes(k); });
    if (!filtered.length) {
        list.innerHTML = custCreateRowHtml({ searchInputId: 'mBizEntryCustSearch', hiddenId: 'mBizEntryCustomerId', labelId: 'mBizEntryCustLabel', listId: 'mBizEntryCustList', onType: 'bizentry', kw: kw });
        list.style.display = 'block';
        return;
    }
    list.innerHTML = filtered.map(function(c, i) {
        return '<div class="m-cust-option" data-id="' + c.id + '" data-name="' + (c.company || c.name || '').replace(/"/g, '&quot;') + '"' +
            ' style="padding:10px 12px;cursor:pointer;border-bottom:' + (i < filtered.length - 1 ? '1px solid #f0f0f0' : 'none') + ';font-size:14px;"' +
            ' onmouseover="this.style.background=\'#f0f4ff\'" onmouseout="this.style.background=\'\'"' +
            ' onclick="selectBizEntryCustomer(' + c.id + ',\'' + (c.company || c.name || '').replace(/'/g, '') + '\')">' +
            '<strong>' + (c.company || c.name || '-') + '</strong>' +
            '<span style="float:right;color:#888;font-size:12px;">' + (c.category || '') + '</span>' +
            '</div>';
    }).join('');
    list.style.display = 'block';
}

function selectBizEntryCustomer(id, name) {
    _bizEntryCustomer = { id: id, name: name };
    var s = document.getElementById('mBizEntryCustSearch');
    var h = document.getElementById('mBizEntryCustomerId');
    var l = document.getElementById('mBizEntryCustLabel');
    if (s) s.value = name;
    if (h) h.value = id;
    if (l) l.innerHTML = '<i class="m-icon" data-icon="done"></i> 已选择: <strong>' + name + '</strong>';
    var list = document.getElementById('mBizEntryCustList');
    if (list) list.style.display = 'none';
    // 若业务类型已预选（如在标签页内点加号），选完客户立即出对应子表单（2.6.9）
    var _sub = document.getElementById('mBizEntrySubtype');
    if (_sub && _sub.value) onBizEntrySubtypeChange();
    renderIcons(document.body);
}

// 通用「选项面板」：居中 m-popup-card 弹窗（复用 mPopupBase / mPopupCard 统一风格）。
// options: [{value,label}]；currentValue 命中项高亮；点击选项回调 onPick(value)；底部「取消」行不回调。
function mOptionSheet(title, options, currentValue, onPick) {
    var overlay = mPopupBase({ id: 'mOptionSheetOverlay' });
    var rows = options.map(function(o) {
        var active = (String(o.value) === String(currentValue)) ? ' active' : '';
        return '<div class="m-popup-row' + active + '" data-v="' + esc(String(o.value)) + '">' + esc(o.label) + '</div>';
    }).join('<div class="m-popup-divider"></div>');
    overlay.innerHTML = mPopupCard(
        '<div style="padding:16px 16px 8px;font-size:13px;color:var(--m-text-secondary);text-align:center;">' + esc(title) + '</div>' +
        '<div class="m-popup-divider"></div>' +
        rows +
        '<div class="m-popup-divider"></div>' +
        '<div class="m-popup-row" style="justify-content:center;color:var(--m-text-secondary);" data-cancel="1">取消</div>'
    , 'width:84%;max-width:320px;max-height:72vh;overflow-y:auto;');
    overlay.querySelectorAll('.m-popup-row').forEach(function(row) {
        row.addEventListener('click', function() {
            if (row.getAttribute('data-cancel')) { overlay.remove(); return; }
            var v = row.getAttribute('data-v');
            overlay.remove();
            if (onPick) onPick(v);
        });
    });
    document.body.appendChild(overlay);
}

// 业务类型选择：复用全局 mOptionSheet（m-popup-card 风格），取代原生 <select>。
// 选定后写入隐藏 input(opts.hiddenId) 并更新按钮文案(opts.labelId)，回调 opts.onChange(value)。
function openBizTypePicker(opts) {
    opts = opts || { hiddenId: 'mBizEntrySubtype', labelId: 'mBizEntryTypeLabel', onChange: onBizEntrySubtypeChange };
    var cur = (document.getElementById(opts.hiddenId) || {}).value || '';
    var options = BIZ_TYPE_LIST.map(function(t) { return { value: t, label: t }; });
    mOptionSheet('选择业务类型', options, cur, function(v) {
        var h = document.getElementById(opts.hiddenId); if (h) h.value = v;
        var l = document.getElementById(opts.labelId); if (l) l.textContent = v;
        if (opts.onChange) opts.onChange(v);
    });
}

function addBusinessEntryMobile(returnFn, presetCustomer, presetType) {
    enterSubPage();
    navPush('addbizentry', returnFn || function() { switchPage('business'); });
    window._editingBizEntry = null;
    // 进入新增引导页即清空上次残留的关联客户（2.6.9：修复「保留前一次关联客户」）；
    // 仅当由客户详情页带预设客户进来时才保留（presetCustomer）。
    if (presetCustomer && presetCustomer.id) {
        _bizEntryCustomer = { id: presetCustomer.id, name: presetCustomer.name };
    } else {
        _bizEntryCustomer = null;
    }
    var presetTypeVal = (presetType && BIZ_TYPE_LIST.indexOf(presetType) !== -1) ? presetType : '';
    var content = document.getElementById('pageContent');
    document.getElementById('pageTitle').textContent = '新增业务';
    var custName = _bizEntryCustomer ? _bizEntryCustomer.name : '';
    var custId = _bizEntryCustomer ? _bizEntryCustomer.id : '';
    content.innerHTML =
        '<div class="m-card">' +
            '<div class="form-group"><label>关联客户 *</label>' +
                '<input type="text" class="form-control" id="mBizEntryCustSearch" placeholder="搜索" style="font-size:13px;" oninput="filterBizEntryCustomers(this.value)" autocomplete="off" value="' + custName.replace(/"/g, '&quot;') + '">' +
                '<input type="hidden" id="mBizEntryCustomerId" value="' + custId + '">' +
                '<div id="mBizEntryCustList" class="m-popup-card" style="max-height:240px;overflow-y:auto;border:1px solid var(--m-border);box-shadow:0 12px 40px rgba(0,0,0,0.15);background:var(--m-card);margin-top:6px;display:none;"></div></div>' +
            '<div style="font-size:12px;color:#888;margin-bottom:8px;" id="mBizEntryCustLabel">' + (custName ? '<i class="m-icon" data-icon="done"></i> 已选择: <strong>' + custName + '</strong>' : '请搜索并选择客户') + '</div>' +
            '<div class="form-group"><label>业务类型 *</label>' +
                '<input type="hidden" id="mBizEntrySubtype" value="' + esc(presetTypeVal) + '">' +
                '<button type="button" class="form-control" id="mBizEntryTypeBtn" style="display:flex;align-items:center;justify-content:space-between;cursor:pointer;text-align:left;" onclick="openBizTypePicker({hiddenId:\'mBizEntrySubtype\',labelId:\'mBizEntryTypeLabel\',onChange:onBizEntrySubtypeChange})">' +
                    '<span id="mBizEntryTypeLabel">' + (presetTypeVal ? esc(presetTypeVal) : '请选择业务类型') + '</span>' +
                    '<i class="m-icon" data-icon="chevronDown"></i>' +
                '</button>' +
            '</div>' +
        '</div>' +
        '<div id="mBizEntryForm"></div>';
    if (custName && !window._allBizEntryCustomers) {
        api('/api/customers').then(function(cs) { window._allBizEntryCustomers = cs; });
    }
    // 标签页内点加号带 presetType 且已预选客户时，进入即出对应子表单（2.6.9）
    if (presetTypeVal && _bizEntryCustomer && _bizEntryCustomer.id) {
        onBizEntrySubtypeChange();
    }
    resetPageScroll();
    renderIcons(content);
}

// 从客户详情页「新增业务」入口：预选该客户并打开业务引导页（用户再选业务类型）
function addBizEntryForCustomer(cid, cname) {
    addBusinessEntryMobile(function() { viewCustomerMobile(cid); }, { id: cid, name: cname }, '');
}

// 选中具体「业务类型」后，由其决定落哪个存储表并出对应录入表单，不再有中间「分类」层。
function onBizEntrySubtypeChange() {
    var sub = (document.getElementById('mBizEntrySubtype').value || '').trim();
    var box = document.getElementById('mBizEntryForm');
    if (!box) return;
    if (!sub) { box.innerHTML = ''; return; }
    if (!_bizEntryCustomer || !_bizEntryCustomer.id) {
        showToast('请先选择关联客户', 'error');
        document.getElementById('mBizEntrySubtype').value = '';
        var _bt = document.getElementById('mBizEntryTypeLabel'); if (_bt) _bt.textContent = '请选择业务类型';
        return;
    }
    renderBizForm(sub);
}

// 合同业务录入表单（落 businesses）。2.4.1 起每个具体类型独立渲染，不再共用一张分支表单，方便后续单独调整。
function bizFormFieldHtml(f, prefix, defaultValue) {
    var id = prefix + f.key;
    var dv = (defaultValue != null && defaultValue !== '') ? defaultValue : '';
    if (f.type === 'textarea') {
        return '<div class="form-group"><label>' + f.label + '</label><textarea class="form-control" id="' + id + '" rows="3">' + esc(dv) + '</textarea></div>';
    }
    var ctrl = '<input type="' + (f.type === 'number' ? 'number' : (f.type === 'date' ? 'date' : 'text')) + '" class="form-control" id="' + id + '"' + (f.type === 'number' ? ' step="any"' : '') + (dv ? ' value="' + esc(dv) + '"' : '') + '>';
    return '<div class="form-group"><label>' + f.label + '</label>' + ctrl + '</div>';
}

// 业务字段展示值（详情页复用）：金额带 ¥、日期取 YYYYMM、空值显示 -
function bizFieldDisplay(f, raw) {
    if (f.type === 'number') return (raw != null && raw !== '' && !isNaN(Number(raw))) ? '¥' + Number(raw).toLocaleString() : '-';
    if (f.type === 'date') return raw ? String(raw).replace(/-/g, '').substring(0, 6) : '-';
    return (raw != null && raw !== '') ? raw : '-';
}
// 通用录入表单（2.6.1 模块化：按 BIZ_TYPE_FIELDS[type] 渲染字段，取代 BIZ_SCHEMA 双分支）。
// 输入控件 id 统一 mf_<key>，保存时按字段清单循环收集，与具体物理表解耦（单表 businesses）。
// 关联主卡字段（搜索菜单）通用模板：新增与编辑共用，确保两套 UI 完全一致。
// prefix: 'mf_'(新增) / 'mbiz_'(编辑)；curPid: 当前主卡 id(可空)；curLabelHtml: 已转义/组装好的展示文案（curPid 为空时传"不关联（独立副卡）"）。
function bizParentFieldHtml(prefix, curPid, curLabelHtml) {
    return '<div class="form-group"><label>关联主卡（可选）</label>' +
        '<input type="text" class="form-control" id="' + prefix + 'parent_search" placeholder="搜索主卡号码/公司/使用人" style="font-size:13px;" oninput="filterBizParent(this.value, \'' + prefix + '\')" autocomplete="off">' +
        '<input type="hidden" id="' + prefix + 'parent_id" value="' + (curPid != null && curPid !== '' ? curPid : '') + '">' +
        '<div id="' + prefix + 'parent_list" class="m-popup-card" style="max-height:240px;overflow-y:auto;border:1px solid var(--m-border);box-shadow:0 12px 40px rgba(0,0,0,0.15);background:var(--m-card);margin-top:6px;display:none;"></div></div>' +
        '<div style="font-size:12px;color:#888;margin-bottom:8px;" id="' + prefix + 'parent_box">' + curLabelHtml + '</div>';
}

// 主卡底部「子卡新增」按钮组（副卡/宽带/固话）通用模板：新增与编辑共用。
function bizSubButtonsHtml() {
    return '<div style="display:flex;gap:6px;margin-top:8px;">' +
        '<button class="btn btn-outline" style="flex:1;padding:8px;font-size:12px;justify-content:center;" onclick="addBizSubEntry(\'副卡\')"><i class="m-icon" data-icon="add"></i> 副卡</button>' +
        '<button class="btn btn-outline" style="flex:1;padding:8px;font-size:12px;justify-content:center;" onclick="addBizSubEntry(\'宽带\')"><i class="m-icon" data-icon="add"></i> 宽带</button>' +
        '<button class="btn btn-outline" style="flex:1;padding:8px;font-size:12px;justify-content:center;" onclick="addBizSubEntry(\'固话\')"><i class="m-icon" data-icon="add"></i> 固话</button>' +
        '</div>';
}

// ===== 主卡内联子卡（数智惠企/冰激凌 → 副卡/宽带/固话）=====
function renderBizSubEntries() {
    var wrap = document.getElementById('mBizSubEntries');
    if (!wrap) return;
    // 重渲染前先回写当前输入框已填值，避免「新增第二张子卡时第一张号码消失」
    (window._bizSubEntries || []).forEach(function(s) {
        if (!s.values) s.values = {};
        (BIZ_SUB_INLINE_FIELDS[s.childType] || ['number']).forEach(function(key) {
            var el = document.getElementById('sub_' + s.idx + '_' + key);
            if (el) s.values[key] = el.value;
        });
    });
    var subs = window._bizSubEntries || [];
    if (!subs.length) { wrap.innerHTML = '<div style="font-size:12px;color:#999;padding:4px 0;">尚未添加子卡</div>'; return; }
    var html = '';
    subs.forEach(function(s) {
        var childFields = BIZ_SUB_INLINE_FIELDS[s.childType] || ['number'];
        html += '<div class="m-subcard" style="border:1px solid var(--m-border);border-radius:10px;padding:10px;margin-bottom:8px;background:var(--m-bg);">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">' +
            '<span style="font-size:13px;font-weight:600;">' + esc(s.childType) + '</span>' +
            '<button class="btn btn-outline" style="padding:4px 10px;font-size:12px;justify-content:center;" onclick="removeBizSubEntry(' + s.idx + ')">删除</button></div>';
        childFields.forEach(function(key) {
            var f = BIZ_FIELD_POOL[key];
            if (!f) return;
            var dv = (s.values && s.values[key] != null) ? s.values[key] : '';
            html += bizFormFieldHtml(f, 'sub_' + s.idx + '_', dv);
        });
        html += '</div>';
    });
    wrap.innerHTML = html;
    renderIcons(wrap);
}

function addBizSubEntry(childType) {
    if (!window._bizSubEntries) window._bizSubEntries = [];
    var max = BIZ_SUB_MAX[childType] || 99;
    var cnt = window._bizSubEntries.filter(function(s) { return s.childType === childType; }).length;
    if (cnt >= max) { showToast(childType + '最多添加 ' + max + ' 张', 'error'); return; }
    if (window._bizSubSeq == null) window._bizSubSeq = 0;
    window._bizSubSeq++;
    window._bizSubEntries.push({ idx: window._bizSubSeq, childType: childType, values: {} });
    renderBizSubEntries();
}

function removeBizSubEntry(idx) {
    window._bizSubEntries = (window._bizSubEntries || []).filter(function(s) { return s.idx !== idx; });
    renderBizSubEntries();
}

// 收集内联子卡字段：子卡（副卡/宽带/固话）录入字段集 BIZ_SUB_INLINE_FIELDS 与「编辑该子卡」对齐，
// 全部由输入框直接读取（不再从主卡继承办理日期/使用人/备注/客户）。公司名与客户取自主卡（落库归属）。
function collectBizSubCards(mainData) {
    var subs = [];
    (window._bizSubEntries || []).forEach(function(s) {
        var childFields = BIZ_SUB_INLINE_FIELDS[s.childType] || ['number'];
        var d = {
            business_type: s.childType,
            company_name: mainData.company_name,
            customer_id: mainData.customer_id
        };
        childFields.forEach(function(key) {
            var f = BIZ_FIELD_POOL[key];
            var el = document.getElementById('sub_' + s.idx + '_' + key);
            var val = el ? el.value.trim() : '';
            d[key] = (f && f.type === 'number') ? (val ? parseFloat(val) : null) : val;
        });
        subs.push(d);
    });
    return subs;
}

// 独立录入子卡（副卡/宽带/固话）选择关联主卡：子卡归属与所选主卡同客户，自动关联；
// 各字段（办理日期/使用人/业务地址/备注）由输入框直接录入，不再从主卡继承。
function onBizChildParentChange() {
    var pid = (document.getElementById('mf_parent_id') ? document.getElementById('mf_parent_id').value : '').trim();
    if (!pid) return;
    var main = (allBusinessesMobile || []).find(function(b) { return b.id === parseInt(pid); });
    if (!main) return;
    // 子卡归属与所选主卡同客户，自动关联
    if (main.customer_id) {
        window._bizEntryCustomer = { id: main.customer_id, name: main.company_name || '' };
    }
    showToast('已关联主卡：' + (main.number || '-'), 'success');
}

// 独立录入子卡（副卡/宽带/固话）「关联主卡」：可搜索关联菜单（复用搜索客户列表样式 m-cust-option）。
// 支持按号码/公司/使用人名字搜索定位主卡；始终保留「不关联（独立副卡）」选项。
// prefix: 'mf_'（新增流程）/ 'mbiz_'（编辑流程）——区分两套 DOM id。
function filterBizParent(kw, prefix) {
    var k = (kw || '').trim().toLowerCase();
    var list = document.getElementById(prefix + 'parent_list');
    if (!list) return;
    if (!allBusinessesMobile || allBusinessesMobile.length === 0) {
        api('/api/business').then(function(bs) { allBusinessesMobile = bs; filterBizParent(k, prefix); });
        return;
    }
    var mains = allBusinessesMobile.filter(function(b) { return BIZ_MAIN_TYPES.indexOf(b.business_type) !== -1; });
    var filtered = mains.filter(function(m) {
        if (!k) return true;
        var hay = ((m.number || '') + ' ' + (m.company_name || '') + ' ' + (m.user_name || '')).toLowerCase();
        return hay.indexOf(k) !== -1;
    });
    list.innerHTML = bizParentRowsHtml(filtered, prefix);
    list.style.display = 'block';
}

function bizParentRowsHtml(mains, prefix) {
    var parts = [];
    parts.push('<div class="m-cust-option" data-pid="" style="padding:10px 12px;cursor:pointer;font-size:14px;color:var(--m-accent,#007AFF);" onclick="selectBizParent(\'\',\'' + prefix + '\')">不关联（独立副卡）</div>');
    mains.forEach(function(m) {
        var label = (m.number || '-') + (m.company_name ? '（' + m.company_name + '）' : '');
        var usr = m.user_name ? '<span style="float:right;color:#888;font-size:12px;">' + esc(m.user_name) + '</span>' : '';
        parts.push('<div class="m-cust-option" data-pid="' + m.id + '" style="padding:10px 12px;cursor:pointer;border-top:1px solid var(--m-border);font-size:14px;"' +
            ' onmouseover="this.style.background=\'#f0f4ff\'" onmouseout="this.style.background=\'\'"' +
            ' onclick="selectBizParent(' + m.id + ',\'' + prefix + '\')">' +
            '<strong>' + esc(label) + '</strong>' + usr + '</div>');
    });
    return parts.join('');
}

function selectBizParent(id, prefix) {
    var hid = document.getElementById(prefix + 'parent_id');
    if (hid) hid.value = id;
    var list = document.getElementById(prefix + 'parent_list');
    if (list) list.style.display = 'none';
    var s = document.getElementById(prefix + 'parent_search');
    var box = document.getElementById(prefix + 'parent_box');
    var main = id ? (allBusinessesMobile || []).find(function(b) { return b.id === parseInt(id); }) : null;
    var label = main ? ((main.number || '-') + (main.company_name ? '（' + main.company_name + '）' : '')) : '不关联（独立副卡）';
    if (s) s.value = id ? label : '';
    if (box) box.innerHTML = id ? ('<i class="m-icon" data-icon="done"></i> 已关联: <strong>' + esc(label) + '</strong>') : '不关联（独立副卡）';
    if (prefix === 'mf_') onBizChildParentChange();  // 仅新增流程需继承主卡字段并联动关联客户
    renderIcons(document.body);
}

async function renderBizForm(type) {
    var fields = BIZ_TYPE_FIELDS[type];
    if (!fields) { showToast('未知业务类型', 'error'); return; }
    var box = document.getElementById('mBizEntryForm');
    if (!box) return;
    if (!_bizEntryCustomer || !_bizEntryCustomer.id) {
        showToast('请先选择关联客户', 'error');
        var sel = document.getElementById('mBizEntrySubtype');
        if (sel) sel.value = '';
        var _bt = document.getElementById('mBizEntryTypeLabel'); if (_bt) _bt.textContent = '请选择业务类型';
        return;
    }
    window._bizEntrySubtype = type;
    window._bizSubEntries = [];
    window._bizSubSeq = null;
    document.getElementById('pageTitle').textContent = '新增' + type;
    // 确保主卡数据已加载（关联主卡下拉需要），避免下拉为空
    if (!allBusinessesMobile || allBusinessesMobile.length === 0) {
        try { allBusinessesMobile = await api('/api/business'); } catch(e) { allBusinessesMobile = []; }
    }
    var html = '<div class="m-card">';
    html += '<div class="form-group"><label>业务类型</label><div style="font-size:14px;">' + esc(type) + '</div></div>';
    if (BIZ_CHILD_TYPES.indexOf(type) !== -1) {
        // 独立录入子卡（副卡/宽带/固话）：关联主卡复用全局可搜索关联菜单模板（bizParentFieldHtml），
        // 支持按号码/公司/使用人搜索定位主卡；留空即为「不关联（独立副卡）」。隐藏 input 存值，onBizChildParentChange 仍按此读取。
        html += bizParentFieldHtml('mf_', '', esc('不关联（独立副卡）'));
        (BIZ_SUB_INLINE_FIELDS[type] || ['number']).forEach(function(key) {
            var f = BIZ_FIELD_POOL[key];
            if (!f) return;
            html += bizFormFieldHtml(f, 'mf_', '');
        });
    } else {
        fields.forEach(function(key) {
            var f = BIZ_FIELD_POOL[key];
            if (!f) return;
            var dv = (key === 'company_name' && _bizEntryCustomer) ? _bizEntryCustomer.name : '';
            html += bizFormFieldHtml(f, 'mf_', dv);
        });
    }
    html += '</div>';
    // 主卡（数智惠企/冰激凌）支持内联挂子卡（副卡/宽带/固话，自动关联本主卡）
    if (BIZ_MAIN_TYPES.indexOf(type) !== -1) {
        html += '<div id="mBizSubWrap" style="margin-top:12px;">' +
            '<div style="font-size:13px;color:var(--m-text-secondary);margin-bottom:6px;">子卡（副卡 / 宽带 / 固话，将自动关联本主卡）</div>' +
            '<div id="mBizSubEntries"></div>' +
            bizSubButtonsHtml() +
            '</div>';
    }
    html += '<div style="display:flex;gap:8px;margin-top:12px;">' +
        '<button class="btn btn-outline" style="flex:1;padding:12px;justify-content:center;" onclick="navBack()">取消</button>' +
        '<button class="btn btn-primary" style="flex:1;padding:12px;justify-content:center;" onclick="saveBizEntry(\'' + type + '\')"><i class="m-icon" data-icon="save"></i> 保存</button>' +
        '</div>';
    box.innerHTML = html;
    if (BIZ_MAIN_TYPES.indexOf(type) !== -1) renderBizSubEntries();
    setTimeout(function() { window.scrollTo(0, document.getElementById('mBizEntryForm').offsetTop - 20); }, 0);
    renderIcons(box);
}

// 保存：按业务类型落到单表 businesses（关联客户名映射到 company_name 字段）。
// 通用保存（2.6.1：按 BIZ_TYPE_FIELDS[type] 收集字段，POST 到 /api/business）。
async function saveBizEntry(type) {
    if (window._pendingCustomerCreate) {
        try { await window._pendingCustomerCreate; } catch (e) { showToast('客户新建失败', 'error'); return; }
    }
    if (!_bizEntryCustomer || !_bizEntryCustomer.id) { showToast('请先选择关联客户', 'error'); return; }
    var fields = BIZ_TYPE_FIELDS[type];
    if (!fields) { showToast('未知业务类型', 'error'); return; }
    var custId = _bizEntryCustomer.id;
    var custName = _bizEntryCustomer.name;
    // 独立录入子卡（副卡/宽带/固话）：仅收集极简字段 + 关联主卡，其余（办理日期/使用人/备注/客户）从所选主卡继承。
    // 子卡无「业务层级」字段，不发送 business_level。
    var isChild = BIZ_CHILD_TYPES.indexOf(type) !== -1;
    var effCustId = custId;
    var effCustName = custName;
    var data;
    if (isChild) {
        // 关联主卡改为可选：未选则 parent_id 为 null（独立副卡），归属落到已选关联客户。
        // 其余字段（办理日期/使用人/业务地址/备注）由输入框直接录入，与「编辑该子卡」一致。
        var pidRaw = (document.getElementById('mf_parent_id') ? document.getElementById('mf_parent_id').value : '').trim();
        data = {
            business_type: type,
            company_name: effCustName,
            customer_id: parseInt(effCustId),
            parent_id: pidRaw ? parseInt(pidRaw) : null
        };
        (BIZ_SUB_INLINE_FIELDS[type] || ['number']).forEach(function(key) {
            var f = BIZ_FIELD_POOL[key];
            var el = document.getElementById('mf_' + key);
            var val = el ? el.value.trim() : '';
            data[key] = (f && f.type === 'number') ? (val ? parseFloat(val) : null) : val;
        });
    } else {
        data = { business_type: type, company_name: custName, customer_id: parseInt(custId) };
        fields.forEach(function(key) {
            var f = BIZ_FIELD_POOL[key];
            if (!f) return;
            if (key === 'parent_id') {
                var pid2 = (document.getElementById('mf_parent_id') ? document.getElementById('mf_parent_id').value : '').trim();
                data.parent_id = pid2 ? parseInt(pid2) : null;
            } else {
                var el = document.getElementById('mf_' + key);
                var val = el ? el.value.trim() : '';
                data[key] = (f.type === 'number') ? (val ? parseFloat(val) : null) : val;
            }
        });
    }
    // 主卡内联子卡（数智惠企/冰激凌 → 副卡/宽带/固话）：收集待建子卡，保存主卡后顺带建
    var isMain = BIZ_MAIN_TYPES.indexOf(type) !== -1;
    var subCards = isMain ? collectBizSubCards(data) : [];
    var tmpId = 'tmp_biz_' + Date.now() + '_' + Math.floor(Math.random() * 1e4);
    optimisticWrite({
        applyLocal: function() {
            window._pendingCreates.push({ tmpId: tmpId, src: 'business', customer_id: parseInt(effCustId),
                company_name: effCustName, sub_type: type,
                contract_amount: data.contract_amount, contract_code: data.contract_code || '',
                business_number: data.number, _pending: true });
            // 子卡乐观占位（parent_id 待主卡落库后回填）
            var subTmpIds = [];
            subCards.forEach(function(sc, i) {
                var stid = tmpId + '_sub_' + i;
                subTmpIds.push(stid);
                window._pendingCreates.push({ tmpId: stid, src: 'business', customer_id: parseInt(effCustId),
                    company_name: effCustName, sub_type: sc.business_type,
                    contract_amount: null, contract_code: '',
                    business_number: sc.number || '', _pending: true });
            });
            window._bizSubTmpIds = subTmpIds;
            navBack(); // 立即返回列表（秒回），临时记录已在返回页渲染
        },
        submit: async function() {
            var created = await api('/api/business', { method: 'POST', body: JSON.stringify(data) });
            var mainId = created && created.id;
            for (var i = 0; i < subCards.length; i++) {
                subCards[i].parent_id = mainId;
                await api('/api/business', { method: 'POST', body: JSON.stringify(subCards[i]) });
            }
        },
        onSuccess: function() {
            removePending(tmpId);
            (window._bizSubTmpIds || []).forEach(function(stid) { removePending(stid); });
            allBusinessesMobile = null; window._businessNeedRefresh = true;
            showToast('已新增' + (subCards.length ? '（含 ' + subCards.length + ' 张子卡）' : ''), 'success');
            refreshReturnPagesForCustomer(effCustId);
        },
        rollback: function(err) {
            removePending(tmpId);
            (window._bizSubTmpIds || []).forEach(function(stid) { removePending(stid); });
            showToast('新增失败: ' + (err && err.message ? err.message : err), 'error');
            refreshReturnPagesForCustomer(effCustId);
        }
    });
}

// ==================== （2.6.1 起已弃用）原 ledgers 表逻辑：业务已合并进单表 businesses，以下函数不再被调用，仅保留以免误删 ====================

var _ledgerData = [];
var _ledgerLoaded = false;

async function loadLedgerMobile() {
    if (_ledgerLoaded) {
        renderLedgerTable();
        return;
    }
    _ledgerLoaded = true;
    var container = document.getElementById('mLedgerResultContainer');
    if (!container) return;
    container.innerHTML = '<div style="text-align:center;color:#999;font-size:13px;padding:20px;"><i class="m-icon" data-icon="loading"></i> 加载中...</div>';
    try {
        _ledgerData = await api('/api/ledgers');
        // 按日期降序排序（最近在上面）
        _ledgerData.sort(function(a, b) {
            var da = a.date || '';
            var db = b.date || '';
            return db.localeCompare(da);
        });
        renderLedgerTable();
    } catch(e) {
        container.innerHTML = '<div class="m-empty" style="padding:20px;"><div class="icon"><i class="m-icon" data-icon="error"></i></div><div class="title">加载失败: ' + e.message + '</div></div>';
    }
}

var LEDGER_PKG_OPTIONS = ['数智惠企', '冰激凌', '魔方卡', '副卡', '融合', '固话'];
var M_LEDGER_MAIN = ['数智惠企', '冰激凌'];   // 主卡类型
var M_LEDGER_CHILD = ['副卡', '融合', '固话'];  // 子卡类型，需关联主卡

function ledgerPkgOptionsHtml(currentVal) {
    var parts = ['<option value="">请选择套餐类型</option>'];
    LEDGER_PKG_OPTIONS.forEach(function(o) {
        parts.push('<option value="' + o + '"' + (o === currentVal ? ' selected' : '') + '>' + o + '</option>');
    });
    if (currentVal && LEDGER_PKG_OPTIONS.indexOf(currentVal) === -1) {
        parts.push('<option value="' + esc(currentVal) + '" selected>' + esc(currentVal) + '（原有）</option>');
    }
    return parts.join('');
}

// 根据套餐类型切换移动端新增/编辑界面：主卡显示副卡/融合/固话按钮；子卡显示关联主卡；魔方卡等隐藏
function syncLedgerMobileTypeUI() {
    var type = (document.getElementById('mLedgerPackageType').value || '').trim();
    var isMain = M_LEDGER_MAIN.indexOf(type) !== -1;
    var isChild = M_LEDGER_CHILD.indexOf(type) !== -1;
    var subWrap = document.getElementById('mLedgerSubWrap');
    if (subWrap) subWrap.style.display = isMain ? '' : 'none';
    var pw = document.getElementById('mLedgerParentWrap');
    if (!pw) return;
    if (isChild) { pw.style.display = ''; populateLedgerMobileParent(); }
    else { pw.style.display = 'none'; }
}

function populateLedgerMobileParent() {
    var sel = document.getElementById('mLedgerParent');
    if (!sel) return;
    var mains = (_ledgerData || []).filter(function(l) { return M_LEDGER_MAIN.indexOf(l.package_type) !== -1; });
    var editingId = (window._editingLedgerId != null) ? String(window._editingLedgerId) : '';
    var parts = ['<option value="">请选择主卡（数智惠企 / 冰激凌）</option>'];
    mains.forEach(function(m) {
        if (String(m.id) === editingId) return;
        var label = (m.number || '-') + (m.company ? '（' + m.company + '）' : '');
        parts.push('<option value="' + esc(m.number || '') + '">' + esc(label) + '</option>');
    });
    sel.innerHTML = parts.join('');
}

function renderLedgerTable(data) {
    var container = document.getElementById('mLedgerResultContainer');
    if (!container) return;
    var items = (data && data.length) ? data : (_ledgerData || []);
    if (!items.length) {
        container.innerHTML = '<div class="m-empty" style="padding:20px;"><div class="icon"><i class="m-icon" data-icon="empty"></i></div><div class="title">暂无业务数据</div></div>';
        return;
    }
    var MAIN = M_LEDGER_MAIN;
    var mains = items.filter(function(r) { return MAIN.indexOf(r.package_type) !== -1; });
    var children = items.filter(function(r) { return r.parent_number; });
    var orphans = items.filter(function(r) { return MAIN.indexOf(r.package_type) === -1 && !r.parent_number; });
    var childMap = {};
    children.forEach(function(c) {
        var k = (c.parent_number || '').trim();
        (childMap[k] = childMap[k] || []).push(c);
    });
    function row1(r) { return [r.number || '-', r.package_name || '-', r.package_type || '-'].map(esc).join(' · '); }
    function row2(r) { var d = r.date ? r.date.replace(/-/g, '').substring(2, 8) : '-'; return [d, r.company || '-', r.user_name || '-'].map(esc).join(' · '); }
    var parts = ['<div class="m-group-list m-group-list--ledger">'];
    mains.forEach(function(m) {
        parts.push('<div class="m-group-item m-ledger-group" data-id="' + m.id + '" onclick="viewLedgerMobile(' + m.id + ')">' +
            '<div class="m-group-info"><div class="m-group-title">' + row1(m) + '</div><div class="m-group-subtitle">' + row2(m) + '</div></div>' +
            '<div class="m-group-chevron"><i class="m-icon" data-icon="chevronRight"></i></div></div>');
        (childMap[(m.number || '').trim()] || []).forEach(function(c) {
            parts.push('<div class="m-group-item m-ledger-child" data-id="' + c.id + '" onclick="viewLedgerMobile(' + c.id + ')">' +
                '<div class="m-group-info"><div class="m-group-title">↳ ' + esc(c.number || '-') + ' · ' + esc(c.package_type || '-') + '</div><div class="m-group-subtitle">' + row2(c) + '</div></div>' +
                '<div class="m-group-chevron"><i class="m-icon" data-icon="chevronRight"></i></div></div>');
        });
    });
    orphans.forEach(function(o) {
        parts.push('<div class="m-group-item" data-id="' + o.id + '" onclick="viewLedgerMobile(' + o.id + ')">' +
            '<div class="m-group-info"><div class="m-group-title">' + row1(o) + '</div><div class="m-group-subtitle">' + row2(o) + '</div></div>' +
            '<div class="m-group-chevron"><i class="m-icon" data-icon="chevronRight"></i></div></div>');
    });
    parts.push('</div><div style="font-size:11px;color:var(--m-text-secondary);padding:6px 3px;text-align:right;">共 ' + items.length + ' 条</div>');
    container.innerHTML = parts.join('');
    renderIcons(container); // 嵌套重绘后补图标，否则右侧箭头不显示
    // 一级页面长按删除——业务列表
    container.querySelectorAll('.m-group-item[data-id]').forEach(function(el) {
        var id = parseInt(el.getAttribute('data-id'), 10);
        var r = items.find(function(x) { return x.id === id; });
        if (!r) return;
        bindLongPress(el, function() {
            mConfirm('删除业务', '确定删除「' + (r.company || '该业务') + '」？此操作不可撤销。', function() {
                deleteLedgerMobile(id, r.company || '');
            });
        });
    });
}

function searchLedgerMobile(query) {
    var q = query.trim().toLowerCase();
    if (!q) {
        renderLedgerTable();
        return;
    }
    var filtered = _ledgerData.filter(function(r) {
        var dateStr = r.date ? r.date.replace(/-/g, '').substring(2, 8) : '';
        return (r.number && r.number.toLowerCase().indexOf(q) !== -1) ||
               (r.company && r.company.toLowerCase().indexOf(q) !== -1) ||
               (r.user_name && r.user_name.toLowerCase().indexOf(q) !== -1) ||
               (dateStr && dateStr.indexOf(q) !== -1);
    });
    renderLedgerTable(filtered);
}

function addLedgerMobile() {
    enterSubPage();
    navPush('addledger', function() { switchPage('business'); });
    _subEntryCount = 0;
    window._editingLedgerId = null;
    var content = document.getElementById('pageContent');
    document.getElementById('pageTitle').textContent = '新增业务';
    content.innerHTML =
        '<div class="m-card">' +
            '<div class="form-group"><label>日期</label><input type="date" class="form-control" id="mLedgerDate"></div>' +
            '<div class="form-group"><label>号码</label><input type="text" class="form-control" id="mLedgerNumber" placeholder="输入号码"></div>' +
            '<div class="form-group"><label>公司</label><input type="text" class="form-control" id="mLedgerCompany" placeholder="输入公司名称"></div>' +
            '<div class="form-group"><label>使用人</label><input type="text" class="form-control" id="mLedgerUser" placeholder="输入使用人"></div>' +
            '<div class="form-group"><label>套餐类型</label><select class="form-control" id="mLedgerPackageType" onchange="syncLedgerMobileTypeUI()">' + ledgerPkgOptionsHtml('') + '</select></div>' +
            '<div class="form-group" id="mLedgerParentWrap" style="display:none;"><label>关联主卡</label><select class="form-control" id="mLedgerParent"></select></div>' +
            '<div class="form-group"><label>层级</label><input type="text" class="form-control" id="mLedgerPackage" placeholder="输入套餐层级"></div>' +
            '<div id="mLedgerSubWrap">' +
                '<div id="mLedgerSubEntries" style="margin-top:4px;"></div>' +
                '<div style="display:flex;gap:6px;margin-top:8px;">' +
                    '<button class="btn btn-outline" style="flex:1;padding:8px;font-size:12px;justify-content:center;" onclick="addSubEntry(\'副卡\',\'10\')"><i class="m-icon" data-icon="add"></i> 新增副卡</button>' +
                    '<button class="btn btn-outline" style="flex:1;padding:8px;font-size:12px;justify-content:center;" onclick="addSubEntry(\'融合\',\'0\')"><i class="m-icon" data-icon="add"></i> 新增融合</button>' +
                    '<button class="btn btn-outline" style="flex:1;padding:8px;font-size:12px;justify-content:center;" onclick="addSubEntry(\'固话\',\'0\')"><i class="m-icon" data-icon="add"></i> 新增固话</button>' +
                '</div>' +
            '</div>' +
            '<div style="display:flex;gap:8px;margin-top:12px;">' +
                '<button class="btn btn-outline" style="flex:1;padding:12px;justify-content:center;" onclick="navBack()">取消</button>' +
                '<button class="btn btn-primary" style="flex:1;padding:12px;justify-content:center;" onclick="saveLedgerMobile()"><i class="m-icon" data-icon="save"></i> 保存</button>' +
            '</div>' +
        '</div>';
}

var _subEntryCount = 0;

function addSubEntry(type, defaultPkg) {
    // 限制数量：副卡最多4条，融合最多2条
    var maxCount = (type === '副卡') ? 4 : 2;
    var existing = document.querySelectorAll('#mLedgerSubEntries > div');
    var count = Array.from(existing).filter(function(el) {
        var label = el.querySelector('span');
        return label && label.textContent.trim() === type;
    }).length;
    if (count >= maxCount) {
        showToast(type + '已达上限（最多' + maxCount + '条）', 'error');
        return;
    }
    _subEntryCount++;
    var idx = _subEntryCount;
    var container = document.getElementById('mLedgerSubEntries');
    if (!container) return;
    var div = document.createElement('div');
    div.id = 'subEntryRow' + idx;
    div.style.cssText = 'display:flex;gap:6px;align-items:center;margin-top:6px;padding:6px 8px;background:var(--m-card);border-radius:var(--m-radius-md);';
    div.innerHTML =
        '<span style="font-size:11px;color:var(--m-text-secondary);white-space:nowrap;min-width:32px;">' + type + '</span>' +
        '<input type="text" placeholder="号码" id="subNum' + idx + '" style="flex:1;font-size:12px;padding:6px 10px;border:1px solid var(--m-border);border-radius:var(--m-radius-pill);background:var(--m-card);color:var(--m-text);min-width:0;">' +
        '<input type="text" placeholder="层级" id="subPkg' + idx + '" value="' + defaultPkg + '" style="width:64px;font-size:12px;padding:6px 10px;border:1px solid var(--m-border);border-radius:var(--m-radius-pill);background:var(--m-card);color:var(--m-text);">' +
        '<input type="text" placeholder="套餐类型" id="subType' + idx + '" value="' + type + '" style="width:72px;font-size:12px;padding:6px 10px;border:1px solid var(--m-border);border-radius:var(--m-radius-pill);background:var(--m-card);color:var(--m-text);">' +
        '<button onclick="removeSubEntry(' + idx + ')" style="border:none;background:none;color:var(--m-danger);font-size:18px;cursor:pointer;padding:0 4px;">×</button>';
    container.appendChild(div);
}

function removeSubEntry(idx) {
    var row = document.getElementById('subEntryRow' + idx);
    if (row) row.remove();
}

async function saveLedgerMobile() {
    var date = document.getElementById('mLedgerDate').value;
    var number = document.getElementById('mLedgerNumber').value.trim();
    var company = document.getElementById('mLedgerCompany').value.trim();
    var userName = document.getElementById('mLedgerUser').value.trim();
    var pkg = document.getElementById('mLedgerPackage').value.trim();
    var pkgType = document.getElementById('mLedgerPackageType').value.trim();

    if (!company && !number) {
        showToast('请输入公司或号码', 'error');
        return;
    }

    var isMain = M_LEDGER_MAIN.indexOf(pkgType) !== -1;
    var isChild = M_LEDGER_CHILD.indexOf(pkgType) !== -1;
    // 关联主卡改为可选：未选则 parent_number 留空（独立副卡）
    var parentVal = isChild ? (document.getElementById('mLedgerParent').value || '').trim() : '';

    // 收集所有子条目（副卡/融合/固话），子条目通过 parent_number 关联主卡号码
    var entries = [{ number: number, package_name: pkg, package_type: pkgType, parent_number: isChild ? parentVal : '' }];
    if (isMain) {
        if (_subEntryCount > 0 && !number) {
            showToast('请填写主卡号码以便关联副卡/融合/固话', 'error');
            return;
        }
        for (var i = 1; i <= _subEntryCount; i++) {
            var subNum = document.getElementById('subNum' + i);
            var subPkg = document.getElementById('subPkg' + i);
            var subType = document.getElementById('subType' + i);
            if (!subNum || !subPkg) continue;
            var sn = subNum.value.trim();
            var sp = subPkg.value.trim();
            var st = subType ? subType.value.trim() : '';
            if (!sn && !sp && !st) continue;
            entries.push({ number: sn, package_name: sp || (document.getElementById('subPkg' + i).defaultValue || ''), package_type: st || (subType ? subType.defaultValue : ''), parent_number: number });
        }
    }

    try {
        for (var j = 0; j < entries.length; j++) {
            await api('/api/ledgers', {
                method: 'POST',
                body: {
                    date: date,
                    number: entries[j].number,
                    company: company,
                    user_name: userName,
                    package_name: entries[j].package_name,
                    package_type: entries[j].package_type,
                    parent_number: entries[j].parent_number || ''
                }
            });
        }
        showToast('新增成功，共 ' + entries.length + ' 条', 'success');
        _ledgerLoaded = false;
        _ledgerData = [];
        window._businessNeedRefresh = true; // 标记业务页需刷新，返回后显示最新
        navBack();
    } catch(e) {
        showToast('新增失败: ' + e.message, 'error');
    }
}

function viewLedgerMobile(id, skipPush) {
    var r = _ledgerData.find(function(x) { return x.id === id; });
    if (!r) { showToast('未找到该记录', 'error'); return; }
    enterSubPage();
    // 与 viewBusinessMobile 一致：仅当来源是业务页时才压栈返回业务页；
    // 来自客户详情的，由调用方（ledger 条目 onclick）压栈返回客户详情，避免回头落到业务页
    if (currentPage === 'business') {
        if (!skipPush) navPush('ledger:' + id, function() { switchPage('business'); });
    }
    var content = document.getElementById('pageContent');
    document.getElementById('pageTitle').textContent = '业务详情';
    content.innerHTML =
        '<div class="m-card" id="mLedgerInfoCard" style="cursor:pointer;" onclick="editLedgerMobile(' + id + ')">' +
            '<div class="form-group"><label>日期</label><div style="font-size:14px;">' + (r.date ? r.date.replace(/-/g, '').substring(2, 8) : '-') + '</div></div>' +
            '<div class="form-group"><label>号码</label><div style="font-size:14px;">' + (r.number || '-') + '</div></div>' +
            '<div class="form-group"><label>公司</label><div style="font-size:14px;">' + (r.company || '-') + '</div></div>' +
            (r.customer_id ? '<div class="form-group"><label>关联客户</label><div style="font-size:14px;color:#007AFF;cursor:pointer;" onclick="navPush(\'ledgercust:' + r.customer_id + '\',function(){viewLedgerMobile(' + id + ')});viewCustomerMobile(' + r.customer_id + ')"><i class="m-icon" data-icon="user"></i> 查看客户详情</div></div>' : '') +
            '<div class="form-group"><label>使用人</label><div style="font-size:14px;">' + (r.user_name || '-') + '</div></div>' +
            '<div class="form-group"><label>套餐类型</label><div style="font-size:14px;">' + (r.package_type || '-') + '</div></div>' +
            (r.parent_number ? '<div class="form-group"><label>关联主卡</label><div style="font-size:14px;">' + esc(r.parent_number) + '</div></div>' : '') +
            '<div class="form-group"><label>层级</label><div style="font-size:14px;">' + (r.package_name || '-') + '</div></div>' +
        '</div>';
}

function editLedgerMobile(id) {
    var r = _ledgerData.find(function(x) { return x.id === id; });
    if (!r) { showToast('未找到该记录', 'error'); return; }
    // 进入编辑页：底部「取消 / 保存」操作栏（不再用顶栏 X/✓）
    enterEditPage(function() { saveEditLedgerMobile(id); });
    navPush('editledger:' + id, function() { viewLedgerMobile(id); });
    window._editingLedgerId = id;
    var content = document.getElementById('pageContent');
    document.getElementById('pageTitle').textContent = '编辑业务';
    var isChild = M_LEDGER_CHILD.indexOf(r.package_type) !== -1;
    content.innerHTML =
        '<div class="m-card">' +
            '<div class="form-group"><label>日期</label><input type="date" class="form-control" id="mEditLedgerDate" value="' + (r.date || '') + '"></div>' +
            '<div class="form-group"><label>号码</label><input type="text" class="form-control" id="mEditLedgerNumber" value="' + (r.number || '').replace(/"/g,'&quot;') + '"></div>' +
            '<div class="form-group"><label>公司</label><input type="text" class="form-control" id="mEditLedgerCompany" value="' + (r.company || '').replace(/"/g,'&quot;') + '"></div>' +
            '<div class="form-group"><label>使用人</label><input type="text" class="form-control" id="mEditLedgerUser" value="' + (r.user_name || '').replace(/"/g,'&quot;') + '"></div>' +
            '<div class="form-group"><label>套餐类型</label><select class="form-control" id="mEditLedgerPackageType" onchange="syncEditLedgerTypeUI()">' + ledgerPkgOptionsHtml(r.package_type) + '</select></div>' +
            '<div class="form-group" id="mEditLedgerParentWrap" style="display:' + (isChild ? '' : 'none') + ';"><label>关联主卡</label><select class="form-control" id="mEditLedgerParent"></select></div>' +
            '<div class="form-group"><label>层级</label><input type="text" class="form-control" id="mEditLedgerPackage" value="' + (r.package_name || '').replace(/"/g,'&quot;') + '"></div>' +
            editActionBarHtml() +
        '</div>';
    if (isChild) {
        populateEditLedgerParent();
        document.getElementById('mEditLedgerParent').value = r.parent_number || '';
    }
}

// 编辑页套餐类型切换：子卡显示关联主卡下拉
function syncEditLedgerTypeUI() {
    var type = (document.getElementById('mEditLedgerPackageType').value || '').trim();
    var isChild = M_LEDGER_CHILD.indexOf(type) !== -1;
    var pw = document.getElementById('mEditLedgerParentWrap');
    if (!pw) return;
    if (isChild) { pw.style.display = ''; populateEditLedgerParent(); }
    else { pw.style.display = 'none'; }
}

function populateEditLedgerParent() {
    var sel = document.getElementById('mEditLedgerParent');
    if (!sel) return;
    var mains = (_ledgerData || []).filter(function(l) { return M_LEDGER_MAIN.indexOf(l.package_type) !== -1; });
    var editingId = (window._editingLedgerId != null) ? String(window._editingLedgerId) : '';
    var parts = ['<option value="">请选择主卡（数智惠企 / 冰激凌）</option>'];
    mains.forEach(function(m) {
        if (String(m.id) === editingId) return;
        var label = (m.number || '-') + (m.company ? '（' + m.company + '）' : '');
        parts.push('<option value="' + esc(m.number || '') + '">' + esc(label) + '</option>');
    });
    sel.innerHTML = parts.join('');
}

async function saveEditLedgerMobile(id) {
    var pkgType = document.getElementById('mEditLedgerPackageType').value.trim();
    var isChild = M_LEDGER_CHILD.indexOf(pkgType) !== -1;
    var parentVal = isChild ? (document.getElementById('mEditLedgerParent').value || '').trim() : '';
    var data = {
        date: document.getElementById('mEditLedgerDate').value,
        number: document.getElementById('mEditLedgerNumber').value.trim(),
        company: document.getElementById('mEditLedgerCompany').value.trim(),
        user_name: document.getElementById('mEditLedgerUser').value.trim(),
        package_name: document.getElementById('mEditLedgerPackage').value.trim(),
        package_type: pkgType,
        parent_number: parentVal
    };
    if (!data.company && !data.number) {
        showToast('请输入公司或号码', 'error');
        return;
    }
    // 关联主卡改为可选：未选则 parent_number 留空（独立副卡），不再强制
    // 编辑：本地先更新缓存 → 立即返回详情（乐观），后台 PUT，失败回滚
    var old = _ledgerData.find(function(x) { return x.id === id; });
    var bak = old ? JSON.parse(JSON.stringify(old)) : null;
    optimisticWrite({
        applyLocal: function() {
            if (old) {
                old.date = data.date; old.number = data.number; old.company = data.company;
                old.user_name = data.user_name; old.package_name = data.package_name;
                old.package_type = data.package_type; old.parent_number = parentVal;
            }
            navBack(); // 返回业务详情（从缓存即时重绘）
        },
        submit: async function() { await api('/api/ledgers/' + id, { method: 'PUT', body: data }); },
        onSuccess: function() {
            _ledgerLoaded = false; window._businessNeedRefresh = true;
            showToast('保存成功', 'success');
        },
        rollback: function(err) {
            if (bak && old) {
                old.date = bak.date; old.number = bak.number; old.company = bak.company;
                old.user_name = bak.user_name; old.package_name = bak.package_name;
                old.package_type = bak.package_type; old.parent_number = bak.parent_number;
            }
            showToast('保存失败: ' + (err && err.message ? err.message : err), 'error');
            viewLedgerMobile(id, true); // 详情页即时重绘为旧值（不重复压栈）
        }
    });
}

async function deleteLedgerMobile(id, name) {
    var key = 'ledger:' + id;
    optimisticWrite({
        applyLocal: function() {
            addPendingDelete(key);
            rerenderVisibleAfterMutation(); // 立即从当前可见视图隐藏（列表或客户详情）
        },
        submit: async function() { await api('/api/ledgers/' + id, { method: 'DELETE' }); },
        onSuccess: function() {
            if (_ledgerData) _ledgerData = _ledgerData.filter(function(x) { return x.id !== id; });
            removePendingDelete(key);
            window._businessNeedRefresh = true;
            showToast('已删除', 'success');
        },
        rollback: function(err) {
            removePendingDelete(key);
            showToast('删除失败: ' + (err && err.message ? err.message : err), 'error');
            rerenderVisibleAfterMutation();
        }
    });
}

async function viewBusinessMobile(id, skipPush) {
    enterSubPage();
    // 根据来源页面决定返回路径：仅当当前停留在一级业务列表时才压栈，
    // 避免从详情/编辑等子页再次进入时重复压栈（导致返回行为异常）
    if (currentPage === 'business' && _isOnTopPage) {
        if (!skipPush) navPush('biz:' + id, function() { switchPage('business'); });
    }
    // 从客户详情进来的，由调用方（openBusinessFromDetail）负责 push
    // 确保主卡数据已加载（关联主卡反查、子卡归集用）
    if (!allBusinessesMobile || allBusinessesMobile.length === 0) {
        try { allBusinessesMobile = await api('/api/business'); } catch(e) { allBusinessesMobile = []; }
    }
    var biz = allBusinessesMobile ? allBusinessesMobile.find(function(b) { return b.id === id; }) : null;
    if (!biz) {
        try {
            biz = await api('/api/business/' + id);
        } catch(e) {
            showToast('业务不存在', 'error');
            return;
        }
    }
    window._viewingBizId = id; // 记当前查看的业务，供删除/新增子卡后即时重绘
    paintBizDetail(id);
}

// 渲染业务详情内容（主卡 + 全部子卡）。单独抽出以便删除/新增子卡后即时重绘，不重走 enterSubPage（避免滚动跳顶）。
function paintBizDetail(id) {
    if (!allBusinessesMobile) return;
    var biz = allBusinessesMobile.find(function(b) { return b.id === id; });
    if (!biz) return; // 已被删除（如根主卡删除）则交由调用方决定去向
    var content = document.getElementById('pageContent');
    if (!content) return;

    // 存在主副卡关系时：无论点主卡还是子卡，都归集到「根主卡」统一展示（主卡 + 全部子卡）
    var root = biz;
    if (biz.parent_id) {
        var p = (allBusinessesMobile || []).find(function(x) { return x.id === biz.parent_id; });
        if (p) root = p;
    }
    var rootId = root.id;
    var children = (allBusinessesMobile || []).filter(function(x) { return x.parent_id === rootId && !isPendingDelete('biz:' + x.id); });
    if (biz.parent_id && !children.some(function(x) { return x.id === biz.id; })) children.push(biz); // 兜底：极端情况下点击的子卡未归集

    document.getElementById('pageTitle').textContent = root.business_type || '业务';

    // 统一标签列宽：取详情页所有字段标签中最长「标题」的显示宽度，内容左对齐到同一位置
    function _cjkW(s){ var w = 0; for (var i = 0; i < s.length; i++){ w += (s.charCodeAt(i) > 0x2E80) ? 1 : 0.5; } return w; }
    var _lbls = ['关联客户', '业务类型'];
    (BIZ_TYPE_FIELDS[root.business_type] || []).forEach(function(k){ var f = BIZ_FIELD_POOL[k]; if (f && k !== 'parent_id') _lbls.push(f.label); });
    if (root.customer_id) _lbls.push('关联客户详情');
    children.forEach(function(ch){
        var cs = ['date', 'number', 'user_name', 'notes'];
        if (BIZ_SUB_INLINE_FIELDS[ch.business_type] && BIZ_SUB_INLINE_FIELDS[ch.business_type].indexOf('business_address') !== -1) cs.push('business_address');
        cs.forEach(function(k){ var f = BIZ_FIELD_POOL[k]; if (f) _lbls.push(f.label); });
    });
    var _maxW = _lbls.reduce(function(m, s){ return Math.max(m, _cjkW(s)); }, 0);
    var _labelW = (_maxW * 13 + 4) + 'px';

    // 主卡信息卡（点击编辑主卡）
    var html = '<div class="biz-detail" style="--biz-label-w:' + _labelW + ';">';
    html += '<div class="m-card" id="mBizInfoCard" style="cursor:pointer;" onclick="editBusinessMobile(' + root.id + ')">';
    html += '<div class="form-group biz-row"><label>关联客户</label><div style="font-size:14px;">' + esc(root.company_name || '-') + '</div></div>';
    html += '<div class="form-group biz-row"><label>业务类型</label><div style="font-size:14px;">' + esc(root.business_type || '-') + '</div></div>';
    (BIZ_TYPE_FIELDS[root.business_type] || []).forEach(function(key) {
        var f = BIZ_FIELD_POOL[key];
        if (!f || key === 'parent_id') return; // 主卡无上级，不展示关联主卡
        html += '<div class="form-group biz-row"><label>' + f.label + '</label><div style="font-size:14px;">' + esc(bizFieldDisplay(f, root[key])) + '</div></div>';
    });
    if (root.customer_id) {
        html += '<div class="form-group biz-row"><label>关联客户详情</label><div style="font-size:14px;color:#007AFF;cursor:pointer;" onclick="event.stopPropagation();navPush(\'bizcust:' + root.customer_id + '\',function(){viewBusinessMobile(' + root.id + ')});viewCustomerMobile(' + root.customer_id + ')"><i class="m-icon" data-icon="user"></i> 查看客户详情</div></div>';
    }

    // 子卡区：点击整卡进入编辑；仅展示 号码 / 使用人 / 备注（宽带/固话 额外显示 业务地址）
    if (children.length) {
        html += '<div class="m-card m-card-wide"><div class="m-card-title"><span>子卡（' + children.length + '）</span></div>';
        children.forEach(function(ch) {
            var isCurrent = (ch.id === biz.id);
            var childShow = ['date', 'number', 'user_name', 'notes'];
            if (BIZ_SUB_INLINE_FIELDS[ch.business_type] && BIZ_SUB_INLINE_FIELDS[ch.business_type].indexOf('business_address') !== -1) childShow.push('business_address');
            html += '<div class="m-subcard" style="border:1px solid var(--m-border);border-radius:10px;padding:10px;margin-bottom:8px;background:var(--m-card);' + (isCurrent ? 'box-shadow:0 0 0 2px #0a84ff;' : '') + ';cursor:pointer;" onclick="editBusinessMobile(' + ch.id + ')">';
            html += '<div style="font-size:13px;font-weight:600;margin-bottom:4px;">' + esc(ch.business_type) + (isCurrent ? ' · 当前' : '') + '</div>';
            childShow.forEach(function(key) {
                var f = BIZ_FIELD_POOL[key];
                if (!f) return;
                var disp = bizFieldDisplay(f, ch[key]);
                if (!disp || disp === '-') return;  // 仅显示有值项（空/占位「-」不渲染）
                html += '<div class="form-group biz-row" style="margin-bottom:2px;"><label>' + f.label + '</label><div style="font-size:13px;">' + esc(disp) + '</div></div>';
            });
            html += '<div style="display:flex;gap:8px;margin-top:6px;">' +
                '<button class="btn btn-outline" style="flex:1;padding:6px;font-size:12px;justify-content:center;" onclick="event.stopPropagation();editBusinessMobile(' + ch.id + ')">编辑</button>' +
                '<button class="btn btn-outline" style="flex:1;padding:6px;font-size:12px;justify-content:center;" onclick="event.stopPropagation();deleteBusinessMobile(' + ch.id + ', \'' + (ch.company_name || '').replace(/'/g, '') + '\')">删除</button>' +
            '</div>';
            html += '</div>';
        });
        html += '</div>';
    }

    html += '</div>';  // 关闭 .biz-detail 包裹

    content.innerHTML = html;
    renderIcons(content);
}

function addBusinessMobile(customerId, customerName) {
    // 打开编辑表单（空表单 = 新增）
    editBusinessMobile(null);
    // 如果从客户详情页调用，预填客户信息
    if (customerId && customerName) {
        // 等表单渲染完，设置客户搜索框和隐藏ID
        var timer = setInterval(function() {
            var input = document.getElementById('mbizCustSearch');
            var hidden = document.getElementById('mbizCustomerId');
            var label = document.getElementById('mbizCustLabel');
            if (input && hidden && label) {
                clearInterval(timer);
                input.value = customerName;
                hidden.value = customerId;
                label.innerHTML = '当前: ' + customerName;
                // 触发行内搜索过滤，选中正确的客户
                if (typeof filterBizCustomers === 'function') {
                    filterBizCustomers(customerName);
                }
            }
        }, 100);
    }
}

async function editBusinessMobile(id) {
    var biz = id ? (allBusinessesMobile ? allBusinessesMobile.find(function(b) { return b.id === id; }) : null) : null;
    var isNew = !biz;
    var content = document.getElementById('pageContent');
    // 进入编辑页前记录当前详情的滚动位置（从详情进编辑时 window.scrollY 即详情位置），返回时恢复
    if (id) window._bizDetailScrollY = window.scrollY;
    // 进入编辑页：底部「取消 / 保存」操作栏（不再用顶栏 X/✓）
    enterEditPage(function() { saveBusinessMobile(biz ? biz.id : null); });

    // 返回时同步重绘详情并恢复滚动位置（不再重跑 viewBusinessMobile 的异步加载+滚顶，避免闪屏与回到顶部）
    if (id) navPush('editbiz:' + id, function() {
        paintBizDetail(id);
        if (window._bizDetailScrollY != null) window.scrollTo(0, window._bizDetailScrollY);
    });

    // 加载客户列表供搜索
    if (!window._allBizCustomers) {
        window._allBizCustomers = [];
        api('/api/customers').then(function(customers) {
            window._allBizCustomers = customers;
        });
    }
    // 确保主卡数据已加载（关联主卡下拉用）
    if (!allBusinessesMobile || allBusinessesMobile.length === 0) {
        try { allBusinessesMobile = await api('/api/business'); } catch(e) { allBusinessesMobile = []; }
    }
    var existingCompany = (biz && biz.company_name) || '';
    var existingCustomerId = (biz && biz.customer_id) || '';
    var currentType = (biz && biz.business_type) || '';

    document.getElementById('pageTitle').textContent = isNew ? '新增业务' : '编辑业务';

    var html = '<div class="m-card">';
    html += '<div class="form-group"><label>关联客户 *</label>' +
        '<input type="text" class="form-control" id="mbizCustSearch" placeholder="搜索" style="font-size:13px;" oninput="filterBizCustomers(this.value)" value="' + existingCompany.replace(/"/g,'&quot;') + '" autocomplete="off">' +
        '<input type="hidden" id="mbizCustomerId" value="' + existingCustomerId + '">' +
        '<div id="mbizCustList" class="m-popup-card" style="max-height:240px;overflow-y:auto;border:1px solid var(--m-border);box-shadow:0 12px 40px rgba(0,0,0,0.15);background:var(--m-card);margin-top:6px;display:none;"></div></div>' +
        '<div style="font-size:12px;color:#888;margin-bottom:8px;" id="mbizCustLabel">' + (existingCompany ? '当前: ' + existingCompany : '请搜索并选择客户') + '</div>';
    html += '<div class="form-group"><label>业务类型 *</label>' +
        '<input type="hidden" id="mbizType" value="' + esc(currentType) + '">' +
        '<button type="button" class="form-control" id="mbizTypeBtn" style="display:flex;align-items:center;justify-content:space-between;cursor:pointer;text-align:left;" onclick="openBizTypePicker({hiddenId:\'mbizType\',labelId:\'mbizTypeLabel\',onChange:syncBizEditTypeUI})">' +
            '<span id="mbizTypeLabel">' + (currentType ? esc(currentType) : '请选择业务类型') + '</span>' +
            '<i class="m-icon" data-icon="chevronDown"></i>' +
        '</button></div>';
    html += '<div id="mbizFields"></div>';
    html += editActionBarHtml();
    html += '</div>';
    content.innerHTML = html;
    window._editingBizId = id;
    window._bizSubEntries = [];   // 编辑/新增主卡时清空内联子卡暂存（避免上一单残留）
    window._bizSubSeq = null;
    syncBizEditTypeUI();
}

// 编辑页：按所选业务类型动态渲染模块化字段（预填已有值）；子卡显示关联主卡下拉
function syncBizEditTypeUI() {
    var type = (document.getElementById('mbizType') ? document.getElementById('mbizType').value : '').trim();
    var box = document.getElementById('mbizFields');
    if (!box) return;
    var biz = window._editingBizId ? (allBusinessesMobile || []).find(function(b) { return b.id === window._editingBizId; }) : null;
    var fields = type ? (BIZ_TYPE_FIELDS[type] || []) : [];
    var html = '';
    fields.forEach(function(key) {
        var f = BIZ_FIELD_POOL[key];
        if (!f) return;
        var dv = biz ? (biz[key] != null ? biz[key] : '') : '';
        if (f.type === 'date' && typeof dv === 'string' && dv.length > 10) dv = dv.substring(0, 10);
        if (f.type === 'parent') {
            // 关联主卡：与新增共用同一套搜索菜单模板（bizParentFieldHtml），保留「不关联」且预填当前主卡
            var curPid = biz ? biz.parent_id : null;
            var curMain = curPid ? (allBusinessesMobile || []).find(function(b) { return b.id === curPid; }) : null;
            var curLabel = curMain ? ((curMain.number || '-') + (curMain.company_name ? '（' + curMain.company_name + '）' : '')) : '不关联（独立副卡）';
            var boxHtml = curPid
                ? ('<i class="m-icon" data-icon="done"></i> 已关联: <strong>' + esc(curLabel) + '</strong>')
                : esc('不关联（独立副卡）');
            html += bizParentFieldHtml('mbiz_', curPid, boxHtml);
        } else {
            html += bizFormFieldHtml(f, 'mbiz_', dv);
        }
    });
    // 主卡（数智惠企/冰激凌）编辑页与新增页一致：底部挂子卡（副卡/宽带/固话）管理
    if (BIZ_MAIN_TYPES.indexOf(type) !== -1) {
        html += buildBizEditSubSectionHtml(biz);
    }
    box.innerHTML = html;
    renderIcons(box);
    if (BIZ_MAIN_TYPES.indexOf(type) !== -1) renderBizSubEntries(); // 渲染已填写的内联子卡输入区
}

// 主卡编辑/新增页底部「子卡管理」区：列出已有子卡（编辑/删除）+ 新增副卡/宽带/固话入口
function buildBizEditSubSectionHtml(biz) {
    var html = '<div id="mBizSubWrap" style="margin-top:12px;">' +
        '<div style="font-size:13px;color:var(--m-text-secondary);margin-bottom:6px;">子卡（副卡 / 宽带 / 固话，将自动关联本主卡）</div>';
    // 已有子卡（落库，可单独编辑/删除）
    var existing = (allBusinessesMobile || []).filter(function(b) { return biz && b.parent_id === biz.id; });
    if (existing.length) {
        html += '<div style="font-size:12px;color:#888;margin:6px 0 4px;">已有子卡（' + existing.length + '）</div>';
        existing.forEach(function(ch) {
            html += '<div class="m-subcard" style="border:1px solid var(--m-border);border-radius:10px;padding:8px;margin-bottom:6px;background:var(--m-card);">' +
                '<div style="font-size:13px;font-weight:600;margin-bottom:4px;">' + esc(ch.business_type) + ' · ' + esc(ch.number || '-') + '</div>' +
                '<div style="display:flex;gap:8px;">' +
                    '<button class="btn btn-outline" style="flex:1;padding:6px;font-size:12px;justify-content:center;" onclick="editBusinessMobile(' + ch.id + ')">编辑</button>' +
                    '<button class="btn btn-outline" style="flex:1;padding:6px;font-size:12px;justify-content:center;" onclick="deleteBusinessMobile(' + ch.id + ', \'' + (ch.company_name || '').replace(/'/g, '') + '\')">删除</button>' +
                '</div></div>';
        });
    }
    html += '<div id="mBizSubEntries"></div>';
    html += bizSubButtonsHtml() + '</div>';
    return html;
}

// 客户搜索过滤（用于新增业务的客户选择）
function filterBizCustomers(keyword) {
    var kw = (keyword || '').trim().toLowerCase();
    var customers = window._allBizCustomers || [];
    var listEl = document.getElementById('mbizCustList');
    var labelEl = document.getElementById('mbizCustLabel');
    if (!listEl || !labelEl) return;

    // 如果用户手动改输入框，清除已选的客户ID
    var hiddenId = document.getElementById('mbizCustomerId');
    if (hiddenId && hiddenId.value) {
        // 检查输入是否匹配已选客户的名称
        var selected = customers.find(function(c) { return String(c.id) === String(hiddenId.value); });
        if (selected && (selected.company || selected.name) !== keyword) {
            hiddenId.value = '';
        }
    }

    if (!kw) {
        listEl.style.display = 'none';
        return;
    }

    var filtered = customers.filter(function(c) {
        return (c.company || c.name || '').toLowerCase().includes(kw);
    });

    if (filtered.length === 0) {
        listEl.innerHTML = custCreateRowHtml({ searchInputId: 'mbizCustSearch', hiddenId: 'mbizCustomerId', labelId: 'mbizCustLabel', listId: 'mbizCustList', onType: '', kw: keyword });
        listEl.style.display = 'block';
        return;
    }

    listEl.innerHTML = filtered.map(function(c, i) {
        return '<div class="m-cust-option" data-id="' + c.id + '" data-name="' + (c.company || c.name || '').replace(/"/g,'&quot;') + '"' +
            ' style="padding:10px 12px;cursor:pointer;border-bottom:' + (i < filtered.length - 1 ? '1px solid #f0f0f0' : 'none') + ';font-size:14px;"' +
            ' onmouseover="this.style.background=\'#f0f4ff\'" onmouseout="this.style.background=\'\'"' +
            ' onclick="selectBizCustomer(' + c.id + ',\'' + (c.company || c.name || '').replace(/'/g,'') + '\')">' +
            '<strong>' + (c.company || c.name || '-') + '</strong>' +
            '<span style="float:right;color:#888;font-size:12px;">' + (c.category || '') + '</span>' +
            '</div>';
    }).join('');
    listEl.style.display = 'block';
}

// 选择客户（业务）
function selectBizCustomer(id, name) {
    document.getElementById('mbizCustSearch').value = name;
    document.getElementById('mbizCustomerId').value = id;
    document.getElementById('mbizCustList').style.display = 'none';
    document.getElementById('mbizCustLabel').innerHTML = '<i class="m-icon" data-icon="done"></i> 已选择: <strong>' + name + '</strong>';
}

async function saveBusinessMobile(id) {
    // 若关联客户是乐观新建（尚未落库），先等其实 id 就绪，避免下游用幻影 id 提交
    if (window._pendingCustomerCreate) {
        try { await window._pendingCustomerCreate; } catch (e) { showToast('客户新建失败', 'error'); return; }
    }
    var customerId = parseInt(document.getElementById('mbizCustomerId').value) || null;
    var companyName = document.getElementById('mbizCustSearch').value.trim();
    // 与新增事项一致：必须关联（选择）一个客户，未关联无法新建/保存
    if (!customerId) { showToast('请选择关联客户', 'error'); return; }
    var type = (document.getElementById('mbizType') ? document.getElementById('mbizType').value : '').trim();
    if (!type) { showToast('请选择业务类型', 'error'); return; }
    var fields = BIZ_TYPE_FIELDS[type] || [];
    var data = { business_type: type, company_name: companyName, customer_id: customerId };
    fields.forEach(function(key) {
        var f = BIZ_FIELD_POOL[key];
        if (!f) return;
        if (key === 'parent_id') {
            var pid = (document.getElementById('mbiz_parent_id') ? document.getElementById('mbiz_parent_id').value : '').trim();
            data.parent_id = pid ? parseInt(pid) : null;
        } else {
            var el = document.getElementById('mbiz_' + key);
            var val = el ? el.value.trim() : '';
            data[key] = (f.type === 'number') ? (val ? parseFloat(val) : null) : val;
        }
    });
    // 主卡（数智惠企/冰激凌）编辑/新增时一并挂的内联子卡（副卡/宽带/固话）：收集后随主卡落库
    var isMainType = BIZ_MAIN_TYPES.indexOf(type) !== -1;
    var subCards = isMainType ? collectBizSubCards(data) : [];
    if (id) {
        // 编辑：本地先更新缓存 → 立即返回详情（乐观），后台 PUT，失败回滚
        var old = allBusinessesMobile ? allBusinessesMobile.find(function(b) { return b.id === id; }) : null;
        var bak = old ? JSON.parse(JSON.stringify(old)) : null;
        optimisticWrite({
            applyLocal: function() {
                if (old) {
                    old.business_type = data.business_type; old.company_name = data.company_name; old.customer_id = data.customer_id;
                    fields.forEach(function(key) { if (key !== 'parent_id') old[key] = data[key]; });
                    old.parent_id = data.parent_id;
                }
                navBack(); // 返回业务详情（从缓存即时重绘）
            },
            submit: async function() {
                await api('/api/business/' + id, { method: 'PUT', body: JSON.stringify(data) });
                for (var i = 0; i < subCards.length; i++) {
                    subCards[i].parent_id = id;
                    await api('/api/business', { method: 'POST', body: JSON.stringify(subCards[i]) });
                }
            },
            onSuccess: function() {
                // 返回页已在 applyLocal→navBack 的 returnFn 中从缓存即时重绘（paintBizDetail(id)），
                // 这里只置脏标记触发后续列表/详情按需重拉，切勿再 paintBizDetail（否则详情闪两次）。
                allBusinessesMobile = null; window._businessNeedRefresh = true;
                showToast('已更新' + (subCards.length ? '（含 ' + subCards.length + ' 张子卡）' : ''), 'success');
            },
            rollback: function(err) {
                if (bak && old) {
                    Object.keys(bak).forEach(function(k){ old[k] = bak[k]; });
                }
                showToast('保存失败: ' + (err && err.message ? err.message : err), 'error');
                viewBusinessMobile(id, true); // 详情页即时重绘为旧值（不重复压栈）
            }
        });
    } else {
        // 新建：临时记录入 _pendingCreates，立即返回列表（乐观），后台 POST，失败回滚
        var tmpId = 'tmp_biz_' + Date.now() + '_' + Math.floor(Math.random() * 1e4);
        optimisticWrite({
            applyLocal: function() {
                window._pendingCreates.push({ tmpId: tmpId, src: 'business', customer_id: customerId,
                    company_name: companyName, sub_type: data.business_type,
                    contract_amount: data.contract_amount, contract_code: data.contract_code || '',
                    business_number: data.number, _pending: true });
                navBack(); // 立即返回列表（秒回），临时记录已在返回页渲染
            },
            submit: async function() {
                var created = await api('/api/business', { method: 'POST', body: JSON.stringify(data) });
                var mainId = created && created.id;
                for (var i = 0; i < subCards.length; i++) {
                    subCards[i].parent_id = mainId;
                    await api('/api/business', { method: 'POST', body: JSON.stringify(subCards[i]) });
                }
            },
            onSuccess: function() {
                removePending(tmpId);
                allBusinessesMobile = null; window._businessNeedRefresh = true;
                showToast('已新增' + (subCards.length ? '（含 ' + subCards.length + ' 张子卡）' : ''), 'success');
                refreshReturnPagesForCustomer(customerId);
            },
            rollback: function(err) {
                removePending(tmpId);
                showToast('新增失败: ' + (err && err.message ? err.message : err), 'error');
                refreshReturnPagesForCustomer(customerId);
            }
        });
    }
}

async function deleteBusinessMobile(id, name, cascade) {
    // cascade 未指定（如详情页子卡删除按钮直接调用）默认级联，保持旧行为
    if (cascade === undefined) cascade = true;
    var kids = (allBusinessesMobile || []).filter(function(b) { return b.parent_id === id; });
    var mainKey = 'biz:' + id;
    optimisticWrite({
        applyLocal: function() {
            addPendingDelete(mainKey);
            if (cascade) {
                kids.forEach(function(k) { addPendingDelete('biz:' + k.id); });
            } else {
                // 仅删主卡：子卡变孤儿（parent_id 置空），立即在列表中可见
                kids.forEach(function(k) { if (k) k.parent_id = null; });
            }
            rerenderVisibleAfterMutation(); // 立即从当前可见视图更新（列表或客户详情）
        },
        submit: async function() {
            if (cascade) {
                for (var i = 0; i < kids.length; i++) {
                    await api('/api/business/' + kids[i].id, { method: 'DELETE' });
                }
            }
            await api('/api/business/' + id, { method: 'DELETE' });
        },
        onSuccess: function() {
            if (allBusinessesMobile) {
                if (cascade) {
                    allBusinessesMobile = allBusinessesMobile.filter(function(b) { return b.id !== id && b.parent_id !== id; });
                } else {
                    allBusinessesMobile = allBusinessesMobile.filter(function(b) { return b.id !== id; });
                    // 孤儿子卡 parent_id 同步为 null（DB 因外键 ON DELETE SET NULL 已置空）
                    (allBusinessesMobile || []).forEach(function(b) { if (b.parent_id === id) b.parent_id = null; });
                }
            }
            removePendingDelete(mainKey);
            window._businessNeedRefresh = true;
            showToast(cascade ? ('已删除' + (kids.length ? '（含 ' + kids.length + ' 张子卡）' : '')) : ('已删除主卡，' + kids.length + ' 张子卡已保留为独立业务'), 'success');
        },
        rollback: function(err) {
            removePendingDelete(mainKey);
            if (!cascade) {
                // 恢复：孤儿重新关联本主卡
                kids.forEach(function(k) { if (k) k.parent_id = id; });
            }
            showToast('删除失败: ' + (err && err.message ? err.message : err), 'error');
            rerenderVisibleAfterMutation();
        }
    });
}

// 移动端联系人渲染（无电话 emoji 图标，仅显示 序号. 姓名 电话）
function renderContactsMobile(c) {
    const names = (c.contact || '').split('||');
    const phones = (c.phone || '').split('||');
    const max = Math.max(names.length, phones.length, 1);
    var parts = [];
    for (let i = 0; i < max; i++) {
        const name = names[i] || (i === 0 ? (c.name || '') : '');
        const phone = phones[i] || '';
        // 仅当姓名与电话均为空时跳过该槽位（不可 filter(Boolean)，否则空电话槽被删、姓名/电话错位）
        if (!name && !phone) continue;
        // 注意：电话链接必须用字符串拼接（不能把 ${...} 包进单/双引号字符串，否则不会求值、会原样显示成 ${esc(phone)}）
        var phoneHtml = phone ? '  <a class="m-tel-link" href="tel:' + telHref(phone) + '" onclick="event.stopPropagation()">' + esc(phone) + '</a>' : '';
        parts.push('<div style="margin:4px 0;">' + (i + 1) + '. ' + esc(name) + phoneHtml + '</div>');
    }
    return parts.join('') || '-';
}

async function viewCustomerMobile(id, refresh) {
    enterSubPage();
    if (refresh) window._subAutoScroll = false; // 就地刷新：不滚顶，保留当前滚动位置
    // 注意：navPush 已由调用方（客户列表项、编辑返回等）完成，此处不再重复压栈。
    // 若需要首次进入时主动压栈，应修改调用方而非在此处 push。
    // 不显示"加载中"框架，保留原列表直到数据返回（与业务页一致，避免二次滑入动画）
    var content = document.getElementById('pageContent');
    var prevScrollY = window.scrollY;
    window._viewingCustomerId = id;

    // 优先命中本地列表缓存，仅在数据缺失时补拉（与业务 viewBusinessMobile 对齐：列表已加载则零/少网络）
    var cLocal = (window._allCustomersMobile || []).find(function(x) { return x.id === id; });
    var tasksLocal = window._allTasksMobile || [];
    var bizLocal = allBusinessesMobile;
    var subsLocal = window._allSubtasksMobile;

    var c = cLocal || null;
    var businesses = (bizLocal && bizLocal.length) ? bizLocal.filter(function(b) { return String(b.customer_id) === String(id); }) : null;
    var allSubs = subsLocal || null;
    var tasksArr = (tasksLocal && tasksLocal.length) ? tasksLocal.filter(function(t) { return String(t.customer_id) === String(id); }) : null;

    // 缓存缺失时一次性拉取详情所需全部数据（客户+业务+事项+子待办），把最多 4 次网络往返压缩为 1 次；
    // 仍遵循「仅缺失补拉」原则（本地缓存命中则 0 请求），不退回无条件批量拉取。
    var needBundle = (!c || businesses == null || allSubs == null || tasksArr == null);
    if (needBundle) {
        try {
            var bundle = await api('/api/customers/' + id + '/bundle');
            if (!c) c = bundle.customer || null;
            if (businesses == null) businesses = bundle.businesses || [];
            if (allSubs == null) { allSubs = bundle.subtasks || []; window._allSubtasksMobile = allSubs; }
            // 直接使用 bundle 返回的「本客户事项」，避免再拉取整张任务表；不写入 _allTasksMobile 全局缓存，
            // 以免污染其它客户详情的缓存命中判断（全局任务缓存仍由 loadTasksMobile 在其 tab 加载时填充）。
            if (tasksArr == null) tasksArr = bundle.tasks || [];
        } catch (e) {
            if (!c) c = null;
            if (businesses == null) businesses = [];
            if (allSubs == null) allSubs = [];
            if (tasksArr == null) tasksArr = [];
        }
    }
    if (!c) { showToast('客户不存在', 'error'); return; }
    if (businesses == null) businesses = [];
    if (allSubs == null) allSubs = [];
    if (tasksArr == null) tasksArr = [];

    const data = { customer: c, tasks: tasksArr };
    const detailSubMap = {};
    allSubs.forEach(function(s) { if (!detailSubMap[s.task_id]) detailSubMap[s.task_id] = []; detailSubMap[s.task_id].push(s); });
    // 缓存供 paintCustomerDetail 即时重绘（编辑返回 / 就地刷新），避免重复网络往返与返回时滚顶
    window._viewingCustomerCache = { id: id, data: data, c: c, businesses: businesses, allSubs: allSubs, detailSubMap: detailSubMap, prevScrollY: prevScrollY };
    paintCustomerDetail(id);

    // 首次进入的滚顶由 #pageContent 观察器在内容渲染后完成；刷新模式（就地更新）恢复原位
    if (refresh) window.scrollTo(0, prevScrollY);
}

// 渲染客户详情内容（联系人 / 业务区块 / 跟进事项）。单独抽出以便编辑返回 / 就地刷新时即时重绘，
// 不重走 viewCustomerMobile 的异步加载 + 滚顶（与业务页 paintBizDetail 同构，避免返回时闪屏与回到顶部）。
function paintCustomerDetail(id) {
    var cache = window._viewingCustomerCache;
    if (!cache || cache.id !== id) { viewCustomerMobile(id, true); return; } // 缓存缺失兜底：重新拉取
    var content = document.getElementById('pageContent');
    var data = cache.data, c = cache.c, businesses = cache.businesses, allSubs = cache.allSubs, detailSubMap = cache.detailSubMap;
    document.getElementById('pageTitle').textContent = c.company || c.name || '-';
    var dest = (c.company || c.name || '目的地').replace(/['"]/g, '');

    // 业务区块（单表 businesses，业务与「台账」已合并为同一张表）：列出该客户名下全部记录，置顶显示
    // 统一按具体业务类型(business_type)归类，与业务页「业务」标签同构；sub_type 作为筛选依据
    var items = [];
    (businesses || []).forEach(function(b) {
        items.push({
            id: b.id,
            company_name: b.company_name || '-',
            sub_type: b.business_type || '',
            contract_amount: b.contract_amount,
            contract_code: b.contract_code || '',
            business_number: b.number || '',
            parent_id: b.parent_id
        });
    });
    // 拼接乐观更新的临时记录（仅该客户名下）：提交成功由 onSuccess 移除，失败由 rollback 移除
    (window._pendingCreates || []).forEach(function(p) {
        if (String(p.customer_id) !== String(id)) return;
        if (p.src !== 'business') return;
        if (BIZ_CHILD_TYPES.indexOf(p.sub_type) !== -1) return; // 内联子卡不单独展示
        items.push({ id: 'P' + p.tmpId, company_name: p.company_name, sub_type: p.sub_type, contract_amount: p.contract_amount, contract_code: p.contract_code || '', business_number: p.business_number || '', _pending: true, parent_id: null });
    });
    // 乐观删除：过滤掉标记为待删除的记录；子卡（关联主卡存在）不在列表展示，仅展示主卡
    items = items.filter(function(b) {
        if (b._pending) return true;
        if (b.parent_id) return false;
        var key = 'biz:' + b.id;
        return !isPendingDelete(key);
    });
    var ledgerHtml;
    if (items.length === 0) {
        ledgerHtml = '<div class="m-empty m-empty-mini"><div class="icon"><i class="m-icon" data-icon="empty"></i></div>暂无业务</div>';
    } else {
        ledgerHtml = '<div class="m-group-list">' + items.map(function(b) {
            return bizGroupItemHtml(b, "navPush('bizcust:" + c.id + "',function(){viewCustomerMobile(" + c.id + ")});viewBusinessMobile(" + b.id + ")");
        }).join('') + '</div>';
    }
    // 跟进事项区块（与事项看板一致展现形式）
    var custTasks = (data.tasks || []).filter(function(t) { return !isPendingDelete('task:' + t.id); });
    (window._pendingCreates || []).forEach(function(p) {
        if (p.src !== 'task') return;
        if (String(p.customer_id) !== String(id)) return;
        custTasks.push({ id: 'P' + p.tmpId, _pending: true, title: p.title, customer_id: p.customer_id, customer_company: p.customer_company, customer_name: p.customer_name, status: '进行中', created_at: p.created_at || '', pinned: false, description: p.description || '', due_date: p.due_date || '' });
    });
    var taskHtml;
    if (custTasks.length === 0) {
        taskHtml = '<div class="m-empty m-empty-mini"><div class="icon"><i class="m-icon" data-icon="empty"></i></div>暂无事项</div>';
    } else {
        taskHtml = custTasks.map(function(t) {
            return renderTaskCard(t, detailSubMap, 'editTaskMobile(' + t.id + ',' + c.id + ')');
        }).join('');
    }

    content.innerHTML =
        '<div class="m-card" id="mCustInfoCard" style="cursor:pointer;" onclick="editCustomerMobile(' + c.id + ')">' +
            '<div style="font-size:14px;line-height:2;">' +
                '<div><strong>联系人:</strong><br>' + renderContactsMobile(c) + '</div>' +
                '<div><i class="m-icon" data-icon="mail"></i> ' + (c.email || '-') + '</div>' +
                '<div class="m-addr-tap" onclick="event.stopPropagation();openCustNav(' + c.latitude + ',' + c.longitude + ",'" + dest + '\')"><i class="m-icon" data-icon="location"></i> ' + (c.address || '未填写地址') + '</div>' +
                '<div><i class="m-icon" data-icon="tag"></i> ' + categoryBadge(c.category) + ' <span class="badge priority-' + c.priority + '">' + c.priority + '优先级</span></div>' +
            '</div>' +
            (c.notes ? '<div class="alert alert-info" style="margin-top:12px;"><i class="m-icon" data-icon="note"></i> ' + c.notes + '</div>' : '') +
        '</div>' +
        '<div class="m-card" style="position:relative;padding-bottom:52px;">' +
            '<div class="m-card-title"><span><i class="m-icon" data-icon="note"></i> 业务 (' + (businesses || []).length + ')</span></div>' +
            ledgerHtml +
            '<button class="m-fab-sm" onclick="addBizEntryForCustomer(' + c.id + ',\'' + (c.company || c.name || '').replace(/'/g, '') + '\')" aria-label="新增业务">' + ICONS.add + '</button>' +
        '</div>' +
        '<div class="m-card" style="position:relative;padding-bottom:52px;">' +
            '<div class="m-card-title"><span><i class="m-icon" data-icon="clipboard"></i> 跟进事项 (' + custTasks.length + ')</span></div>' +
            taskHtml +
            '<button class="m-fab-sm" onclick="addTaskMobile(' + c.id + ',\'' + (c.company || c.name || '').replace(/'/g, '') + '\')" aria-label="新增事项">' + ICONS.add + '</button>' +
        '</div>';
    renderIcons(content); // 嵌套重绘后补图标，否则右侧箭头不显示

    // 长按业务卡片 → 删除（单表 businesses，统一走 deleteBusinessMobile）
    content.querySelectorAll('.m-group-item[data-id]').forEach(function(el) {
        var idAttr = el.getAttribute('data-id');
        if (idAttr && idAttr.charAt(0) === 'P') return; // 临时记录不绑定删除
        var id = parseInt(idAttr, 10);
        var b = (businesses || []).find(function(x) { return x.id === id; });
        if (!b) return;
        bindLongPress(el, function() {
            confirmDeleteBusiness(id, b.company_name || '');
        });
    });
    // 长按事项卡片 → 弹出「置顶 / 删除」操作面板（与事项看板一致）
    content.querySelectorAll('.m-task-item[data-tid]').forEach(function(el) {
        bindLongPress(el, function() {
            var tid = parseInt(el.getAttribute('data-tid'), 10);
            var ttitle = el.getAttribute('data-ttitle') || '该事项';
            var pinned = el.classList.contains('pinned');
            showTaskActionSheet(tid, ttitle, pinned);
        });
    });
}

async function editCustomerMobile(id) {
    // 进入编辑页前记录当前详情的滚动位置（从详情进编辑时 window.scrollY 即详情位置），返回时恢复
    if (id) window._custDetailScrollY = window.scrollY;
    // 进入编辑页：底部「取消 / 保存」操作栏（不再用顶栏 X/✓）
    enterEditPage(function() { saveEditCustomerMobile(id); });
    // 返回时同步重绘详情并恢复滚动位置（不再重跑 viewCustomerMobile 的异步加载+滚顶，避免闪屏与回到顶部）
    if (id) navPush('editcust:' + id, function() {
        paintCustomerDetail(id);
        if (window._custDetailScrollY != null) window.scrollTo(0, window._custDetailScrollY);
    });
    var content = document.getElementById('pageContent');
    content.innerHTML = '<div class="m-card"><div class="m-empty"><div class="icon"><i class="m-icon" data-icon="loading"></i></div><div>加载中...</div></div></div>';

    const data = await api(`/api/customers/${id}`);
    const c = data.customer;
    if (!c) { showToast('未找到该客户', 'error'); return; }
    document.getElementById('pageTitle').textContent = '编辑客户';
    content.innerHTML = `
        <div class="m-card">
            <div class="form-group">
                <label>公司名称</label>
                <input type="text" class="form-control" id="mEditCompany" value="${(c.company || '').replace(/"/g,'&quot;')}">
            </div>
            <div class="form-group">
                <label>法人</label>
                <input type="text" class="form-control" id="mEditName" value="${(c.name || '').replace(/"/g,'&quot;')}">
            </div>
            <div class="form-group" style="grid-column:1/3;">
                <label>联系人组 <span style="font-size:12px;color:#888;">（最多4组，空联系人自动显示法人）</span></label>
                <div id="mContactGroupContainer"></div>
                <button type="button" class="btn btn-outline btn-sm" onclick="addMContactGroup()" id="mAddContactBtn" style="margin-top:4px;font-size:12px;">+ 添加联系人</button>
            </div>
            <div class="form-group">
                <label>邮箱</label>
                <input type="text" class="form-control" id="mEditEmail" value="${(c.email || '').replace(/"/g,'&quot;')}">
            </div>
            <div class="form-group">
                <label>地址</label>
                <input type="text" class="form-control" id="mEditAddress" value="${(c.address || '').replace(/"/g,'&quot;')}">
            </div>
            <div class="form-group">
                <label>分类</label>
                <select class="form-control" id="mEditCategory">
                    <option value="普通客户" ${c.category === '普通客户' ? 'selected' : ''}>普通客户</option>
                    <option value="核心要客" ${c.category === '核心要客' || c.category === 'VIP客户' ? 'selected' : ''}>核心要客</option>
                    <option value="TOP20" ${c.category === 'TOP20' || c.category === '重要客户' ? 'selected' : ''}>TOP20</option>
                </select>
            </div>
            <div class="form-group">
                <label>优先级</label>
                <select class="form-control" id="mEditPriority">
                    <option value="低" ${c.priority === '低' ? 'selected' : ''}>低</option>
                    <option value="中" ${(!c.priority || c.priority === '中' || c.priority === '重要不紧急') ? 'selected' : ''}>中</option>
                    <option value="高" ${c.priority === '高' || c.priority === '重要且紧急' ? 'selected' : ''}>高</option>
                </select>
            </div>
            <div class="form-group">
                <label>备注</label>
                <textarea class="form-control" id="mEditNotes" rows="3">${(c.notes || '').replace(/"/g,'&quot;')}</textarea>
            </div>
            ${editActionBarHtml()}
        </div>
    `;
    // 初始化联系人组
    const _contacts = (c.contact || '').split('||');
    const _phones = (c.phone || '').split('||');
    const _container = document.getElementById('mContactGroupContainer');
    let _mCount = 0;
    for (let i = 0; i < Math.max(_contacts.length, _phones.length, 1); i++) {
        _container.insertAdjacentHTML('beforeend', _renderMGroup(i, _contacts[i] || '', _phones[i] || ''));
        _mCount++;
    }
    _updateMAddBtn(_mCount);
    window._mCount = _mCount;
    window.addMContactGroup = () => {
        const cnt = window._mCount || 0;
        if (cnt >= 4) { showToast('最多添加4组联系人', 'error'); return; }
        document.getElementById('mContactGroupContainer').insertAdjacentHTML('beforeend', _renderMGroup(cnt, '', ''));
        window._mCount = cnt + 1;
        _updateMAddBtn(cnt + 1);
    };
    window.removeMContactGroup = (btn) => {
        btn.closest('.contact-group').remove();
        const _gs = document.querySelectorAll('#mContactGroupContainer .contact-group');
        window._mCount = _gs.length;
        _updateMAddBtn(_gs.length);
    };
    function _renderMGroup(idx, n, p) {
        const isFirst = idx === 0;
        return `<div class="contact-group" style="display:flex;gap:4px;margin-bottom:4px;align-items:center;">
            <input type="text" class="form-control cg-name" placeholder="联系人" value="${(n || '').replace(/"/g,'&quot;')}" style="flex:1;font-size:13px;padding:6px 8px;">
            <input type="text" class="form-control cg-phone" placeholder="联系电话" value="${(p || '').replace(/"/g,'&quot;')}" style="flex:1;font-size:13px;padding:6px 8px;">
            <button type="button" class="btn btn-danger btn-sm" onclick="removeMContactGroup(this)" ${isFirst ? 'disabled style="opacity:0.4"' : ''} style="flex-shrink:0;"><i class="m-icon" data-icon="close"></i></button>
        </div>`;
    }
    function _updateMAddBtn(cnt) {
        const btn = document.getElementById('mAddContactBtn');
        if (btn) btn.style.display = cnt >= 4 ? 'none' : '';
        const _gs = document.querySelectorAll('#mContactGroupContainer .contact-group');
        if (_gs.length > 0) {
            _gs[0].querySelector('.btn-danger').disabled = true;
            _gs[0].querySelector('.btn-danger').style.opacity = '0.4';
        }
    }
}

async function saveEditCustomerMobile(id) {
    const names = [], phones = [];
    document.querySelectorAll('#mContactGroupContainer .contact-group').forEach(g => {
        const n = g.querySelector('.cg-name').value.trim();
        const p = g.querySelector('.cg-phone').value.trim();
        if (n || p) { names.push(n); phones.push(p); }
    });
    const data = {
        company: document.getElementById('mEditCompany').value,
        name: document.getElementById('mEditName').value,
        contact: names.join('||'),
        phone: phones.join('||'),
        email: document.getElementById('mEditEmail').value,
        address: document.getElementById('mEditAddress').value,
        category: document.getElementById('mEditCategory').value,
        priority: document.getElementById('mEditPriority').value,
        notes: document.getElementById('mEditNotes').value
    };
    // 乐观更新：先缓存 + 返回，API 后台同步
    markCustomersDirty();
    if (window._viewingCustomerCache && window._viewingCustomerCache.id === id) {
        Object.assign(window._viewingCustomerCache.data.customer, data);
    }
    quickSave(api(`/api/customers/${id}`, { method: 'PUT', body: data }), {
        successMsg: '保存成功', errorMsg: '保存失败', after: navBack
    });
}

async function deleteCustomerMobile(id, name) {
    markCustomersDirty();
    quickSave(api(`/api/customers/${id}`, { method: 'DELETE' }), {
        successMsg: '已删除', errorMsg: '删除失败', after: navBack
    });
}

// 标记客户列表需刷新：丢弃数据缓存并置位标记（供 switchPage 在进入客户页时强制重拉）
function markCustomersDirty() {
    window._allCustomersMobile = null;
    window._customersNeedRefresh = true;
}

// ==================== 新增客户 ====================

async function addCustomerMobile() {
    enterSubPage();
    navPush('addcustomer', function() { switchPage('customers'); });
    const content = document.getElementById('pageContent');
    document.getElementById('pageTitle').textContent = '新增客户';
    content.innerHTML = `
        <div class="m-card">
            <div class="form-group">
                <label>公司名称</label>
                <input type="text" class="form-control" id="mNewCompany" placeholder="输入公司名称">
            </div>
            <div class="form-group">
                <label>法人</label>
                <input type="text" class="form-control" id="mNewName" placeholder="法定代表人">
            </div>
            <div class="form-group" style="grid-column:1/3;">
                <label>联系人组 <span style="font-size:12px;color:#888;">（最多4组）</span></label>
                <div id="mNewContactGroupContainer"></div>
                <button type="button" class="btn btn-outline btn-sm" onclick="addNewMGroup()" id="mNewAddBtn" style="margin-top:4px;font-size:12px;">+ 添加联系人</button>
            </div>
            <div class="form-group">
                <label>邮箱</label>
                <input type="text" class="form-control" id="mNewEmail" placeholder="输入邮箱">
            </div>
            <div class="form-group">
                <label>地址</label>
                <input type="text" class="form-control" id="mNewAddress" placeholder="输入地址">
            </div>
            <div class="form-group">
                <label>分类</label>
                <select class="form-control" id="mNewCategory">
                    <option value="普通客户" selected>普通客户</option>
                    <option value="核心要客">核心要客</option>
                    <option value="TOP20">TOP20</option>
                </select>
            </div>
            <div class="form-group">
                <label>优先级</label>
                <select class="form-control" id="mNewPriority">
                    <option value="低">低</option>
                    <option value="中" selected>中</option>
                    <option value="高">高</option>
                </select>
            </div>
            <div class="form-group">
                <label>备注</label>
                <textarea class="form-control" id="mNewNotes" rows="3" placeholder="可选备注"></textarea>
            </div>
            <div style="display:flex;gap:8px;margin-top:12px;">
                <button class="btn btn-outline" style="flex:1;padding:12px;justify-content:center;" onclick="navBack()">取消</button>
                <button class="btn btn-primary" style="flex:1;padding:12px;justify-content:center;" onclick="saveAddCustomerMobile()"><i class="m-icon" data-icon="save"></i> 保存</button>
            </div>
        </div>
    `;
    // 初始化一组空的联系人
    var _c = document.getElementById('mNewContactGroupContainer');
    _c.insertAdjacentHTML('beforeend', '<div class="contact-group" style="display:flex;gap:4px;margin-bottom:4px;align-items:center;"><input type="text" class="form-control cg-name" placeholder="联系人" style="flex:1;font-size:13px;padding:6px 8px;"><input type="text" class="form-control cg-phone" placeholder="联系电话" style="flex:1;font-size:13px;padding:6px 8px;"><button type="button" class="btn btn-danger btn-sm" disabled style="flex-shrink:0;opacity:0.4;"><i class="m-icon" data-icon="close"></i></button></div>');
    window._mNewCount = 1;
    window.addNewMGroup = function() {
        var cnt = window._mNewCount || 1;
        if (cnt >= 4) { showToast('最多添加4组联系人', 'error'); return; }
        document.getElementById('mNewContactGroupContainer').insertAdjacentHTML('beforeend', '<div class="contact-group" style="display:flex;gap:4px;margin-bottom:4px;align-items:center;"><input type="text" class="form-control cg-name" placeholder="联系人" style="flex:1;font-size:13px;padding:6px 8px;"><input type="text" class="form-control cg-phone" placeholder="联系电话" style="flex:1;font-size:13px;padding:6px 8px;"><button type="button" class="btn btn-danger btn-sm" onclick="removeNewMGroup(this)" style="flex-shrink:0;"><i class="m-icon" data-icon="close"></i></button></div>');
        window._mNewCount = cnt + 1;
        _updateNewMAddBtn(cnt + 1);
    };
    window.removeNewMGroup = function(btn) {
        btn.closest('.contact-group').remove();
        var gs = document.querySelectorAll('#mNewContactGroupContainer .contact-group');
        window._mNewCount = gs.length;
        _updateNewMAddBtn(gs.length);
    };
    function _updateNewMAddBtn(cnt) {
        var btn = document.getElementById('mNewAddBtn');
        if (btn) btn.style.display = cnt >= 4 ? 'none' : '';
        var gs = document.querySelectorAll('#mNewContactGroupContainer .contact-group');
        if (gs.length > 0) {
            gs[0].querySelector('.btn-danger').disabled = true;
            gs[0].querySelector('.btn-danger').style.opacity = '0.4';
        }
    }
}

async function saveAddCustomerMobile() {
    var names = [], phones = [];
    document.querySelectorAll('#mNewContactGroupContainer .contact-group').forEach(function(g) {
        var n = g.querySelector('.cg-name').value.trim();
        var p = g.querySelector('.cg-phone').value.trim();
        if (n || p) { names.push(n); phones.push(p); }
    });
    var data = {
        company: document.getElementById('mNewCompany').value.trim(),
        name: document.getElementById('mNewName').value.trim(),
        contact: names.join('||'),
        phone: phones.join('||'),
        email: document.getElementById('mNewEmail').value.trim(),
        address: document.getElementById('mNewAddress').value.trim(),
        category: document.getElementById('mNewCategory').value,
        priority: document.getElementById('mNewPriority').value,
        notes: document.getElementById('mNewNotes').value.trim()
    };
    if (!data.company && !data.name) {
        showToast('请输入公司名称或法人', 'error');
        return;
    }
    markCustomersDirty();
    quickSave(api('/api/customers', { method: 'POST', body: data }), {
        successMsg: '新增成功', errorMsg: '新增失败', after: navBack
    });
}

// ==================== 坐标转换（全局） ====================
function _gcjTransformLat(lng, lat) {
    let ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * Math.sqrt(Math.abs(lng));
    ret += (20.0 * Math.sin(6.0 * lng * Math.PI) + 20.0 * Math.sin(2.0 * lng * Math.PI)) * 2.0 / 3.0;
    ret += (20.0 * Math.sin(lat * Math.PI) + 40.0 * Math.sin(lat / 3.0 * Math.PI)) * 2.0 / 3.0;
    ret += (160.0 * Math.sin(lat / 12.0 * Math.PI) + 320 * Math.sin(lat * Math.PI / 30.0)) * 2.0 / 3.0;
    return ret;
}
function _gcjTransformLng(lng, lat) {
    let ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * Math.sqrt(Math.abs(lng));
    ret += (20.0 * Math.sin(6.0 * lng * Math.PI) + 20.0 * Math.sin(2.0 * lng * Math.PI)) * 2.0 / 3.0;
    ret += (20.0 * Math.sin(lng * Math.PI) + 40.0 * Math.sin(lng / 3.0 * Math.PI)) * 2.0 / 3.0;
    ret += (150.0 * Math.sin(lng / 12.0 * Math.PI) + 300.0 * Math.sin(lng / 30.0 * Math.PI)) * 2.0 / 3.0;
    return ret;
}
function gcjOutOfChina(lng, lat) { return !(lng > 73.66 && lng < 135.05 && lat > 3.86 && lat < 53.55); }
function wgs84ToGcj02(lng, lat) {
    if (gcjOutOfChina(lng, lat)) return [lng, lat];
    const a = 6378245.0, ee = 0.00669342162296594323;
    let dlat = _gcjTransformLat(lng - 105.0, lat - 35.0);
    let dlng = _gcjTransformLng(lng - 105.0, lat - 35.0);
    const radlat = lat / 180.0 * Math.PI;
    let magic = Math.sin(radlat);
    magic = 1 - ee * magic * magic;
    const sqrtmagic = Math.sqrt(magic);
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * Math.PI);
    dlng = (dlng * 180.0) / (a / sqrtmagic * Math.cos(radlat) * Math.PI);
    return [lng + dlng, lat + dlat];
}

// ==================== 地图 ====================

let mobileMap = null;
let mobileMyMarker = null;
let mobileCustomerMarkers = [];

// 原生定位回调：进 APK 后 CustomerApp 桥主动推送 GPS 坐标（无需网页地理定位授权弹窗）。
// 用全局函数避免重复绑定；当前在地图页且地图已初始化时即时刷新定位。
window.onNativeLocation = function(lat, lon, accuracy, ts) {
    try {
        window._nativeLoc = {
            lat: parseFloat(lat), lon: parseFloat(lon),
            accuracy: parseFloat(accuracy) || 0,
            ts: ts ? parseInt(ts, 10) : Date.now()
        };
    } catch (e) {}
    if (currentPage === 'map' && window.mobileMap && document.getElementById('mobileMap')) {
        applyNativeLocationToMap();
    }
};

// 把原生 GPS 坐标应用到地图（重新居中 + 逆地理编码地址名）
function applyNativeLocationToMap() {
    var nl = window._nativeLoc;
    if (!nl || !window.mobileMap) return;
    window._mapLat = nl.lat;
    window._mapLon = nl.lon;
    updateMobileMap(nl.lat, nl.lon, window._mapCustomers);
    var locEl = document.getElementById('mLocationName');
    if (locEl) locEl.textContent = '定位中…';
    fetch('/api/reverse_geocode?lat=' + nl.lat.toFixed(6) + '&lon=' + nl.lon.toFixed(6))
        .then(function (r) { return r.json(); })
        .then(function (d) {
            var el = document.getElementById('mLocationName');
            if (el) el.textContent = d.address || (nl.lat.toFixed(4) + ', ' + nl.lon.toFixed(4));
        })
        .catch(function () {
            var el = document.getElementById('mLocationName');
            if (el) el.textContent = nl.lat.toFixed(4) + ', ' + nl.lon.toFixed(4);
        });
}

async function loadMapMobile() {

    const content = document.getElementById('pageContent');

    // 缓存标记：是否有能用的缓存数据
    var hasCache = window._mapData && window._mapData.timestamp && (Date.now() - window._mapData.timestamp < 60000);

    content.innerHTML = `
        <div class="m-map-container" id="mapContainer">
            <div id="mobileMap"></div>
        </div>
        <div class="m-map-spacer"></div>
        <div class="m-card">
            <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;">
                <span style="font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0;"><i class="m-icon" data-icon="location"></i> <span id="mLocationName">${hasCache ? '' : '加载中...'}</span></span>
                <button class="btn btn-outline" id="mRefreshBtn" style="font-size:11px;padding:2px 8px;border-radius:10px;line-height:1.5;flex-shrink:0;" onclick="refreshLocationMobile()"><i class="m-icon" data-icon="refresh"></i></button>
            </div>
            <div id="mMapCatFilters" style="display:flex;flex-wrap:nowrap;gap:4px;padding:0 0 6px 0;margin-bottom:4px;overflow-x:auto;"></div>
            <div style="font-size:13px;color:var(--m-text-secondary);margin-bottom:8px;">
                <span>附近客户（<span id="mNearbyCount">0</span> 个）</span>
                <span style="margin-left:8px;" id="mNearbyInfo"></span>
            </div>
            <div id="mNearbyList"></div>
        </div>
    `;

    // 动态加载 Leaflet
    if (!window.L) {
        await loadScript('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js');
        await loadCSS('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css');
    }

    // 走缓存则跳过 API
    let myLat, myLon, customers;
    if (hasCache) {
        var d = window._mapData;
        myLat = d.lat; myLon = d.lon;
        customers = d.customers;
    } else {
        const settings = await api('/api/settings');
        myLat = parseFloat(settings.my_latitude) || 30.358935;
        myLon = parseFloat(settings.my_longitude) || 114.323843;
        customers = await api('/api/customers');
        window._mapData = {
            lat: myLat, lon: myLon,
            customers: customers,
            timestamp: Date.now()
        };
    }
    window._mapLat = myLat;
    window._mapLon = myLon;
    window._mapCustomers = customers;

    // 进 APK 自动定位：优先用原生 GPS 坐标（CustomerApp 桥已推送或缓存），无需网页地理定位
    if (window.CustomerApp && typeof window.CustomerApp.getLastLocation === 'function') {
        try {
            var _nl = window.CustomerApp.getLastLocation();
            if (_nl) {
                var _o = JSON.parse(_nl);
                if (_o && _o.lat) {
                    window._nativeLoc = { lat: _o.lat, lon: _o.lon, accuracy: _o.accuracy || 0, ts: _o.ts || Date.now() };
                }
            }
        } catch (e) {}
    }
    if (window._nativeLoc && (Date.now() - (window._nativeLoc.ts || 0) < 120000)) {
        myLat = window._nativeLoc.lat;
        myLon = window._nativeLoc.lon;
        window._mapLat = myLat;
        window._mapLon = myLon;
    }

    // 初始化地图 - 高德底图（国内可达）
    // 复用已存在的地图实例：切换 Tab 返回地图时，仅把容器挂回新 DOM 并刷新尺寸，
    // 避免每次切换都销毁重建（瓦片重新下载、明显闪烁）。
    if (mobileMap && !hasCache) {
        try { mobileMap.remove(); } catch(e) {}
        mobileMap = null;
    }
    if (mobileMap) {
        var _host = document.getElementById('mobileMap');
        if (_host && mobileMap.getContainer().parentNode !== _host) {
            _host.appendChild(mobileMap.getContainer());
        }
        mobileMap.invalidateSize();
    } else {
        // zoomControl:false 去掉左上角 +/- 缩放按钮
        mobileMap = L.map('mobileMap', { zoomControl: false }).setView([30.358935, 114.323843], 12);
        L.tileLayer('https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}', {
            subdomains: '1234', maxZoom: 18, attribution: '© 高德地图'
        }).addTo(mobileMap);
        // 首次创建：延迟到容器布局稳定后再校准尺寸，避免抓到 Tab 切换过渡中的过渡尺寸（高度偏小）
        // 导致初始 setView/标记渲染用错尺寸。
        setTimeout(function() { if (mobileMap) mobileMap.invalidateSize(); }, 300);
    }

    // 用默认中心（湖北·武汉·江夏）先渲染一次附近列表，避免定位失败/未授权时一直停在「加载中…」
    updateMobileMap(myLat, myLon);
    var _locEl = document.getElementById('mLocationName');
    if (_locEl) _locEl.textContent = '湖北·武汉·江夏';

    // APK 内由原生 GPS 直接推送定位（window.onNativeLocation），不再走网页地理定位弹窗；
    // 浏览器环境仍用 navigator.geolocation 兜底。
    if (!window.CustomerApp && navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
            (pos) => {
                myLat = pos.coords.latitude;
                myLon = pos.coords.longitude;
                updateMobileMap(myLat, myLon, customers);
                // 逆地理编码获取地址名称
                fetch('/api/reverse_geocode?lat=' + myLat.toFixed(6) + '&lon=' + myLon.toFixed(6))
                    .then(r => r.json())
                    .then(d => {
                        document.getElementById('mLocationName').textContent = d.address || (myLat.toFixed(4) + ', ' + myLon.toFixed(4));
                    })
                    .catch(() => {
                        document.getElementById('mLocationName').textContent = myLat.toFixed(4) + ', ' + myLon.toFixed(4);
                    });
            },
            () => {},
            { timeout: 8000 }
        );
    }

    function categoryBadge(cat) {
        if (!cat) return '<span class="badge badge-normal">-</span>';
        const map = { '核心要客': 'badge-core', 'TOP20': 'badge-top20', '普通客户': 'badge-normal',
            'VIP客户': 'badge-core', '重要客户': 'badge-top20' };
        const cls = map[cat] || 'badge-normal';
        return `<span class="badge ${cls}">${cat}</span>`;
    }

    // 构建地图标记弹窗 HTML（紧凑左对齐，内容复用）
    function buildCustomerPopup(c, dist, cnt) {
        var cname = esc(c.company || c.name || '-');
        var addr = esc(c.address || '-');
        var dest = (c.company || c.name || '目的地').replace(/['"]/g, '');
        return '<div class="cp-wrap">' +
            '<div class="cp-title">\u{1F3DB}\uFE0F ' + cname + '</div>' +
            '<div class="cp-row cp-addr">\u{1F4CD} ' + addr + '</div>' +
            '<div class="cp-row">\u{1F697} 距离 <strong>' + dist.toFixed(2) + ' km</strong></div>' +
            '<div class="cp-actions">' +
                '<a class="cp-btn cp-btn-nav" href="javascript:void(0)" onclick="openNavigationMobile(' + c.latitude + ',' + c.longitude + ",'" + dest + '\')">导航</a>' +
                '<span class="cp-btn cp-btn-ci">' +
                    '<a href="javascript:void(0)" onclick="editCheckinMobile(' + c.id + ')">本月<span id="ci_' + c.id + '">' + cnt + '</span></a>' +
                    '<span class="cp-sep">|</span>' +
                    '<a href="javascript:void(0)" onclick="showCheckinConfirmMobile(' + c.id + ')">+1</a>' +
                '</span>' +
            '</div>' +
        '</div>';
    }

    // 用 Leaflet 原生弹窗（autoPan 自动平移，弹窗+标记整体居中的 padding）
    function openCustomerMapPopup(c, clat, clng, dist, cnt) {
        var _popup = L.popup({
            className: 'map-customer-popup',
            closeButton: true,
            autoPan: true,
            autoPanPadding: [50, 50],
            autoPanPaddingTopLeft: [10, 20],
            autoPanPaddingBottomRight: [10, 130],
            maxWidth: 350
        })
        .setLatLng([clat, clng])
        .setContent(buildCustomerPopup(c, dist, cnt));
        // 弹窗前重校准地图容器尺寸：应对容器在 Tab 切换/屏幕旋转/软键盘等场景下尺寸中途变化，
        // 让 autoPan 基于最新尺寸计算。invalidateSize 默认不带动画、同步开销极小，可安全每次调用。
        mobileMap.invalidateSize();
        _popup.openOn(mobileMap);
        setTimeout(function() { var pc = document.querySelector('.leaflet-popup-content'); if (pc) renderIcons(pc); }, 0);
    }

    // 打开客户地图弹窗，并后台异步刷新打卡次数：先瞬开（用内存缓存的 c.checkin_month），
    // 网络返回后仅更新弹窗内数字。marker 点击与 focusMobileCustomer 共用，消除重复逻辑。
    function openCustomerPopupWithCheckin(c, clat, clng, dist) {
        openCustomerMapPopup(c, clat, clng, dist, c.checkin_month || 0);
        fetch('/api/customers/' + c.id + '/checkin')
            .then(function(r) { return r.json(); })
            .then(function(d) { var el = document.getElementById('ci_' + c.id); if (el) el.textContent = d.count; })
            .catch(function() {});
    }

    async function updateMobileMap(lat, lon, custs) {
        // 与下方「附近列表」共用同一份数据（window._mapCustomers），保证图上标记与列表一致
        if (!custs) custs = window._mapCustomers || customers;
        // 清除旧「我的位置」标记
        if (mobileMyMarker) mobileMap.removeLayer(mobileMyMarker);
        mobileCustomerMarkers.forEach(m => mobileMap.removeLayer(m));
        mobileCustomerMarkers = [];

        // 转 GCJ02 对齐高德底图
        const [mlng, mlat] = wgs84ToGcj02(lon, lat);

        // 我的位置 - 改为黄色
        const myIcon = L.divIcon({
            className: 'my-location-icon',
            html: '<div style="width:20px;height:20px;background:#f1c40f;border:3px solid #fff;border-radius:50%;box-shadow:0 0 8px rgba(241,196,15,0.6);"></div>',
            iconSize: [20, 20], iconAnchor: [10, 10]
        });
        mobileMyMarker = L.marker([mlat, mlng], { icon: myIcon }).addTo(mobileMap);

        mobileMap.setView([mlat, mlng], 12);

        // 按当前筛选绘制客户标记（与下方「附近列表」共用同一套分类/未打卡筛选）
        drawCustomerMarkers(custs, lat, lon);

        // 更新 window 状态并渲染附近列表（带分类筛选）
        window._mapLat = lat;
        window._mapLon = lon;
        renderMapNearbyList();
    }

    // 仅重绘客户标记（不改变地图中心/缩放），供筛选切换时调用，避免整张地图重建闪烁
    function refreshMapMarkers() {
        // 与下方「附近列表」共用同一份数据（window._mapCustomers），保证图上标记与列表一致
        drawCustomerMarkers(window._mapCustomers || customers, window._mapLat || myLat, window._mapLon || myLon);
        renderMapNearbyList();
    }
    window.refreshMapMarkers = refreshMapMarkers;

    // 绘制客户标记：应用与「附近列表」相同的分类/未打卡筛选，不再标全量客户
    function drawCustomerMarkers(custs, lat, lon) {
        // 清除旧客户标记
        mobileCustomerMarkers.forEach(m => mobileMap.removeLayer(m));
        mobileCustomerMarkers = [];

        // 与 renderMapNearbyList 共用同一筛选条件
        var selectedCats = window._mapCats || [];
        var catList = ['核心要客', 'TOP20', '普通客户'];
        var allSelected = selectedCats.length === 0 || selectedCats.length === catList.length;
        var noCheckin = window._mapNoCheckin;

        custs.forEach(c => {
            if (!(c.latitude && c.longitude)) return;
            // 分类筛选：全选或在选中分类内
            var cat = c.category || '普通客户';
            var passCat = allSelected || selectedCats.indexOf(cat) !== -1;
            // 未打卡筛选：开启时只保留「本月打卡=0」的客户
            var isUnchecked = (c.checkin_month == null || c.checkin_month === 0);
            if (!(passCat && (!noCheckin || isUnchecked))) return;

            const dist = calcDistance(lat, lon, c.latitude, c.longitude);
            const colors = {
                '核心要客': { fill: '#e74c3c', border: '#c0392b' },
                'TOP20': { fill: '#3498db', border: '#2980b9' },
                'VIP客户': { fill: '#e74c3c', border: '#c0392b' },
                '重要客户': { fill: '#3498db', border: '#2980b9' },
                '普通客户': { fill: '#95a5a6', border: '#7f8c8d' }
            };
            const color = colors[c.category] || colors['普通客户'];
            const [clng, clat] = wgs84ToGcj02(c.longitude, c.latitude);
            const icon = L.divIcon({
                className: 'customer-icon',
                html: '<div style="width:14px;height:14px;background:' + color.fill + ';border:2px solid ' + color.border + ';border-radius:50%;"></div>',
                iconSize: [14, 14], iconAnchor: [7, 7]
            });
            const marker = L.marker([clat, clng], { icon });
            marker._cid = c.id;
            // 点击标记打开自定义弹窗（不超出地图边界）
            marker.on('click', function() {
                openCustomerPopupWithCheckin(c, clat, clng, dist);
            });
            marker.addTo(mobileMap);
            mobileCustomerMarkers.push(marker);
        });
    }

    function refreshLocationMobile() {
        if (!navigator.geolocation) { showToast('您的浏览器不支持定位功能', 'error'); return; }
        const btn = document.getElementById('mRefreshBtn');
        // 用全局命令统一反馈：点击瞬间锁按钮 + spinner，定位完成自动恢复
        withTapFeedback(btn, function() {
            return new Promise(function(resolve) {
                navigator.geolocation.getCurrentPosition(
                    (pos) => {
                        myLat = pos.coords.latitude;
                        myLon = pos.coords.longitude;
                        updateMobileMap(myLat, myLon);
                        fetch('/api/reverse_geocode?lat=' + myLat.toFixed(6) + '&lon=' + myLon.toFixed(6))
                            .then(r => r.json())
                            .then(d => {
                                document.getElementById('mLocationName').textContent = d.address || (myLat.toFixed(4) + ', ' + myLon.toFixed(4));
                            })
                            .catch(() => {
                                document.getElementById('mLocationName').textContent = myLat.toFixed(4) + ', ' + myLon.toFixed(4);
                            });
                        document.getElementById('mLocationName').textContent = myLat.toFixed(4) + ', ' + myLon.toFixed(4);
                        showToast('已刷新到当前位置', 'success');
                        resolve();
                    },
                    (err) => {
                        let msg = '定位失败';
                        if (err.code === 1) msg = '定位失败: 请允许浏览器获取位置权限';
                        else if (err.code === 2) msg = '定位失败: 无法获取位置信息，请检查GPS/网络';
                        else if (err.code === 3) msg = '定位失败: 定位请求超时，请重试';
                        else msg = '定位失败: ' + (err.message || '未知错误');
                        showToast(msg, 'error');
                        resolve();
                    },
                    { enableHighAccuracy: true, timeout: 10000 }
                );
            });
        }, { spinner: true });
    }

    function focusMobileCustomer(id) {
        const c = customers.find(x => x.id === id);
        if (c && c.latitude && c.longitude && mobileMap) {
            const [clng, clat] = wgs84ToGcj02(c.longitude, c.latitude);
            var lat0 = window._mapLat || 30.358935, lon0 = window._mapLon || 114.323843;
            var dist = calcDistance(lat0, lon0, c.latitude, c.longitude);
            mobileMap.setView([clat, clng], 16);
            openCustomerPopupWithCheckin(c, clat, clng, dist);
            var mp = document.getElementById('mobileMap');
            if (mp) mp.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }

    window.refreshLocationMobile = refreshLocationMobile;
    // 顶栏刷新按钮调用：重新拉取客户数据并重绘地图标记 + 附近列表（不重建地图实例，无闪烁）
    async function refreshMapData() {
        try {
            customers = await api('/api/customers');
            window._mapData = { lat: myLat, lon: myLon, customers: customers, timestamp: Date.now() };
        } catch (e) {}
        updateMobileMap(myLat, myLon, customers);
    }
    window.refreshMapData = refreshMapData;

    window.focusMobileCustomer = focusMobileCustomer;
    window.viewCustomerMobile = viewCustomerMobile;
    window.categoryBadge = categoryBadge;
}

// ==================== 地图附近列表筛选 ====================

window._mapCats = [];
window._mapNoCheckin = false;

function renderMapNearbyList() {
    var backPage = currentPage; // 捕获来源页（地图附近列表只在地图页渲染），保证「公司详情」返回地图而非客户列表
    var custs = window._mapCustomers || [];
    var lat = window._mapLat || 30.358935;
    var lon = window._mapLon || 114.323843;
    var selectedCats = window._mapCats || [];
    var catList = ['核心要客', 'TOP20', '普通客户'];
    var allSelected = selectedCats.length === 0 || selectedCats.length === catList.length;
    var noCheckin = window._mapNoCheckin;

    // 单遍遍历：统计分类总数 + 计算距离筛选附近客户 + 统计未打卡数（合并原 3 趟扫描，减少循环内重复计算）
    var catCount = {};
    var nearby = [];
    var noCheckinCount = 0;
    custs.forEach(function(c) {
        var cat = c.category || '普通客户';
        catCount[cat] = (catCount[cat] || 0) + 1;
        if (c.latitude && c.longitude) {
            c._dist = calcDistance(lat, lon, c.latitude, c.longitude);
            var passCat = allSelected || selectedCats.includes(cat);
            var isUnchecked = (c.checkin_month == null || c.checkin_month === 0);
            if (passCat && isUnchecked) noCheckinCount++;
            if (passCat && (!noCheckin || isUnchecked)) nearby.push(c);
        }
    });
    nearby.sort(function(a, b) { return a._dist - b._dist; });

    document.getElementById('mNearbyCount').textContent = nearby.length;
    document.getElementById('mNearbyInfo').textContent = '';

    // 筛选先
    var chipParts = ['<div style="display:flex;flex-wrap:nowrap;gap:4px;padding:0 0 6px 0;margin-bottom:1px;overflow-x:auto;">'];
    catList.forEach(function(cat) {
        var active = selectedCats.indexOf(cat) !== -1;
        chipParts.push('<span class="m-filter-chip ' + (active ? 'active' : '') + '" style="font-size:10px;padding:2px 6px;"' +
            ' onclick="toggleMapCat(\'' + cat.replace(/'/g, "\\'") + '\')">' + cat + ' (' + (catCount[cat] || 0) + ')</span>');
    });
    chipParts.push('<span class="m-filter-chip ' + (noCheckin ? 'active' : '') + '" style="font-size:10px;padding:2px 6px;"' +
        ' onclick="toggleMapNoCheckin()">未打卡 (' + noCheckinCount + ')</span>');
    chipParts.push('</div>');
    var chipHtml = chipParts.join('');

    var listHtml = nearby.length === 0 ?
        '<div class="m-empty" style="padding:16px 0;"><div class="icon"><i class="m-icon" data-icon="nav"></i></div>附近暂无客户</div>' :
        nearby.map(function(c) {
            var cNames = (c.contact || '').split('||');
            var cPhones = (c.phone || '').split('||');
            var primaryName = cNames[0] || c.name || '';
            var primaryPhone = cPhones[0] || '';
            var cat = c.category || '普通客户';
            var accent = catAccent(cat);
            var checkinText = (c.checkin_month == null || c.checkin_month === 0) ? '未打卡' : ('本月打卡' + c.checkin_month + '次');
            var sub = [cat, checkinText].filter(Boolean).join(' · ');
            var distText = (c._dist != null) ? (c._dist.toFixed(1) + ' km') : '';
            return '<div class="m-group-item" onclick="focusMobileCustomer(' + c.id + ')">' +
                '<div class="m-group-info">' +
                    '<div class="m-group-title" style="display:flex;align-items:center;">' +
                        '<span style="flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(c.company || c.name || '-') + '</span>' +
                        '<span onclick="event.stopPropagation();copyCustomerName(' + c.id + ')" title="复制公司名" style="flex-shrink:0;font-size:13px;line-height:1;color:#007FFF;cursor:pointer;margin-right:8px;">复制</span>' +
                        '<span onclick="event.stopPropagation();navPush(\'cust:' + c.id + '\', function(){switchPage(\'' + backPage + '\')});viewCustomerMobile(' + c.id + ')" style="flex-shrink:0;font-size:13px;line-height:1;color:#007FFF;text-decoration:underline;text-underline-offset:2px;cursor:pointer;margin-left:auto;">公司详情</span>' +
                    '</div>' +
                    '<div class="m-group-subtitle" style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">' +
                        '<span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(sub) + '</span>' +
                        (distText ? '<span style="flex-shrink:0;white-space:nowrap;color:var(--m-text-secondary);font-size:12px;">' + distText + '</span>' : '') +
                    '</div>' +
                '</div>' +
            '</div>';
        }).join('');

    document.getElementById('mNearbyList').innerHTML = chipHtml + listHtml;
    renderIcons(document.getElementById('mNearbyList')); // 嵌套重绘后补图标
}

function toggleMapCat(cat) {
    var current = window._mapCats || [];
    var idx = current.indexOf(cat);
    window._mapCats = idx >= 0 ? current.filter(function(c) { return c !== cat; }) : current.concat([cat]);
    renderMapNearbyList();
    if (window.refreshMapMarkers) window.refreshMapMarkers();
}

function toggleMapNoCheckin() {
    window._mapNoCheckin = !window._mapNoCheckin;
    renderMapNearbyList();
    if (window.refreshMapMarkers) window.refreshMapMarkers();
}

// 复制客户公司名到剪贴板（附近列表公司名旁的按钮调用）
function copyCustomerName(id) {
    var list = window._mapCustomers || (typeof customers !== 'undefined' ? customers : []) || [];
    var c = list.find(function(x) { return x && String(x.id) === String(id); }) || null;
    var name = c ? (c.company || c.name || '') : '';
    if (!name) { showToast('没有可复制的名称', 'error'); return; }
    copyTextToClipboard(name, function(ok) {
        showToast(ok ? ('已复制：' + name) : '复制失败', ok ? 'success' : 'error');
    });
}
function copyTextToClipboard(text, cb) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function() { cb(true); }).catch(function() { cb(fallbackCopyText(text)); });
    } else {
        cb(fallbackCopyText(text));
    }
}
function fallbackCopyText(text) {
    try {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.top = '-9999px';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.focus(); ta.select();
        var ok = document.execCommand('copy');
        document.body.removeChild(ta);
        return ok;
    } catch (e) { return false; }
}

// ==================== 事项看板 ====================

var _allTasksMobile = [];
var _taskSubMap = {};

async function loadTasksMobile() {
    const content = document.getElementById('pageContent');

    // 控件仅构建一次：左侧筛选下拉 + 右侧搜索（并排圆角，与业务/客户页一致）
    if (!document.getElementById('mTaskControls')) {
        content.innerHTML =
            '<div class="m-biz-controls" id="mTaskControls">' +
                '<button type="button" class="m-biz-type-btn" id="mTaskTypeBtn" onclick="toggleTaskTypeMenu()">' +
                    '<span id="mTaskTypeLabel">全部</span>' +
                    '<i class="m-icon m-biz-type-arrow" data-icon="chevronDown"></i>' +
                '</button>' +
                '<div class="m-biz-search">' +
                    '<input type="text" id="mTaskSearch" placeholder="搜索" ' +
                    'oninput="var v=this.value;clearTimeout(window._taskTimer);window._taskTimer=setTimeout(function(){onTaskSearchInput(v)},200)">' +
                '</div>' +
                '<div class="m-biz-type-menu" id="mTaskTypeMenu" style="display:none;">' +
                    '<div class="m-biz-type-item active" data-status="" onclick="selectTaskType(\'\')">全部</div>' +
                    '<div class="m-popup-divider"></div>' +
                    '<div class="m-biz-type-item" data-status="进行中" onclick="selectTaskType(\'进行中\')">进行中</div>' +
                    '<div class="m-popup-divider"></div>' +
                    '<div class="m-biz-type-item" data-status="已完结" onclick="selectTaskType(\'已完结\')">已完结</div>' +
                    '<div class="m-popup-divider"></div>' +
                    '<div class="m-biz-type-item" data-status="已归档" onclick="selectTaskType(\'已归档\')">已归档</div>' +
                '</div>' +
            '</div>' +
            '<div id="mTaskList" style="padding-bottom:72px;"></div>' +
            '<button class="m-fab" onclick="addTaskMobile()" aria-label="新增事项">' + ICONS.add + '</button>';
    }

    // 拉取事项与全部子待办（用于列表内嵌展示）
    var results = await Promise.all([
        api('/api/tasks'),
        api('/api/tasks/subtasks').catch(function() { return []; })
    ]);
    _allTasksMobile = results[0] || [];
    var subs = results[1] || [];
    _taskSubMap = {};
    subs.forEach(function(s) {
        if (!_taskSubMap[s.task_id]) _taskSubMap[s.task_id] = [];
        _taskSubMap[s.task_id].push(s);
    });

    renderTaskList();
}

// 单条事项卡片（与事项看板一致）：标题前置圆点（可一键完成）；下方内嵌子待办（小字、各带圆点、点击快捷已办）。
// subMap: { task_id: [subtask,...] }；editOnclick: 卡片点击行为字符串（看板传 editTaskMobile(id)，详情传 editTaskMobile(id, customerId)）
function renderTaskCard(t, subMap, editOnclick) {
    // 乐观新增的临时事项：不绑定点击/勾选交互，仅展示「同步中…」
    if (t._pending) {
        return '<div class="m-task-item" data-tid="' + t.id + '" data-ttitle="' + esc(t.title || '').replace(/"/g, '&quot;') + '" style="cursor:default;opacity:0.85;">' +
            '<div class="m-task-row">' +
                '<span class="m-task-dot done" style="background:#ff9f0a;"></span>' +
                '<div class="m-task-body"><div class="m-task-title">' + esc(t.title) + ' <span style="color:#ff9f0a;font-size:11px;">同步中…</span></div></div>' +
            '</div></div>';
    }
    var subs = subMap[t.id] || [];
    var taskDone = t.status === '已完结';
    var doneCount = subs.filter(function(s) { return s.done; }).length;
    var subHtml = subs.length === 0 ? '' :
        '<div class="m-task-subs">' + subs.map(function(s) {
            return '<div class="m-task-sub' + (s.done ? ' done' : '') + '">' +
                '<span class="m-dot-sm" onclick="event.stopPropagation();toggleTaskSubtaskQuick(' + t.id + ',' + s.id + ',' + (s.done ? 0 : 1) + ')"></span>' +
                '<span class="m-sub-title">' + esc(s.title) + '</span>' +
            '</div>';
        }).join('') + '</div>';
    var overdue = isOverdue(t.due_date, t.status);
    // 标题下方小字：有子待办显示「已完成 X/Y」，并附截止日期（同字体）
    var meta = '';
    if (subs.length || t.due_date) {
        var metaParts = [];
        if (subs.length) metaParts.push('<span>已完成 ' + doneCount + '/' + subs.length + '</span>');
        if (t.due_date) metaParts.push('<span' + (overdue ? ' style="color:#e74c3c;"' : '') + '>' + formatDate(t.due_date) + '</span>');
        meta = '<div class="m-task-meta">' + metaParts.join('<span class="m-task-meta-sep">·</span>') + '</div>';
    }
    return '<div class="m-task-item' + (t.pinned ? ' pinned' : '') + '" data-tid="' + t.id + '" data-ttitle="' + esc(t.title || '').replace(/"/g,'&quot;') + '" onclick="' + editOnclick + '" style="cursor:pointer;' + (t.status === '已完结' ? 'opacity:0.7;' : '') + '">' +
        '<div class="m-task-row">' +
            '<span class="m-task-dot' + (taskDone ? ' done' : '') + '" onclick="event.stopPropagation();toggleTaskDot(' + t.id + ',' + (taskDone ? 0 : 1) + ')"></span>' +
            '<div class="m-task-body">' +
                '<div class="m-task-title">' + esc(t.title) + '</div>' +
                meta +
            '</div>' +
            (t.pinned ? '<span class="m-pin-tag">置顶</span>' : '') +
        '</div>' +
        subHtml +
    '</div>';
}

function renderTaskList() {
    var list = document.getElementById('mTaskList');
    if (!list) return;
    var filter = window._taskFilter || '';
    var search = (window._taskSearch || '').trim().toLowerCase();

    var tasks = (_allTasksMobile || []).filter(function(t) {
        if (filter) {
            if (t.status !== filter) return false;
        } else {
            // "全部"下不显示已归档事项
            if (t.status === '已归档') return false;
        }
        if (search) {
            var hay = (t.title || '') + ' ' + (t.customer_company || '') + ' ' + (t.customer_name || '');
            if (hay.toLowerCase().indexOf(search) === -1) return false;
        }
        return true;
    });
    // 乐观新增：拼接临时事项（提交成功后由 onSuccess 移除，失败由 rollback 移除）
    (window._pendingCreates || []).forEach(function(p) {
        if (p.src !== 'task') return;
        tasks.push({ id: 'P' + p.tmpId, _pending: true, title: p.title, customer_id: p.customer_id, customer_company: p.customer_company, customer_name: p.customer_name, status: '进行中', created_at: p.created_at || '', pinned: false, description: p.description || '', due_date: p.due_date || '' });
    });
    // 乐观删除：过滤待删除事项
    tasks = tasks.filter(function(t) {
        if (t._pending) return true;
        return !isPendingDelete('task:' + t.id);
    });

    // 按状态分组
    var groups = { '进行中': [], '已完结': [], '已归档': [] };
    tasks.forEach(function(t) { if (groups[t.status]) groups[t.status].push(t); });

    // 组内排序：置顶优先，再按创建时间由近至远
    Object.keys(groups).forEach(function(st) {
        groups[st].sort(function(a, b) {
            var pa = a.pinned ? 1 : 0, pb = b.pinned ? 1 : 0;
            if (pa !== pb) return pb - pa;
            return (b.created_at || '').localeCompare(a.created_at || '');
        });
    });

    // 按公司分组
    function groupByCompany(taskList) {
        var map = {};
        taskList.forEach(function(t) {
            var key = t.customer_id || t.customer_company || 'unknown';
            if (!map[key]) map[key] = { name: t.customer_company || t.customer_name || '未知客户', tasks: [] };
            map[key].tasks.push(t);
        });
        return Object.values(map);
    }

    function companyGroup(cg) {
        var taskCards = cg.tasks.map(function(t, i) {
            var card = renderTaskCard(t, _taskSubMap, 'editTaskMobile(' + t.id + ')');
            if (i < cg.tasks.length - 1) {
                // 事项之间用分割线
                card = card + '<div class="m-task-divider"></div>';
            }
            return card;
        }).join('');
        return '<div style="margin-bottom:14px;">' +
            '<div class="m-group-title" style="display:flex;align-items:center;gap:4px;">' +
                '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#007FFF" stroke-width="2"><ellipse cx="9.5" cy="7.5" rx="3.5" ry="4"/><path d="M1 21v-2a6 6 0 0 1 6-6h5a6 6 0 0 1 6 6v2"/><path d="M17.5 9.5a3 3 0 1 0 0-6"/><path d="M23 21v-1a4.5 4.5 0 0 0-3.5-4.33"/></svg>' +
                esc(cg.name) +
            '</div>' +
            '<div class="m-task-group-mask">' + taskCards + '</div>' +
        '</div>';
    }

    var statusMeta = { '进行中': 'refresh', '已完结': 'done', '已归档': 'archive' };
    // 看板默认展示 进行中 / 已完结；筛选已归档时单独展示已归档看板
    var boardStatuses = filter === '已归档' ? ['已归档'] : ['进行中', '已完结'];
    var parts = [];
    boardStatuses.forEach(function(st) {
        var arr = groups[st];
        if (!arr.length) return;
        var companyGroups = groupByCompany(arr);
        // 公司组排序：置顶组优先 → 再按组内最新事项的创建时间由近至远
        companyGroups.sort(function(a, b) {
            var aPinned = a.tasks.some(function(t) { return t.pinned; });
            var bPinned = b.tasks.some(function(t) { return t.pinned; });
            if (aPinned !== bPinned) return aPinned ? -1 : 1;
            // 组内任务已按 created_at 降序排好，取第一个（最新）比较即可
            var aTime = a.tasks[0] && a.tasks[0].created_at || '';
            var bTime = b.tasks[0] && b.tasks[0].created_at || '';
            return bTime.localeCompare(aTime);
        });
        parts.push('<div class="m-card"><div class="m-card-title"><span><i class="m-icon" data-icon="' + statusMeta[st] + '"></i> ' + st + ' (' + arr.length + ')</span></div>' +
            companyGroups.map(companyGroup).join('') +
        '</div>');
    });
    var html = parts.join('');

    if (!html) {
        html = '<div class="m-empty"><div class="icon"><i class="m-icon" data-icon="note"></i></div>暂无事项</div>';
    }
    list.innerHTML = html;

    // 长按任务卡片 → 弹出「置顶 / 删除」操作面板
    list.querySelectorAll('.m-task-item[data-tid]').forEach(function(el) {
        bindLongPress(el, function() {
            var tid = parseInt(el.getAttribute('data-tid'), 10);
            var ttitle = el.getAttribute('data-ttitle') || '该事项';
            var pinned = el.classList.contains('pinned');
            showTaskActionSheet(tid, ttitle, pinned);
        });
    });
}

// 点击子待办快速切换已办/未办（列表页就地刷新）
async function toggleTaskSubtaskQuick(tid, sid, done) {
    try {
        await api('/api/tasks/' + tid + '/subtasks/' + sid, { method: 'PUT', body: { done: done ? 1 : 0 } });
        if (currentPage === 'tasks') loadTasksMobile();
        else if (window._viewingCustomerId) viewCustomerMobile(window._viewingCustomerId, true);
    } catch(e) {
        showToast('操作失败', 'error');
    }
}

// 点击事项圆点：一键完成/取消完成（级联切换全部子待办，同步「进行中/已完结」状态）
async function toggleTaskDot(tid, done) {
    try {
        await api('/api/tasks/' + tid + '/done', { method: 'POST', body: { done: done ? 1 : 0 } });
        if (currentPage === 'tasks') loadTasksMobile();
        else if (window._viewingCustomerId) viewCustomerMobile(window._viewingCustomerId, true);
    } catch(e) {
        showToast('操作失败', 'error');
    }
}

// 长按任务弹出的操作面板（置顶 / 删除）
function showTaskActionSheet(tid, title, pinned) {
    closeTaskActionSheet();
    var overlay = document.createElement('div');
    overlay.id = 'mTaskSheet';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:2000;background:rgba(0,0,0,0.35);display:flex;align-items:center;justify-content:center;animation:fadeIn 0.15s ease;-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);';
    overlay.addEventListener('click', function(e) { if (e.target === overlay) closeTaskActionSheet(); });
    overlay.innerHTML =
        '<div class="m-popup-card" style="background:var(--m-card);width:80%;max-width:300px;overflow:hidden;animation:fadeIn 0.15s ease;box-shadow:0 12px 40px rgba(0,0,0,0.4);">' +
            '<button class="m-sheet-item" style="padding-top:18px;" onclick="pinTaskMobile(' + tid + ',' + (pinned ? 0 : 1) + ')">' + (pinned ? '取消置顶' : '置顶') + '</button>' +
            '<div class="m-popup-divider"></div>' +
            '<button class="m-sheet-item m-sheet-danger" onclick="confirmDeleteTaskMobile(' + tid + ',\'' + esc(title).replace(/'/g,'') + '\')">删除</button>' +
        '</div>';
    document.body.appendChild(overlay);
}
function closeTaskActionSheet() {
    var el = document.getElementById('mTaskSheet');
    if (el) el.remove();
}
async function pinTaskMobile(tid, pinned) {
    closeTaskActionSheet();
    try {
        await api('/api/tasks/' + tid, { method: 'PUT', body: JSON.stringify({ pinned: pinned }) });
        showToast(pinned ? '已置顶' : '已取消置顶', 'success');
        // 乐观更新本地缓存，避免全量重拉（loadTasksMobile 做两次网络请求较慢）
        if (_allTasksMobile) {
            _allTasksMobile.forEach(function(t) {
                if (t.id === tid) t.pinned = pinned;
            });
        }
        if (currentPage === 'tasks') {
            renderTaskList(); // 只就地重渲染，不请求网络
        } else if (window._viewingCustomerId) {
            viewCustomerMobile(window._viewingCustomerId, true);
        }
    } catch(e) {
        showToast('操作失败: ' + e.message, 'error');
    }
}
function confirmDeleteTaskMobile(tid, title) {
    closeTaskActionSheet();
    deleteTaskMobile(tid, title);
}

// 筛选下拉：展开/收起
function toggleTaskTypeMenu() {
    var menu = document.getElementById('mTaskTypeMenu');
    var btn = document.getElementById('mTaskTypeBtn');
    if (!menu) return;
    var open = (menu.style.display === 'none' || menu.style.display === '');
    var bak = document.getElementById('_mb_backdrop');
    if (bak) { bak.remove(); bak = null; }
    if (open) {
        menu.style.display = 'block';
        menu.style.animation = 'fadeIn 0.15s ease';
        if (btn) btn.classList.add('is-open');
        _showMenuBackdrop(function() {
            menu.style.display = 'none';
            if (btn) btn.classList.remove('is-open');
        });
    } else {
        menu.style.display = 'none';
        if (btn) btn.classList.remove('is-open');
    }
}
// 选择筛选状态
function selectTaskType(status) {
    window._taskFilter = status || '';
    var label = document.getElementById('mTaskTypeLabel');
    if (label) label.textContent = status || '全部';
    document.querySelectorAll('#mTaskTypeMenu .m-biz-type-item').forEach(function(it) {
        it.classList.toggle('active', (it.getAttribute('data-status') || '') === (status || ''));
    });
    var menu = document.getElementById('mTaskTypeMenu');
    if (menu) menu.style.display = 'none';
    var btn = document.getElementById('mTaskTypeBtn');
    if (btn) btn.classList.remove('is-open');
    var _bak3 = document.getElementById('_mb_backdrop');
    if (_bak3) _bak3.remove();
    if (currentPage === 'tasks') renderTaskList();
}
// 搜索
function onTaskSearchInput(v) {
    window._taskSearch = v || '';
    if (currentPage === 'tasks') renderTaskList();
}

// ============ 移动端子待办 ============

// 子待办本地缓存：taskId -> subs[]，用于添加/删除即时（乐观）反馈，避免等待网络
var _subtaskCache = {};
// LRU 顺序（FIFO）：跨长会话打开大量事项时，超上限淘汰最旧 taskId 的缓存，避免内存只增不减
var _subtaskCacheOrder = [];
var _SUBTASK_CACHE_MAX = 50;
function _cacheSubtasks(taskId, subs) {
    _subtaskCache[taskId] = subs;
    var i = _subtaskCacheOrder.indexOf(taskId);
    if (i >= 0) _subtaskCacheOrder.splice(i, 1);
    _subtaskCacheOrder.push(taskId);
    while (_subtaskCacheOrder.length > _SUBTASK_CACHE_MAX) {
        var old = _subtaskCacheOrder.shift();
        if (old !== taskId) delete _subtaskCache[old];
    }
}
// taskId -> { tmpId: true }：乐观新增的行被用户即时删除时标记，后端返回后丢弃
var _cancelledSubAdds = {};

// 生成子待办区块 HTML（用于原地刷新，避免整块销毁重建）
function renderSubtaskSection(taskId, subs) {
    subs = subs || [];
    var doneCount = subs.filter(function(s) { return s.done; }).length;
    var subHtml = subs.length === 0 ? '<div style="font-size:12px;color:var(--m-text-tertiary);margin:8px 0;">暂无子待办</div>' :
        subs.map(function(s) {
            // 将 id 包成 JS 字符串字面量（单引号），兼容乐观新增的临时字符串 id
            var sid = "'" + String(s.id).replace(/'/g, '') + "'";
            return '<div class="m-subtask-row" data-sid="' + s.id + '">' +
                '<span class="m-dot-sm' + (s.done ? ' done' : '') + '" onclick="event.stopPropagation();toggleMobileSubtask(' + taskId + ',' + sid + ',' + (s.done ? 0 : 1) + ')"></span>' +
                '<span class="m-subtask-title' + (s.done ? ' done' : '') + '" ' +
                    'ondblclick="editSubtaskTitle(' + taskId + ',' + sid + ')">' + esc(s.title) + '</span>' +
                '<button type="button" onclick="withTapFeedback(this, function(){ moveMobileSubtask(' + taskId + ',' + sid + ',-1); })" class="m-subtask-move" title="上移">▲</button>' +
                '<button type="button" onclick="withTapFeedback(this, function(){ moveMobileSubtask(' + taskId + ',' + sid + ',1); })" class="m-subtask-move" title="下移">▼</button>' +
                '<span onclick="deleteMobileSubtask(' + taskId + ',' + sid + ')" class="m-subtask-del"><i class="m-icon" data-icon="close"></i></span>' +
                '</div>';
        }).join('');
    return '<div style="font-size:14px;font-weight:600;margin:12px 0 8px;"><i class="m-icon" data-icon="clipboard"></i> 子待办 (' + doneCount + '/' + subs.length + ')</div>' +
        subHtml +
        '<div style="display:flex;gap:6px;margin-top:10px;">' +
            '<input type="text" id="mobileSubtaskInput" class="m-subtask-input" placeholder="添加子待办..."' +
                ' onkeydown="handleSubtaskEnter(event,' + taskId + ')">' +
            '<button onclick="withTapFeedback(this, function(){ return addMobileSubtask(' + taskId + '); })" class="m-subtask-add">添加</button>' +
        '</div>';
}

// 上移/下移子待办：先即时交换 DOM 节点（零等待），再后台静默提交 reorder，避免每次排序卡顿/整块重渲染
function moveMobileSubtask(taskId, subId, dir) {
    var section = document.getElementById('mSubtaskSection');
    if (!section) return;
    var rows = Array.prototype.slice.call(section.querySelectorAll('[data-sid]'));
    // 用字符串严格比较（data-sid 可能是乐观新增的临时串 id，parseInt 会与传入的串 id 不匹配导致失效）
    var idx = rows.findIndex(function(r) { return String(r.getAttribute('data-sid')) === String(subId); });
    if (idx === -1) return;
    var swap = idx + dir;
    if (swap < 0 || swap >= rows.length) return;
    var a = rows[idx], b = rows[swap];
    if (dir < 0) section.insertBefore(a, b);   // 上移：a 插到 b 之前
    else section.insertBefore(b, a);             // 下移：b 插到 a 之前
    // 仅把真实数字 id 提交给后端（临时串 id 不参与排序持久化）
    var ids = Array.prototype.slice.call(section.querySelectorAll('[data-sid]'))
        .map(function(r) { return r.getAttribute('data-sid'); })
        .filter(function(id) { return /^\d+$/.test(String(id)); });
    // 后台保存顺序，不阻塞 UI；失败仅提示，不影响已完成的视觉交换
    api('/api/tasks/' + taskId + '/subtasks/reorder', { method: 'PUT', body: { order: ids } })
        .catch(function() { showToast('排序保存失败', 'error'); });
}

// 原地刷新子待办区块。syncStatus=true 时（仅勾选已办触发）再单独拉取该事项状态同步下拉框，
// 避免每次添加/删除/排序都拉取全部事项列表（/api/tasks），显著提速。
// optimisticSubs 传入时（添加/删除的乐观更新）直接用本地数组重绘，零网络等待，并立即重绘图标。
async function refreshSubtaskSection(taskId, focusInput, syncStatus, optimisticSubs) {
    var section = document.getElementById('mSubtaskSection');
    if (!section) return;
    // 乐观数据优先：立即重绘，无需等待网络（修复「点了过几秒才响应」）
    if (Array.isArray(optimisticSubs)) {
        _cacheSubtasks(taskId, optimisticSubs);
        section.innerHTML = renderSubtaskSection(taskId, optimisticSubs);
        renderIcons(section); // 关键：嵌套重绘后手动补一次图标，否则关闭 ✕ 不渲染
        if (focusInput) { var fi = document.getElementById('mobileSubtaskInput'); if (fi) fi.focus(); }
        return;
    }
    try {
        var subs = await api('/api/tasks/' + taskId + '/subtasks').catch(function() { return []; });
        _cacheSubtasks(taskId, subs);
        section.innerHTML = renderSubtaskSection(taskId, subs);
        renderIcons(section); // 关键：每次重绘后补图标，避免删除键变灰/不可见
        if (syncStatus) {
            // 仅勾选已办会改变事项状态，这里再拉取全部事项并找到本事项同步下拉框
            // （后端无单条 GET 接口，且此分支只在 toggle 时触发，频率低，不影响添加/删除/排序的响应速度）
            var tasks = await api('/api/tasks').catch(function() { return []; });
            var task = (tasks || []).find(function(t) { return t.id === taskId; });
            if (task) {
                var statusSel = document.getElementById('mEditTaskStatus');
                if (statusSel) statusSel.value = task.status;
            }
        }
    } catch (e) {}
    if (focusInput) {
        var input = document.getElementById('mobileSubtaskInput');
        if (input) input.focus();
    }
}

async function addMobileSubtask(taskId) {
    var input = document.getElementById('mobileSubtaskInput');
    var title = (input ? input.value : '').trim();
    if (!title) return;
    if (input) input.value = '';
    // 乐观更新：先用本地缓存插入一行（临时 id）立即重绘，无需等待后端（修复「点了过几秒才响应」）
    var list = (_subtaskCache[taskId] || []).slice();
    var tmpId = 'tmp_' + Date.now() + '_' + Math.floor(Math.random() * 1000);
    list.push({ id: tmpId, title: title, done: false });
    _subtaskCache[taskId] = list;
    await refreshSubtaskSection(taskId, true, false, list);
    // 后台静默提交；成功后用真实 id 替换临时行（静默重绘，不抢焦点）
    api('/api/tasks/' + taskId + '/subtasks', { method: 'POST', body: { title: title } })
        .then(function(res) {
            if (_cancelledSubAdds[taskId] && _cancelledSubAdds[taskId][tmpId]) return; // 用户已即时删除，丢弃
            var real = (res && res.id != null) ? res.id : null;
            var cache = _subtaskCache[taskId] || [];
            for (var k = 0; k < cache.length; k++) {
                if (String(cache[k].id) === String(tmpId)) { if (real != null) cache[k].id = real; break; }
            }
            if (real != null) refreshSubtaskSection(taskId, false, false); // 静默合并真实 id
        })
        .catch(function() {
            showToast('添加失败', 'error');
            _subtaskCache[taskId] = (_subtaskCache[taskId] || []).filter(function(s) { return String(s.id) !== String(tmpId); });
            refreshSubtaskSection(taskId, false, false);
        });
}

// 编辑事项（二级页面）：底部「保存 / 取消」操作栏（不再用顶栏 X/✓）；页面内含事项表单 + 子待办管理
// customerId 存在时（从客户详情进入）返回客户详情页，否则返回事项看板
async function editTaskMobile(taskId, customerId) {
    enterEditPage(function() { saveEditTaskMobile(taskId); });
    if (customerId) {
        navPush('edittask:' + taskId, function() { viewCustomerMobile(customerId); });
    } else {
        navPush('edittask:' + taskId, function() { switchPage('tasks'); });
    }
    var content = document.getElementById('pageContent');

    // 优先命中本地列表缓存，仅在数据缺失时补拉（与业务 viewBusinessMobile 对齐：列表已加载则零/少网络）
    var subsFromGlobal = window._allSubtasksMobile;
    var subsPromise = subsFromGlobal
        ? Promise.resolve(subsFromGlobal.filter(function(s) { return String(s.task_id) === String(taskId); }))
        : api('/api/tasks/' + taskId + '/subtasks').then(function(s) { return s || []; }).catch(function() { return []; });

    var tasksArr = window._allTasksMobile;
    var task, subs;
    if (tasksArr && tasksArr.length) {
        // 事项列表已加载全量：直接 find，跳过 GET /api/tasks 重拉
        task = tasksArr.find(function(t) { return t.id === taskId; });
        subs = await subsPromise;
    } else {
        // 缓存缺失：补拉全量 tasks + 该任务 subtasks
        var results = await Promise.all([ api('/api/tasks'), subsPromise ]);
        tasksArr = results[0] || [];
        window._allTasksMobile = tasksArr;
        task = tasksArr.find(function(t) { return t.id === taskId; });
        subs = results[1] || [];
    }
    if (!task) { showToast('事项不存在', 'error'); return; }

    document.getElementById('pageTitle').textContent = '编辑事项';
    // 单卡片内：事项字段 + 子待办区 + 底部取消/保存（与其他编辑页一致，按钮在控件内）
    content.innerHTML =
        '<div class="m-card">' +
            '<div style="font-size:13px;color:#888;margin-bottom:12px;"><i class="m-icon" data-icon="building"></i> ' + (task.customer_company || task.customer_name || '未知公司') + '</div>' +
            '<div class="form-group"><label>事项标题</label><input type="text" class="form-control" id="mEditTaskTitle" value="' + (task.title || '').replace(/"/g,'&quot;') + '"></div>' +
            '<div class="form-group"><label>详细描述</label><textarea class="form-control" id="mEditTaskDesc" rows="3">' + (task.description || '').replace(/"/g,'&quot;') + '</textarea></div>' +
            '<div class="form-group"><label>截止日期</label><input type="date" class="form-control" id="mEditTaskDueDate" value="' + (task.due_date ? task.due_date.substring(0,10) : '') + '"></div>' +
            '<div id="mSubtaskSection">' + renderSubtaskSection(taskId, subs) + '</div>' +
            editActionBarHtml() +
        '</div>';
}

async function saveEditTaskMobile(taskId) {
    var data = {
        title: document.getElementById('mEditTaskTitle').value.trim(),
        description: document.getElementById('mEditTaskDesc').value.trim(),
        due_date: document.getElementById('mEditTaskDueDate').value
    };
    if (!data.title) { showToast('标题不能为空', 'error'); return; }
    var old = _allTasksMobile.find(function(t) { return t.id === taskId; });
    var bak = old ? JSON.parse(JSON.stringify(old)) : null;
    optimisticWrite({
        applyLocal: function() {
            if (old) {
                old.title = data.title; old.description = data.description; old.due_date = data.due_date;
            }
            navBack(); // 返回列表（从缓存即时重绘）
        },
        submit: async function() { await api('/api/tasks/' + taskId, { method: 'PUT', body: JSON.stringify(data) }); },
        onSuccess: function() {
            _pageDirty['tasks'] = true;
            showToast('已更新', 'success');
        },
        rollback: function(err) {
            if (bak && old) {
                old.title = bak.title; old.description = bak.description; old.due_date = bak.due_date;
            }
            showToast('保存失败: ' + (err && err.message ? err.message : err), 'error');
            rerenderVisibleAfterMutation();
        }
    });
}

async function toggleMobileSubtask(taskId, subId, done) {
    // 乐观新增的临时行：仅本地翻转 done 并重绘，不请求后端
    if (String(subId).indexOf('tmp_') === 0) {
        var c = _subtaskCache[taskId] || [];
        var hit = c.find(function(x) { return String(x.id) === String(subId); });
        if (hit) hit.done = !!done;
        refreshSubtaskSection(taskId, false, false, c);
        return;
    }
    try {
        await api('/api/tasks/' + taskId + '/subtasks/' + subId, { method: 'PUT', body: { done: done ? 1 : 0 } });
        // 原地刷新子待办区块与状态（勾选已办会改变事项状态，需同步下拉框）
        await refreshSubtaskSection(taskId, false, true);
    } catch(e) {}
}

// 双击子待办标题 → 内联编辑
function editSubtaskTitle(taskId, subId) {
    var section = document.getElementById('mSubtaskSection');
    if (!section) return;
    var row = section.querySelector('[data-sid="' + subId + '"]');
    if (!row) return;
    var titleEl = row.querySelector('.m-subtask-title');
    if (!titleEl) return;
    var oldTitle = titleEl.textContent || '';
    // 替换为输入框
    titleEl.innerHTML = '<input type="text" class="m-subtask-edit-input" value="' + esc(oldTitle).replace(/"/g,'&quot;') + '" style="width:100%;box-sizing:border-box;background:transparent;border:1px solid var(--m-border,#333);border-radius:6px;padding:2px 6px;font-size:inherit;color:inherit;outline:none;">';
    var input = titleEl.querySelector('input');
    if (!input) return;
    titleEl.className = (titleEl.className || '') + ' editing';
    input.focus();
    input.select();
    function save() {
        var val = input.value.trim();
        if (!val || val === oldTitle) { restore(); return; }
        var cache = _subtaskCache[taskId] || [];
        var hit = cache.find(function(s) { return String(s.id) === String(subId); });
        if (hit) hit.title = val;
        titleEl.textContent = val;
        titleEl.className = titleEl.className.replace(' editing', '');
        if (String(subId).indexOf('tmp_') !== 0) {
            api('/api/tasks/' + taskId + '/subtasks/' + subId, { method: 'PUT', body: { title: val } })
                .catch(function() { showToast('更新失败', 'error'); });
        }
    }
    function restore() {
        titleEl.textContent = oldTitle;
        titleEl.className = titleEl.className.replace(' editing', '');
    }
    input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') { e.preventDefault(); save(); }
        else if (e.key === 'Escape') { e.preventDefault(); restore(); }
    });
    input.addEventListener('blur', function() { save(); });
}

// 子待办输入框回车
function handleSubtaskEnter(event, taskId) {
    if (event.key === 'Enter') addMobileSubtask(taskId);
}

function deleteMobileSubtask(taskId, subId) {
    // 乐观更新：立即从本地缓存移除并重绘，无需等待网络（修复「点了过几秒才响应」）
    if (_subtaskCache[taskId]) {
        // 若删除的是尚未入库的乐观新增行，标记取消，后端返回后丢弃
        if (String(subId).indexOf('tmp_') === 0) {
            if (!_cancelledSubAdds[taskId]) _cancelledSubAdds[taskId] = {};
            _cancelledSubAdds[taskId][subId] = true;
        }
        _subtaskCache[taskId] = _subtaskCache[taskId].filter(function(s) { return String(s.id) !== String(subId); });
        refreshSubtaskSection(taskId, false, false, _subtaskCache[taskId]);
        // 仅真实 id 才请求后端删除；乐观临时行无需请求
        if (String(subId).indexOf('tmp_') !== 0) {
            api('/api/tasks/' + taskId + '/subtasks/' + subId, { method: 'DELETE' })
                .catch(function() { showToast('删除失败', 'error'); refreshSubtaskSection(taskId, false, false); });
        }
        return;
    }
    // 兜底：无缓存时直接移除 DOM 并请求后端
    var section = document.getElementById('mSubtaskSection');
    if (section) { var row = section.querySelector('[data-sid="' + subId + '"]'); if (row) row.remove(); }
    api('/api/tasks/' + taskId + '/subtasks/' + subId, { method: 'DELETE' })
        .catch(function() { showToast('删除失败', 'error'); refreshSubtaskSection(taskId, false, false); });
}

// ==================== 移动端事项新增 / 编辑 ====================

function addTaskMobile(customerId, customerName) {
    // 进入编辑页（新增事项）：底部「取消 / 保存」操作栏（不再用顶栏 X/✓）
    enterEditPage(saveTaskMobile);
    window._newTaskSubs = [];

    if (customerId) {
        navPush('addtask:' + (customerId || 'tasks'), function() { viewCustomerMobile(customerId); });
    } else {
        navPush('addtask:' + (customerId || 'tasks'), function() { switchPage('tasks'); });
    }
    var content = document.getElementById('pageContent');
    document.getElementById('pageTitle').textContent = '新增事项';
    content.innerHTML =
        '<div class="m-card">' +
            '' +
            '<div class="form-group"><label>关联客户 *</label>' +
                '<input type="text" class="form-control" id="mTaskCustSearch" placeholder="搜索" style="font-size:13px;" oninput="filterTaskCustomers(this.value)" autocomplete="off">' +
                '<input type="hidden" id="mTaskCustomerId" value="">' +
                '<div id="mTaskCustList" class="m-popup-card" style="max-height:240px;overflow-y:auto;border:1px solid var(--m-border);box-shadow:0 12px 40px rgba(0,0,0,0.15);background:var(--m-card);margin-top:6px;display:none;"></div></div>' +
            '<div style="font-size:12px;color:#888;margin-bottom:8px;" id="mTaskCustLabel">请搜索并选择客户</div>' +
            '<div class="form-group"><label>事项标题 *</label><input type="text" class="form-control" id="mTaskTitle" placeholder="请输入事项标题"></div>' +
            '<div class="form-group"><label>详细描述</label><textarea class="form-control" id="mTaskDesc" rows="3"></textarea></div>' +
            '<div class="form-group"><label>截止日期</label><input type="date" class="form-control" id="mTaskDueDate"></div>' +
            '<div id="mNewSubtaskSection"></div>' +
            editActionBarHtml() +
        '</div>';
    renderNewSubtaskSection();

    // 加载客户列表
    window._allTaskCustomers = [];
    api('/api/customers').then(function(customers) {
        window._allTaskCustomers = customers;
        // 如果从客户详情页调用，客户列表加载完后预填
        if (customerId && customerName) {
            var input = document.getElementById('mTaskCustSearch');
            var hidden = document.getElementById('mTaskCustomerId');
            var label = document.getElementById('mTaskCustLabel');
            if (input && hidden && label) {
                input.value = customerName;
                hidden.value = customerId;
                label.innerHTML = '当前: ' + customerName;
                if (typeof filterTaskCustomers === 'function') {
                    filterTaskCustomers(customerName);
                }
            }
        }
    });
}

// 客户搜索过滤 - 输入时显示匹配列表
function filterTaskCustomers(keyword) {
    var kw = (keyword || '').trim().toLowerCase();
    var customers = window._allTaskCustomers || [];
    var listEl = document.getElementById('mTaskCustList');
    var labelEl = document.getElementById('mTaskCustLabel');
    if (!listEl || !labelEl) return;

    if (!kw) {
        listEl.style.display = 'none';
        labelEl.textContent = '请搜索并选择客户';
        return;
    }

    var filtered = customers.filter(function(c) {
        return (c.company || c.name || '').toLowerCase().includes(kw);
    });

    if (filtered.length === 0) {
        listEl.innerHTML = custCreateRowHtml({ searchInputId: 'mTaskCustSearch', hiddenId: 'mTaskCustomerId', labelId: 'mTaskCustLabel', listId: 'mTaskCustList', onType: '', kw: keyword });
        listEl.style.display = 'block';
        return;
    }

    listEl.innerHTML = filtered.map(function(c, i) {
        return '<div class="m-cust-option" data-id="' + c.id + '" data-name="' + (c.company || c.name || '').replace(/"/g,'&quot;') + '"' +
            ' style="padding:10px 12px;cursor:pointer;border-bottom:' + (i < filtered.length - 1 ? '1px solid #f0f0f0' : 'none') + ';font-size:14px;"' +
            ' onmouseover="this.style.background=\'#f0f4ff\'" onmouseout="this.style.background=\'\'"' +
            ' onclick="selectTaskCustomer(' + c.id + ',\'' + (c.company || c.name || '').replace(/'/g,'') + '\')">' +
            '<strong>' + (c.company || c.name || '-') + '</strong>' +
            '<span style="float:right;color:#888;font-size:12px;">' + (c.category || '') + '</span>' +
            '</div>';
    }).join('');
    listEl.style.display = 'block';
}

// 选择客户
function selectTaskCustomer(id, name) {
    document.getElementById('mTaskCustSearch').value = name;
    document.getElementById('mTaskCustomerId').value = id;
    document.getElementById('mTaskCustList').style.display = 'none';
    document.getElementById('mTaskCustLabel').innerHTML = '<i class="m-icon" data-icon="done"></i> 已选择: <strong>' + name + '</strong>';
}

async function saveTaskMobile() {
    // 若关联客户是乐观新建（尚未落库），先等其实 id 就绪，避免下游用幻影 id 提交
    if (window._pendingCustomerCreate) {
        try { await window._pendingCustomerCreate; } catch (e) { showToast('客户新建失败', 'error'); return; }
    }
    var customerId = document.getElementById('mTaskCustomerId').value;
    var title = document.getElementById('mTaskTitle').value.trim();
    if (!customerId || !title) { showToast('请选择客户并填写标题', 'error'); return; }

    var data = {
        customer_id: parseInt(customerId),
        title: title,
        description: document.getElementById('mTaskDesc').value.trim(),
        due_date: document.getElementById('mTaskDueDate').value
    };
    var cid = parseInt(customerId);
    var cname = document.getElementById('mTaskCustSearch').value.trim();
    // 乐观新增：临时事项入 _pendingCreates，立即返回列表（秒回），后台逐条提交，失败回滚
    var tmpId = 'tmp_task_' + Date.now() + '_' + Math.floor(Math.random() * 1e4);
    optimisticWrite({
        applyLocal: function() {
            window._pendingCreates.push({ tmpId: tmpId, src: 'task', customer_id: cid,
                title: title, customer_company: cname, customer_name: cname,
                description: data.description, due_date: data.due_date, _pending: true });
            navBack(); // 立即返回列表（秒回），临时事项已在返回页渲染
        },
        submit: async function() {
            var res = await api('/api/tasks', { method: 'POST', body: JSON.stringify(data) });
            var newId = res && res.id;
            // 依次创建暂存子待办（保持顺序）
            var subs = window._newTaskSubs || [];
            for (var i = 0; i < subs.length; i++) {
                await api('/api/tasks/' + newId + '/subtasks', { method: 'POST', body: { title: subs[i].title } });
            }
            window._newTaskSubs = [];
        },
        onSuccess: function() {
            removePending(tmpId);
            showToast('已新增', 'success');
            refetchVisibleAfterCreate(); // 真实事项已落库，重拉展示
        },
        rollback: function(err) {
            removePending(tmpId);
            showToast('保存失败: ' + (err && err.message ? err.message : err), 'error');
            rerenderVisibleAfterMutation();
        }
    });
}

// ==================== 新增事项页：子待办暂存模块（与编辑页一致） ====================
function renderNewSubtaskSection() {
    var sec = document.getElementById('mNewSubtaskSection');
    if (!sec) return;
    window._newTaskSubs = window._newTaskSubs || [];
    var subs = window._newTaskSubs;
    var subHtml = subs.length === 0 ? '<div style="font-size:12px;color:var(--m-text-tertiary);margin:8px 0;">暂无子待办</div>' :
        subs.map(function(s) {
            return '<div class="m-subtask-row" data-nid="' + s._id + '">' +
                '<span class="m-dot-sm"></span>' +
                '<span class="m-subtask-title">' + esc(s.title) + '</span>' +
                '<button type="button" onclick="moveNewSubtask(' + s._id + ',-1)" class="m-subtask-move" title="上移">▲</button>' +
                '<button type="button" onclick="moveNewSubtask(' + s._id + ',1)" class="m-subtask-move" title="下移">▼</button>' +
                '<span onclick="deleteNewSubtask(' + s._id + ')" class="m-subtask-del"><i class="m-icon" data-icon="close"></i></span>' +
                '</div>';
        }).join('');
    sec.innerHTML = '<div style="font-size:14px;font-weight:600;margin:12px 0 8px;"><i class="m-icon" data-icon="clipboard"></i> 子待办 (' + subs.length + ')</div>' +
        subHtml +
        '<div style="display:flex;gap:6px;margin-top:10px;">' +
            '<input type="text" id="mNewSubtaskInput" class="m-subtask-input" placeholder="添加子待办..." onkeydown="if(event.key===\'Enter\')addNewSubtask()">' +
            '<button onclick="addNewSubtask()" class="m-subtask-add">添加</button>' +
        '</div>';
    renderIcons(sec); // 关键：嵌套重绘后手动补图标，否则关闭 ✕ 不渲染
}

function addNewSubtask() {
    var input = document.getElementById('mNewSubtaskInput');
    var title = (input ? input.value : '').trim();
    if (!title) return;
    window._newTaskSubs = window._newTaskSubs || [];
    window._newTaskSubs.push({ _id: Date.now() + Math.floor(Math.random() * 1000), title: title });
    renderNewSubtaskSection();
    if (input) input.value = '';
}

function moveNewSubtask(nid, dir) {
    var subs = window._newTaskSubs || [];
    var idx = subs.findIndex(function(s) { return s._id === nid; });
    if (idx === -1) return;
    var swap = idx + dir;
    if (swap < 0 || swap >= subs.length) return;
    var tmp = subs[idx]; subs[idx] = subs[swap]; subs[swap] = tmp;
    renderNewSubtaskSection();
}

function deleteNewSubtask(nid) {
    window._newTaskSubs = (window._newTaskSubs || []).filter(function(s) { return s._id !== nid; });
    renderNewSubtaskSection();
}

// ==================== 报告 ====================

async function loadReportMobile() {
    const reports = await api('/api/reports');
    const content = document.getElementById('pageContent');

    content.innerHTML = `
        <div class="m-card">
            <button class="btn btn-primary" style="width:100%;padding:14px;font-size:16px;" onclick="generateReportMobile()">
                <i class="m-icon" data-icon="bolt"></i> 立即生成今日报告
            </button>
        </div>

        <div class="m-card">
            <div class="m-card-title"><span><i class="m-icon" data-icon="folder"></i> 历史报告</span></div>
            ${reports.length === 0 ? '<div class="m-empty"><div class="icon"><i class="m-icon" data-icon="empty"></i></div>暂无报告</div>' :
                reports.map(r => `
                    <div class="m-report-item">
                        <div>
                            <div class="filename"><i class="m-icon" data-icon="report"></i> ${r.filename.replace('daily_report_','').replace('.html','')}</div>
                            <div class="meta"><i class="m-icon" data-icon="cal"></i> ${r.created} · ${r.size}</div>
                        </div>
                        <a href="${r.url}" target="_blank" class="btn btn-primary btn-sm">查看</a>
                    </div>
                `).join('')}
        </div>
    `;
}

async function generateReportMobile() {
    try {
        showToast('正在生成报告...');
        const data = await api('/api/report/generate', { method: 'POST' });
        showToast('报告已生成！', 'success');
        loadReportMobile();
        setTimeout(() => window.open(data.url, '_blank'), 500);
    } catch (e) {
        showToast('生成失败: ' + e.message, 'error');
    }
}

// ==================== 打卡 ====================

async function doCheckinMobile(cid) {
    try {
        var resp = await fetch('/api/customers/' + cid + '/checkin', { method: 'POST' });
        var d = await resp.json();
        var el = document.getElementById('ci_' + cid);
        if (el) el.textContent = d.count;
        // 实时同步到附近列表：更新内存中该客户的打卡数并重绘附近列表，无需等手动刷新
        if (window._mapCustomers && currentPage === 'map') {
            var _c = window._mapCustomers.find(function(c) { return c.id === cid; });
            if (_c) _c.checkin_month = d.count;
            renderMapNearbyList();
        }
        showToast('已打卡（本月 ' + d.count + ' 次）', 'success');
    } catch(e) {
        showToast('打卡失败: ' + e.message, 'error');
    }
}

// 打卡确认弹窗：与首页长按弹窗一致的卡片 + 毛玻璃遮罩样式
function showCheckinConfirmMobile(cid) {
    var ex = document.getElementById('mCheckinConfirmOverlay');
    if (ex) ex.remove();  // 兜底：移除残留遮罩，避免双层叠加
    var overlay = document.createElement('div');
    overlay.id = 'mCheckinConfirmOverlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:2000;background:rgba(0,0,0,0.35);display:flex;align-items:center;justify-content:center;animation:fadeIn .15s ease;-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);';
    overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });
    overlay.innerHTML =
        '<div class="m-popup-card" style="background:var(--m-card,#1c1c1e);color:var(--m-text,#fff);width:80%;max-width:300px;overflow:hidden;animation:fadeIn .15s ease;box-shadow:0 12px 40px rgba(0,0,0,0.4);">' +
            '<div style="padding:20px 20px 20px;font-size:14px;color:var(--m-text-secondary,#aaa);line-height:1.5;text-align:center;">确定给该客户打卡？</div>' +
            '<div class="m-popup-divider"></div>' +
            '<button onclick="(function(){var o=document.getElementById(\'mCheckinConfirmOverlay\');if(o)o.remove();})()" style="width:100%;padding:14px;border:none;background:transparent;color:var(--m-text-secondary,#aaa);font-size:15px;cursor:pointer;">取消</button>' +
            '<div class="m-popup-divider"></div>' +
            '<button onclick="(function(){var o=document.getElementById(\'mCheckinConfirmOverlay\');if(o)o.remove();if(window.__mCheckinCb)window.__mCheckinCb();})()" style="width:100%;padding:14px;border:none;background:transparent;color:var(--m-accent,#0a84ff);font-size:15px;font-weight:600;cursor:pointer;">打卡</button>' +
        '</div>';
    window.__mCheckinCb = function() { doCheckinMobile(cid); };
    document.body.appendChild(overlay);
}

function editCheckinMobile(cid) {
    var el = document.getElementById('ci_' + cid);
    var current = parseInt(el ? el.textContent : '0');
    var newVal = prompt('编辑当月打卡次数', current);
    if (newVal === null || newVal === '') return;
    var count = parseInt(newVal);
    if (isNaN(count) || count < 0) { showToast('请输入有效数字', 'error'); return; }
    fetch('/api/customers/' + cid + '/checkin', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ count: count })
    })
    .then(function(r) { return r.json(); })
    .then(function(d) {
        if (el) el.textContent = d.count;
        // 实时同步到附近列表
        if (window._mapCustomers && currentPage === 'map') {
            var _c = window._mapCustomers.find(function(c) { return c.id === cid; });
            if (_c) _c.checkin_month = d.count;
            renderMapNearbyList();
        }
        showToast('已更新为 ' + d.count + ' 次', 'success');
    })
    .catch(function(e) { showToast('更新失败', 'error'); });
}

window.doCheckinMobile = doCheckinMobile;
window.editCheckinMobile = editCheckinMobile;
window.showCheckinConfirmMobile = showCheckinConfirmMobile;

// ==================== 浏览器返回拦截 ====================
// 监听手机物理返回键/左滑返回 → 统一在 popstate 内处理（应用内返回 / 关弹窗 / 退出确认）
// 关键：所有返回路径（手势与按钮）最终都只走这里，保证“一次返回 = 弹出一个导航栈 = 消费一个历史状态”。
(function() {
    // 初始推一个历史状态，确保首个返回即可被拦截（此状态不计入导航栈）
    try { history.pushState({ sub: false }, '', window.location.href); } catch (e) {}

    function _topOpenOverlay() {
        // 当前打开、可由手势返回关闭的弹窗；排除退出确认框（由退出流程自行处理）
        if (document.getElementById('qModalOverlay')) return document.getElementById('qModalOverlay');
        var mo = document.querySelector('.modal-overlay.show');
        if (mo) return mo;
        var list = document.querySelectorAll('div[style*="z-index: 2000"], div[style*="z-index:2000"], div[style*="z-index: 1050"], div[style*="z-index:1050"]');
        return Array.from(list).find(function(el) {
            if (el.id === 'mExitOverlay') return false; // 退出确认不在此关闭
            return el.style.display !== 'none' && getComputedStyle(el).display !== 'none';
        }) || null;
    }

    function _closeOverlay(ov) {
        if (ov.id === 'qModalOverlay' && typeof closeQuadrantModal === 'function') { closeQuadrantModal(); return; }
        if (ov.classList && ov.classList.contains('modal-overlay')) { ov.classList.remove('show'); return; }
        // 通用遮罩：触发其自身点击关闭处理器；无处理器则直接移除
        try { ov.click(); } catch (e) { ov.remove(); }
    }

    window.addEventListener('popstate', function(e) {
            // 1) 弹窗优先关闭（不导航）；手势已消费一个历史状态，补推一个以保持导航栈平衡
            var ov = _topOpenOverlay();
            if (ov) {
                _closeOverlay(ov);
                try { history.pushState({ sub: false }, '', window.location.href); } catch (e) {}
                return;
            }
            // 2) 导航栈有记录 → 应用内返回（弹出一个条目，消费一个历史状态）
            if (_navStack.length > 0) {
                var item = _navStack.pop();
                _runReturn(item);
                // 消费一个历史状态后，若仍停留在二级页（栈非空），补推一个基础状态，
                // 维持「1 次返回 = 弹出 1 个栈 = 消费 1 个历史状态」的平衡，避免游离状态累积
                if (_navStack.length > 0) {
                    try { history.pushState({ sub: false }, '', window.location.href); } catch (e) {}
                }
                return;
            }
            // 3) 一级页面：系统/手势返回 → APK 回桌面 / 浏览器退页
            if (TOP_LEVEL_PAGES.indexOf(currentPage) !== -1) {
                topLevelSystemBack();
                return;
            }
            // 4) 兜底：其它情况回退到最近访问的一级页面
            switchPage(_prevTopPage);
    });
})();

// ==================== 一级页面系统/手势返回 ====================
// APK 端：返回桌面（原生 moveTaskToBack）；浏览器端：退出网页（window.close 尽力）。
function topLevelSystemBack() {
    // APK（注入了 CustomerApp.goHome 桥）：返回桌面
    try {
        if (window.CustomerApp && typeof window.CustomerApp.goHome === 'function') {
            window.CustomerApp.goHome();
            return;
        }
    } catch (e) {}
    // 浏览器端：尽力关闭网页（仅当本页由脚本 window.open 打开时有效；否则交由浏览器原生返回退出）
    try { window.close(); } catch (e) {}
}

// ==================== 移动端设置页 ====================

function applyTheme() {
    var t = '';
    try { t = localStorage.getItem('mTheme') || ''; } catch (e) {}
    var el = document.documentElement;
    if (t === 'light' || t === 'dark') el.setAttribute('data-theme', t);
    else el.removeAttribute('data-theme');
}

function setTheme(t) {
    try {
        if (t) localStorage.setItem('mTheme', t);
        else localStorage.removeItem('mTheme');
    } catch (e) {}
    applyTheme();
    syncThemeSeg();
}

function syncThemeSeg() {
    var cur = '';
    try { cur = localStorage.getItem('mTheme') || ''; } catch (e) {}
    var btns = document.querySelectorAll('#mThemeSeg .m-theme-opt');
    for (var i = 0; i < btns.length; i++) {
        btns[i].classList.toggle('is-active', btns[i].getAttribute('data-t') === cur);
    }
}

async function loadSettingsMobile() {
    // 加载用户信息
    let userInfo = {};
    try {
        const resp = await fetch('/api/me');
        if (resp.ok) userInfo = await resp.json();
    } catch(e) {}

    let settings = {};
    try { settings = await api('/api/settings'); } catch(e) {}

    const content = document.getElementById('pageContent');
    const phone = (userInfo.user && userInfo.user.phone) || '—';
    const isAdmin = userInfo.user && userInfo.user.is_admin;
    window.__currentPhone = (phone !== '—') ? phone : '';

    content.innerHTML = `
        <div class="m-card">
            <div class="m-card-title">账号设置</div>
            <p style="color:#999;font-size:12px;margin-bottom:10px;">仅你本人可见，客户资料彼此隔离</p>
            <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;">
                <span style="color:#888;font-size:13px;">手机号</span>
                <span style="display:flex;align-items:center;gap:12px;">
                    <span style="font-weight:600;font-size:15px;">${phone}</span>
                    <span onclick="openChangePhone()" style="color:var(--m-accent,#0a84ff);font-size:14px;cursor:pointer;-webkit-tap-highlight-color:transparent;">更改</span>
                </span>
            </div>
            <div style="margin-top:14px;">
                <div style="font-size:15px;font-weight:600;margin-bottom:12px;">修改密码</div>
                <div class="form-group"><label>当前密码</label><div style="position:relative;display:flex;align-items:center;"><input type="password" class="form-control" id="mOldPwd" placeholder="输入当前密码" style="padding-right:44px;"><button type="button" onclick="togglePwdMobile('mOldPwd',this)" style="position:absolute;right:10px;top:50%;transform:translateY(-50%);background:none;border:none;color:var(--m-text-secondary);cursor:pointer;display:flex;align-items:center;padding:0;"><i class="m-icon" data-icon="eye"></i></button></div></div>
                <div class="form-group"><label>新密码（至少 6 位）</label><div style="position:relative;display:flex;align-items:center;"><input type="password" class="form-control" id="mNewPwd" placeholder="输入新密码" style="padding-right:44px;"><button type="button" onclick="togglePwdMobile('mNewPwd',this)" style="position:absolute;right:10px;top:50%;transform:translateY(-50%);background:none;border:none;color:var(--m-text-secondary);cursor:pointer;display:flex;align-items:center;padding:0;"><i class="m-icon" data-icon="eye"></i></button></div></div>
                <div class="form-group"><label>确认新密码</label><div style="position:relative;display:flex;align-items:center;"><input type="password" class="form-control" id="mConfirmPwd" placeholder="再次输入新密码" style="padding-right:44px;"><button type="button" onclick="togglePwdMobile('mConfirmPwd',this)" style="position:absolute;right:10px;top:50%;transform:translateY(-50%);background:none;border:none;color:var(--m-text-secondary);cursor:pointer;display:flex;align-items:center;padding:0;"><i class="m-icon" data-icon="eye"></i></button></div></div>
                <div style="text-align:center;"><button class="btn btn-primary" style="width:50%;padding:12px;" onclick="changePasswordMobile()">保存修改</button></div>
                <div id="mPwdMsg" style="font-size:13px;margin-top:8px;min-height:20px;"></div>
            </div>
        </div>

        <div class="m-card">
            <div class="m-card-title">外观</div>
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <span style="font-size:14px;">深色模式</span>
                <div style="display:flex;gap:6px;" id="mThemeSeg">
                    <button class="m-theme-opt" data-t="light" onclick="setTheme('light')">浅色</button>
                    <button class="m-theme-opt" data-t="dark" onclick="setTheme('dark')">深色</button>
                    <button class="m-theme-opt" data-t="" onclick="setTheme('')">跟随系统</button>
                </div>
            </div>
        </div>

        ${isAdmin ? `
        <div class="m-card" id="mAdminPanel">
            <div class="m-card-title">注册审核 <span id="mPendingCount" style="background:#007FFF;color:#fff;border-radius:10px;padding:2px 8px;font-size:12px;">0</span></div>
            <div id="mPendingList"><div style="text-align:center;color:#999;font-size:13px;padding:8px;">加载中...</div></div>
            <div id="mAdminMsg" style="font-size:13px;margin-top:6px;min-height:20px;"></div>
        </div>
        <div class="m-card">
            <div class="m-card-title">密码重置审核 <span id="mResetCount" style="background:#007FFF;color:#fff;border-radius:10px;padding:2px 8px;font-size:12px;">0</span></div>
            <div id="mResetList"><div style="text-align:center;color:#999;font-size:13px;padding:8px;">加载中...</div></div>
            <div id="mResetMsg" style="font-size:13px;margin-top:6px;min-height:20px;"></div>
        </div>
        ` : ''}

        <div style="text-align:center;margin:8px 0 12px;">
            <button type="button" style="background:none;border:none;box-shadow:none;color:var(--m-accent);font-size:15px;font-weight:600;padding:12px;cursor:pointer;-webkit-tap-highlight-color:transparent;" onclick="window.location.href='/logout'">退出登录</button>
        </div>
        <div style="height:20px;"></div>
    `;

    syncThemeSeg();
    if (typeof renderIcons === 'function') renderIcons(content);  // 保证账号卡内图标正常渲染

    if (isAdmin) { loadPendingMobile(); loadResetsMobile(); }
}

async function saveSettingsMobile() {
    const data = {
        my_location_name: document.getElementById('mSetLocationName').value,
        my_latitude: document.getElementById('mSetLat').value,
        my_longitude: document.getElementById('mSetLng').value,
        default_radius_km: document.getElementById('mSetRadius').value
    };
    quickSave(api('/api/settings', { method: 'PUT', body: data }), { successMsg: '设置已保存', errorMsg: '保存失败' });
}

async function changePasswordMobile() {
    const oldPwd = document.getElementById('mOldPwd').value;
    const newPwd = document.getElementById('mNewPwd').value;
    const confirmPwd = document.getElementById('mConfirmPwd').value;
    const msgEl = document.getElementById('mPwdMsg');
    if (!oldPwd) { msgEl.innerHTML = '<span style="color:#c0392b;">请输入当前密码</span>'; return; }
    if (newPwd.length < 6) { msgEl.innerHTML = '<span style="color:#c0392b;">新密码至少 6 位</span>'; return; }
    if (newPwd !== confirmPwd) { msgEl.innerHTML = '<span style="color:#c0392b;">两次输入的新密码不一致</span>'; return; }
    try {
        const resp = await fetch('/api/change-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_password: oldPwd, new_password: newPwd })
        });
        const data = await resp.json();
        if (resp.ok) {
            msgEl.innerHTML = '<span style="color:#2e7d32;"><i class="m-icon" data-icon="done"></i> 密码修改成功</span>';
            document.getElementById('mOldPwd').value = '';
            document.getElementById('mNewPwd').value = '';
            document.getElementById('mConfirmPwd').value = '';
        } else {
            msgEl.innerHTML = '<span style="color:#c0392b;"><i class="m-icon" data-icon="error"></i> ' + (data.error || '修改失败') + '</span>';
        }
    } catch(e) {
        msgEl.innerHTML = '<span style="color:#c0392b;"><i class="m-icon" data-icon="error"></i> 修改失败: ' + e.message + '</span>';
    }
}


// 修改手机号：弹窗输入新手机号（复用 m-popup-card 风格遮罩与卡片）
function openChangePhone() {
    var overlay = document.getElementById('mChangePhoneOverlay');
    if (overlay) overlay.remove();
    overlay = document.createElement('div');
    overlay.id = 'mChangePhoneOverlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:2000;background:rgba(0,0,0,0.35);display:flex;align-items:center;justify-content:center;animation:fadeIn .15s ease;-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);';
    overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });
    var cur = (window.__currentPhone || '');
    overlay.innerHTML =
        '<div class="m-popup-card" style="background:var(--m-card,#1c1c1e);color:var(--m-text,#fff);width:86%;max-width:320px;overflow:hidden;animation:fadeIn .15s ease;box-shadow:0 12px 40px rgba(0,0,0,0.4);">' +
            '<div style="padding:18px 18px 10px;font-size:16px;font-weight:700;">修改手机号</div>' +
            '<div style="padding:0 18px 14px;">' +
                '<input id="mNewPhoneInput" type="tel" value="' + esc(cur) + '" placeholder="请输入 11 位手机号" maxlength="11" style="width:100%;box-sizing:border-box;padding:12px;border-radius:var(--m-radius-pill,24px);border:1px solid var(--m-border,#333);background:var(--m-bg,#000);color:var(--m-text,#fff);font-size:15px;outline:none;">' +
                '<div id="mChangePhoneMsg" style="font-size:12px;margin-top:6px;min-height:16px;color:var(--m-danger,#ff453a);"></div>' +
            '</div>' +
            '<div class="m-popup-divider"></div>' +
            '<button onclick="(function(){var o=document.getElementById(\'mChangePhoneOverlay\');if(o)o.remove();})()" style="width:100%;padding:14px;border:none;background:transparent;color:var(--m-text-secondary,#aaa);font-size:15px;cursor:pointer;">取消</button>' +
            '<div class="m-popup-divider"></div>' +
            '<button onclick="submitChangePhone()" style="width:100%;padding:14px;border:none;background:transparent;color:var(--m-accent,#0a84ff);font-size:15px;font-weight:600;cursor:pointer;">保存</button>' +
        '</div>';
    document.body.appendChild(overlay);
    var inp = document.getElementById('mNewPhoneInput');
    if (inp) { inp.focus(); try { inp.select(); } catch(e) {} }
}

async function submitChangePhone() {
    var inp = document.getElementById('mNewPhoneInput');
    var msg = document.getElementById('mChangePhoneMsg');
    if (!inp) return;
    var newPhone = inp.value.trim();
    if (!newPhone) { if (msg) msg.textContent = '请输入手机号'; return; }
    if (!/^1\d{10}$/.test(newPhone)) { if (msg) msg.textContent = '请输入有效的 11 位手机号'; return; }
    var cur = window.__currentPhone || '';
    if (newPhone === cur) { if (msg) msg.textContent = '新手机号与当前相同'; return; }
    try {
        var r = await api('/api/change-phone', { method: 'POST', body: { phone: newPhone } });
        var o = document.getElementById('mChangePhoneOverlay'); if (o) o.remove();
        window.__currentPhone = newPhone;
        showToast('手机号已更新', 'success');
        loadSettingsMobile();  // 刷新账号卡显示
    } catch(e) {
        if (msg) msg.textContent = (e && e.message) ? e.message : '修改失败';
    }
}

function togglePwdMobile(inputId, btn) {
    var inp = document.getElementById(inputId);
    if (!inp) return;
    if (inp.type === 'password') {
        inp.type = 'text';
        btn.innerHTML = ICONS.eyeOff;
    } else {
        inp.type = 'password';
        btn.innerHTML = ICONS.eye;
    }
}

async function loadPendingMobile() {
    try {
        const resp = await fetch('/api/admin/pending');
        const data = await resp.json();
        const arr = data.pending || [];
        document.getElementById('mPendingCount').textContent = arr.length;
        const listEl = document.getElementById('mPendingList');
        if (arr.length === 0) {
            listEl.innerHTML = '<div style="text-align:center;color:#999;font-size:13px;padding:12px;">暂无待审核申请</div>';
            return;
        }
        listEl.innerHTML = arr.map(function(u) {
            return '<div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid #eee;">' +
                '<div><div style="font-weight:600;font-size:14px;">' + (u.phone || u.username || '') + '</div>' +
                '<div style="font-size:11px;color:#999;">' + (u.created_at || '') + '</div></div>' +
                '<div style="display:flex;gap:6px;">' +
                    '<button class="btn btn-success btn-sm" style="font-size:11px;padding:3px 10px;" onclick="approveMobile(' + u.id + ')">通过</button>' +
                    '<button class="btn btn-outline btn-sm" style="font-size:11px;padding:3px 10px;" onclick="rejectMobile(' + u.id + ')">拒绝</button>' +
                '</div></div>';
        }).join('');
    } catch(e) {
        document.getElementById('mPendingList').innerHTML = '<div style="text-align:center;color:#c0392b;font-size:13px;">加载失败</div>';
    }
}

async function approveMobile(userId) {
    try {
        const resp = await fetch('/api/admin/approve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });
        const data = await resp.json();
        if (resp.ok) {
            showToast('已通过', 'success');
            loadPendingMobile();
        } else {
            showToast(data.error || '操作失败', 'error');
        }
    } catch(e) {
        showToast('操作失败: ' + e.message, 'error');
    }
}

async function rejectMobile(userId) {
    try {
        const resp = await fetch('/api/admin/reject', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });
        const data = await resp.json();
        if (resp.ok) {
            showToast('已拒绝', 'success');
            loadPendingMobile();
        } else {
            showToast(data.error || '操作失败', 'error');
        }
    } catch(e) {
        showToast('操作失败: ' + e.message, 'error');
    }
}

async function loadResetsMobile() {
    try {
        const resp = await fetch('/api/admin/password-resets');
        const data = await resp.json();
        const arr = data.resets || [];
        document.getElementById('mResetCount').textContent = arr.length;
        const listEl = document.getElementById('mResetList');
        if (arr.length === 0) {
            listEl.innerHTML = '<div style="text-align:center;color:#999;font-size:13px;padding:12px;">暂无待审核申请</div>';
            return;
        }
        listEl.innerHTML = arr.map(function(r) {
            var who = r.phone || r.username || '';
            return '<div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid #eee;">' +
                '<div><div style="font-weight:600;font-size:14px;">' + esc(who) + '</div>' +
                '<div style="font-size:11px;color:#999;">' + (r.created_at || '') + '</div></div>' +
                '<div style="display:flex;gap:6px;">' +
                    '<button class="btn btn-success btn-sm" style="font-size:11px;padding:3px 10px;" onclick="approveResetMobile(' + r.user_id + ')">通过</button>' +
                    '<button class="btn btn-outline btn-sm" style="font-size:11px;padding:3px 10px;" onclick="rejectResetMobile(' + r.user_id + ')">拒绝</button>' +
                '</div></div>';
        }).join('');
    } catch(e) {
        document.getElementById('mResetList').innerHTML = '<div style="text-align:center;color:#c0392b;font-size:13px;">加载失败</div>';
    }
}

async function approveResetMobile(userId) {
    try {
        const resp = await fetch('/api/admin/reset-approve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });
        const data = await resp.json();
        if (resp.ok) {
            showToast('密码已重置', 'success');
            loadResetsMobile();
        } else {
            showToast(data.error || '操作失败', 'error');
        }
    } catch(e) {
        showToast('操作失败: ' + e.message, 'error');
    }
}

async function rejectResetMobile(userId) {
    try {
        const resp = await fetch('/api/admin/reset-reject', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });
        const data = await resp.json();
        if (resp.ok) {
            showToast('已拒绝', 'success');
            loadResetsMobile();
        } else {
            showToast(data.error || '操作失败', 'error');
        }
    } catch(e) {
        showToast('操作失败: ' + e.message, 'error');
    }
}

// ==================== 工具函数 ====================

function calcDistance(lat1, lon1, lat2, lon2) {
    const R = 6371;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat/2)**2 + Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*Math.sin(dLon/2)**2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}

function loadScript(src) {
    return new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = src;
        s.onload = resolve;
        s.onerror = reject;
        document.head.appendChild(s);
    });
}

function loadCSS(href) {
    return new Promise((resolve) => {
        const l = document.createElement('link');
        l.rel = 'stylesheet';
        l.href = href;
        l.onload = resolve;
        document.head.appendChild(l);
    });
}

/* ============ 打开系统导航（移动端） ============ */
// 优先唤起高德 App，未安装则回落网页版地图（与地图「点击导航」同一接口）
function openNavigationMobile(lat, lon, name) {
    // lat/lon 是 WGS84，高德需 GCJ02
    var gcj = wgs84ToGcj02(lon, lat); // [lng, lat]（GCJ02）
    var lng = gcj[0], glat = gcj[1];
    var nm = encodeURIComponent(name || '目的地');
    // 网页版回落地址（高德 marker 页：显示该客户位置标记，不发起导航）
    var webUrl = 'https://uri.amap.com/marker?position=' + lng + ',' + glat + '&name=' + nm + '&coordinate=gcj02&callnative=1';
    var ua = navigator.userAgent || '';
    // APK 内：调用原生地图选择器，列出本机已安装的地图 App 让用户自选，
    // 不再固定跳转高德、也不再回落网页版（网页版会在 WebView 内打开导致返回键异常）
    if (window.CustomerApp && typeof window.CustomerApp.openMapChooser === 'function') {
        // 走系统原生选择器（geo: + createChooser），传 WGS84 原始坐标
        window.CustomerApp.openMapChooser(lat, lon, name || '目的地');
        return;
    }
    var isAndroid = /android/i.test(ua);
    var isIOS = /iphone|ipad|ipod/i.test(ua);
    if (isAndroid) {
        // 高德 Android scheme：viewMap = 打开地图并居中显示该点（非导航）
        var appUrl = 'androidamap://viewMap?sourceApplication=customer-workspace&poiname=' + nm + '&lat=' + glat + '&lon=' + lng + '&dev=0';
        launchAppThenWeb(appUrl, webUrl);
    } else if (isIOS) {
        var iosUrl = 'iosamap://viewMap?sourceApplication=customer-workspace&poiname=' + nm + '&lat=' + glat + '&lon=' + lng + '&dev=0';
        launchAppThenWeb(iosUrl, webUrl);
    } else {
        window.location.href = webUrl;
    }
}

// 尝试唤起 App：先跳 App scheme；若页面在定时器内既未隐藏（App 已打开）也未失焦（系统「打开方式」选择器已弹出），才回落网页版
function launchAppThenWeb(appUrl, webUrl) {
    var start = Date.now();
    var done = false;
    var clear = function () {
        if (done) return;
        done = true;
        clearTimeout(timer);
        window.removeEventListener('blur', clear);
    };
    // 约 1.6s 后仍未离开页面（说明本机未装高德、scheme 无响应）→ 回落网页版
    var timer = setTimeout(function () {
        if (!document.hidden && !done) {
            window.location.href = webUrl;
        }
    }, 1600);
    // App 真正打开：页面隐藏 → 取消回落
    window.addEventListener('pagehide', clear, { once: true });
    document.addEventListener('visibilitychange', function () {
        if (document.hidden) clear();
    });
    // 系统「打开方式」选择器弹出时 WebView 失焦（页面未隐藏）→ 取消回落，避免同时跳网页
    window.addEventListener('blur', clear, { once: true });
    window.location.href = appUrl;
}

// 客户详情「地址」点击 → 复用地图「点击导航」同一接口（跳到地图 App 显示该客户位置）
function openCustNav(lat, lon, name) {
    lat = parseFloat(lat); lon = parseFloat(lon);
    if (isNaN(lat) || isNaN(lon)) { showToast('该客户暂无定位坐标', 'error'); return; }
    openNavigationMobile(lat, lon, name);
}

// 联系电话 → 系统拨号链接（仅保留可拨号字符）
function telHref(phone) {
    return String(phone || '').replace(/[^\d+]/g, '');
}

// 暴露给全局
window.switchPage = switchPage;
window.loadCustomersMobile = loadCustomersMobile;
window.viewCustomerMobile = viewCustomerMobile;
window.generateReportMobile = generateReportMobile;
window.loadSettingsMobile = loadSettingsMobile;
window.saveSettingsMobile = saveSettingsMobile;
window.changePasswordMobile = changePasswordMobile;
window.openChangePhone = openChangePhone;
window.openSettingsAsSubPage = openSettingsAsSubPage;
window.togglePwdMobile = togglePwdMobile;
window.loadPendingMobile = loadPendingMobile;
window.approveMobile = approveMobile;
window.rejectMobile = rejectMobile;
window.loadResetsMobile = loadResetsMobile;
window.approveResetMobile = approveResetMobile;
window.rejectResetMobile = rejectResetMobile;
window.isOverdue = isOverdue;
window.formatDate = formatDate;
window.calcDistance = calcDistance;
window.editCustomerMobile = editCustomerMobile;
window.saveEditCustomerMobile = saveEditCustomerMobile;
window.deleteCustomerMobile = deleteCustomerMobile;
window.toggleCustTypeMenu = toggleCustTypeMenu;
window.selectCustType = selectCustType;
window.onCustSearchInput = onCustSearchInput;
window.loadBusinessesMobile = loadBusinessesMobile;
window.switchBizTab = switchBizTab;
window.loadLedgerMobile = loadLedgerMobile;
window.searchLedgerMobile = searchLedgerMobile;
window.addLedgerMobile = addLedgerMobile;
window.saveLedgerMobile = saveLedgerMobile;
window.viewLedgerMobile = viewLedgerMobile;
window.editLedgerMobile = editLedgerMobile;
window.saveEditLedgerMobile = saveEditLedgerMobile;
window.deleteLedgerMobile = deleteLedgerMobile;
window.addSubEntry = addSubEntry;
window.removeSubEntry = removeSubEntry;
window.viewBusinessMobile = viewBusinessMobile;
window.addBusinessMobile = addBusinessMobile;
window.editBusinessMobile = editBusinessMobile;
// ==================== 全局页面进入动画 ====================
// 监听 #pageContent 直接子节点变化（整页渲染：一级切换 / 二级页面 / renderPage），
// 自动为内容区施加一次进入动画；地图页用纯淡入以免 transform 影响 fixed 地图容器。
(function initPageTransition() {
    var content = document.getElementById('pageContent');
    if (!content) return;
    var applyAnim = function() {
        // 关闭弹窗后的列表刷新：抑制进入动画，主界面保持不动（与四象限弹窗一致）
        if (_suppressPageAnim) {
            _suppressPageAnim = false;
            content.classList.remove('pg-fade', 'pg-right', 'pg-fade-plain', 'pg-left', 'pg-exit-right');
            return;
        }
        var cls = (currentPage === 'map') ? 'pg-fade-plain'
            : (_pageEnterDir === 'right' ? 'pg-right'
            : (_pageEnterDir === 'left' ? 'pg-left' : 'pg-fade'));
        content.classList.remove('pg-fade', 'pg-right', 'pg-fade-plain', 'pg-left', 'pg-exit-right');
        void content.offsetWidth; // 强制回流以重启动画
        content.classList.add(cls);
    };
    var obs = new MutationObserver(function(muts) {
        for (var i = 0; i < muts.length; i++) {
            if (muts[i].addedNodes.length || muts[i].removedNodes.length) {
                applyAnim();
                renderIcons(content);
                break;
            }
        }
    });
    obs.observe(content, { childList: true, subtree: false });

    // 监听 body 直接子节点变化（弹窗遮罩），自动渲染图标
    var bodyObs = new MutationObserver(function(muts) {
        for (var i = 0; i < muts.length; i++) {
            if (muts[i].addedNodes.length) {
                for (var j = 0; j < muts[i].addedNodes.length; j++) {
                    var node = muts[i].addedNodes[j];
                    if (node && node.nodeType === 1) renderIcons(node);
                }
            }
        }
    });
    bodyObs.observe(document.body, { childList: true, subtree: false });

    // 全局：输入框获焦且软键盘弹出时，将输入框滚动/抬升至可视区域中央（避免被键盘遮挡）。
    // 监听 focusin（冒泡），对 input/textarea/select 延迟 300ms（待键盘完全展开）后 scrollIntoView。
    // 全局生效，不针对单页写死；与页面进入时的滚顶（_subAutoScroll）互不冲突（focusin 在用户点击后触发）。
    document.addEventListener('focusin', function(e) {
        var t = e.target;
        if (!t || t.nodeType !== 1) return;
        var tag = t.tagName;
        if (tag !== 'INPUT' && tag !== 'TEXTAREA' && tag !== 'SELECT') return;
        setTimeout(function() {
            try { t.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (_) {}
        }, 300);
    });
})();

window.saveBusinessMobile = saveBusinessMobile;
window.deleteBusinessMobile = deleteBusinessMobile;
window.filterBizCustomers = filterBizCustomers;
window.selectBizCustomer = selectBizCustomer;
window.addTaskMobile = addTaskMobile;
window.saveTaskMobile = saveTaskMobile;
window.filterTaskCustomers = filterTaskCustomers;
window.selectTaskCustomer = selectTaskCustomer;
window.addMobileSubtask = addMobileSubtask;
window.toggleMobileSubtask = toggleMobileSubtask;
window.deleteMobileSubtask = deleteMobileSubtask;
window.handleSubtaskEnter = handleSubtaskEnter;
window.editTaskMobile = editTaskMobile;
window.saveEditTaskMobile = saveEditTaskMobile;
window.setHeaderMode = setHeaderMode;
window.setTabBarVisible = setTabBarVisible;
window.goBack = goBack;
