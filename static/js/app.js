// ==================== 公共工具函数 ====================

// Toast 提示
function showToast(message, type = '') {
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        toast.style.transition = 'all 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// API 请求封装
// 统一基于 session cookie 认证（credentials: include 自动带），无 JWT。
async function api(url, options = {}) {
    const defaults = {
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',  // PC 端同源访问 session 必须带 cookie
    };
    const config = { ...defaults, ...options };
    if (config.body && typeof config.body === 'object') {
        config.body = JSON.stringify(config.body);
    }
    const resp = await fetch(url, config);
    // 未登录（会话过期/JWT 失效）：H5 环境显示登录浮层，不再跳 /login（PC 页）
    if (resp.status === 401) {
        const data = await resp.json().catch(() => ({}));
        if (typeof window.showH5Login === 'function') {
            window.showH5Login(data.error || '登录已失效，请重新登录');
        }
        throw new Error(data.error || '未登录');
    }
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        throw new Error(data.error || `请求失败 (${resp.status})`);
    }
    // 写操作（非 GET）成功后通知移动端标记页面缓存失效，保证返回/切 tab 时数据最新
    if (config.method && config.method.toUpperCase() !== 'GET') {
        if (typeof window.__mobileMarkDirty === 'function') window.__mobileMarkDirty();
    }
    return data;
}

// 激活导航
function setActiveNav() {
    const path = window.location.pathname;
    const isActive = (href) =>
        href === path ||
        (path === '/' && href === '/') ||
        (path !== '/' && href !== '/' && path.startsWith(href));
    document.querySelectorAll('.nav-item').forEach(a => {
        if (isActive(a.getAttribute('href'))) a.classList.add('active');
    });
    // 移动端底部 tab 高亮
    document.querySelectorAll('.mobile-tabbar a').forEach(a => {
        if (isActive(a.getAttribute('href'))) a.classList.add('active');
    });
}

// 注入移动端底部 Tab 栏
function injectMobileTabBar() {
    // 避免重复注入
    if (document.querySelector('.mobile-tabbar')) return;
    const tabs = [
        { href: '/customers', icon: '👥', label: '客户' },
        { href: '/tasks', icon: '📝', label: '事项' },
        { href: '/map', icon: '🗺️', label: '地图' },
        { href: '/settings', icon: '⚙️', label: '设置' },
    ];
    const nav = document.createElement('nav');
    nav.className = 'mobile-tabbar';
    nav.innerHTML = tabs.map(t =>
        `<a href="${t.href}"><span class="tab-icon">${t.icon}</span><span>${t.label}</span></a>`
    ).join('');
    document.body.appendChild(nav);
}

// 分类徽章（空分类不显示任何徽章）
function categoryBadge(category) {
    if (!category) return '<span style="color:#bbb;">-</span>';
    const map = {
        '核心要客': 'badge-core',
        'TOP20': 'badge-top20',
        '普通客户': 'badge-normal',
        // 兼容历史数据
        'VIP客户': 'badge-core',
        '重要客户': 'badge-top20',
    };
    return `<span class="badge ${map[category] || 'badge-normal'}">${category}</span>`;
}

// 显示联系人：有联系人则显示，否则显示法人
function displayContact(c) {
    const contacts = (c.contact || '').split('||');
    const phones = (c.phone || '').split('||');
    const name = contacts[0] || c.name || '-';
    const phone = phones[0] || '';
    return phone ? `${name}<br><span style="color:#888;font-size:12px;">${phone}</span>` : name;
}

// 渲染所有联系人组
function renderContacts(c) {
    const contacts = (c.contact || '').split('||');
    const phones = (c.phone || '').split('||');
    let html = '';
    const max = Math.max(contacts.length, phones.length, 1);
    for (let i = 0; i < max; i++) {
        const name = contacts[i] || (i === 0 ? (c.name || '-') : '');
        const phone = phones[i] || '';
        if (name || phone) {
            html += `<div style="margin:4px 0;">${i+1}. ${name}${phone ? '  📞 ' + phone : ''}</div>`;
        }
    }
    return html || '-';
}

// 格式化日期
function formatDate(dateStr) {
    if (!dateStr) return '-';
    return dateStr.substring(0, 10);
}

// 判断是否逾期
function isOverdue(dueDate, status) {
    if (!dueDate || status === '已完结') return false;
    const today = new Date().toISOString().substring(0, 10);
    return dueDate < today;
}

// CSV 导出：导出「当前筛选/搜索结果」（rows 为二维数组，不含表头）。
// 带 BOM + CRLF，Excel 中文友好；字段含逗号/引号/换行时自动加引号转义。
function downloadCsv(filename, headers, rows) {
    if (!rows || !rows.length) {
        showToast('当前没有可导出的数据', 'error');
        return;
    }
    const escapeCsv = function (v) {
        const s = (v == null ? '' : String(v));
        return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const lines = [headers.map(escapeCsv).join(',')];
    rows.forEach(function (r) { lines.push(r.map(escapeCsv).join(',')); });
    const csv = '﻿' + lines.join('\r\n'); // BOM 放最前，Excel 才识别 UTF-8
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    showToast('已导出 ' + rows.length + ' 条', 'success');
}

// 页面加载时初始化导航
document.addEventListener('DOMContentLoaded', () => {
    injectMobileTabBar();
    setActiveNav();
});
