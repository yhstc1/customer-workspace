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
async function api(url, options = {}) {
    const defaults = {
        headers: { 'Content-Type': 'application/json' },
    };
    const config = { ...defaults, ...options };
    if (config.body && typeof config.body === 'object') {
        config.body = JSON.stringify(config.body);
    }
    const resp = await fetch(url, config);
    const data = await resp.json();
    if (!resp.ok) {
        throw new Error(data.error || `请求失败 (${resp.status})`);
    }
    return data;
}

// 激活导航
function setActiveNav() {
    const path = window.location.pathname;
    document.querySelectorAll('.navbar-nav a').forEach(a => {
        const href = a.getAttribute('href');
        if (href === path || (path === '/' && href === '/') || (path !== '/' && href !== '/' && path.startsWith(href))) {
            a.classList.add('active');
        }
    });
}

// 分类徽章（空分类不显示任何徽章）
function categoryBadge(category) {
    if (!category) return '<span style="color:#bbb;">-</span>';
    const map = {
        '核心要客': 'badge-core',
        'TOP20': 'badge-top20',
        // 兼容历史数据
        'VIP客户': 'badge-core',
        '重要客户': 'badge-top20',
    };
    return `<span class="badge ${map[category] || 'badge-normal'}">${category}</span>`;
}

// 格式化日期
function formatDate(dateStr) {
    if (!dateStr) return '-';
    return dateStr.substring(0, 10);
}

// 判断是否逾期
function isOverdue(dueDate, status) {
    if (!dueDate || status === '已完成') return false;
    const today = new Date().toISOString().substring(0, 10);
    return dueDate < today;
}

// 页面加载时初始化导航
document.addEventListener('DOMContentLoaded', setActiveNav);
