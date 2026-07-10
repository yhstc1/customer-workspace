// ==================== 移动端逻辑 ====================

let currentPage = 'dashboard';

// 钉钉 SDK
const DINGTALK_JS_URL = 'https://g.alicdn.com/dingding/dingtalk-jsapi/2.15.2/dingtalk.open.js';

function initDingtalkAuth() {
    // 检查是否在钉钉环境内
    const ua = navigator.userAgent.toLowerCase();
    if (ua.indexOf('dingtalk') === -1) {
        return; // 不在钉钉内，跳过
    }

    // 动态加载钉钉 JSAPI
    const script = document.createElement('script');
    script.src = DINGTALK_JS_URL;
    script.onload = () => {
        // 获取免登授权码
        if (window.dd) {
            dd.runtime.permission.requestAuthCode({
                corpId: window.DINGTALK_CORP_ID || '',
                onSuccess: (result) => {
                    // 用 authCode 换取用户身份
                    fetch('/api/dingtalk/auth', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ authCode: result.code })
                    })
                    .then(r => r.json())
                    .then(data => {
                        if (data.user) {
                            showToast('钉钉登录成功: ' + (data.user.name || '用户'), 'success');
                        }
                    })
                    .catch(e => console.error('钉钉登录失败', e));
                },
                onFail: (err) => {
                    console.error('获取授权码失败', err);
                }
            });
        }
    };
    document.head.appendChild(script);
}

// ==================== 页面切换 ====================

async function switchPage(page) {
    currentPage = page;
    // 更新 Tab 高亮
    document.querySelectorAll('.tab-item').forEach(t => t.classList.remove('active'));
    const tab = document.querySelector(`.tab-item[data-page="${page}"]`);
    if (tab) tab.classList.add('active');

    // 更新标题
    const titles = {
        dashboard: '📊 仪表盘',
        customers: '👥 客户管理',
        map: '🗺️ 地图视图',
        tasks: '📝 事项看板',
        report: '📋 每日报告'
    };
    document.getElementById('pageTitle').textContent = titles[page] || '';

    // 加载内容
    const content = document.getElementById('pageContent');
    content.innerHTML = '<div class="m-empty"><div class="icon">⏳</div><div>加载中...</div></div>';

    try {
        switch (page) {
            case 'dashboard': await loadDashboard(); break;
            case 'customers': await loadCustomersMobile(); break;
            case 'map': await loadMapMobile(); break;
            case 'tasks': await loadTasksMobile(); break;
            case 'report': await loadReportMobile(); break;
        }
    } catch (e) {
        content.innerHTML = `<div class="m-empty"><div class="icon">❌</div><div>加载失败: ${e.message}</div></div>`;
    }
}

// ==================== 仪表盘 ====================

async function loadDashboard() {
    const data = await api('/api/dashboard');
    const content = document.getElementById('pageContent');

    content.innerHTML = `
        <div class="m-stats-grid">
            <div class="m-stat-card">
                <div class="m-stat-icon">👥</div>
                <div class="m-stat-info">
                    <div class="value">${data.total_customers}</div>
                    <div class="label">客户总数</div>
                </div>
            </div>
            <div class="m-stat-card">
                <div class="m-stat-icon" style="background:#fff3e0;">📋</div>
                <div class="m-stat-info">
                    <div class="value">${data.pending}</div>
                    <div class="label">待处理</div>
                </div>
            </div>
            <div class="m-stat-card">
                <div class="m-stat-icon" style="background:#ffebee;">⏰</div>
                <div class="m-stat-info">
                    <div class="value">${data.overdue}</div>
                    <div class="label">逾期</div>
                </div>
            </div>
            <div class="m-stat-card">
                <div class="m-stat-icon" style="background:#e8f5e9;">✅</div>
                <div class="m-stat-info">
                    <div class="value">${data.completion_rate}%</div>
                    <div class="label">完成率</div>
                </div>
            </div>
        </div>

        <div class="m-card">
            <div class="m-card-title">⚡ 快捷操作</div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
                <button class="btn btn-primary" style="flex:1;min-width:140px;justify-content:center;padding:12px;" onclick="switchPage('map')">🗺️ 附近客户</button>
                <button class="btn btn-success" style="flex:1;min-width:140px;justify-content:center;padding:12px;" onclick="generateReportMobile()">📊 生成报告</button>
            </div>
        </div>

        <div class="m-card">
            <div class="m-card-title">
                <span>📌 最近事项</span>
                <a href="javascript:switchPage('tasks')" style="font-size:13px;color:#667eea;">全部 →</a>
            </div>
            ${data.recent_tasks.length === 0 ? '<div class="m-empty"><div class="icon">📭</div>暂无事项</div>' :
                data.recent_tasks.map(t => `
                    <div class="m-task-item priority-${t.priority}" onclick="switchPage('tasks')">
                        <div class="m-task-title">${t.title}</div>
                        <div class="m-task-customer">👤 ${t.customer_name}</div>
                        <div class="m-task-bottom">
                            <span class="badge status-${t.status}">${t.status}</span>
                            <span style="font-size:12px;color:${isOverdue(t.due_date,t.status)?'#e74c3c':'#888'}">${formatDate(t.due_date)}</span>
                        </div>
                    </div>
                `).join('')}
        </div>
    `;
}

// ==================== 客户管理 ====================

async function loadCustomersMobile(search = '') {
    const params = search ? `?search=${encodeURIComponent(search)}` : '';
    const customers = await api('/api/customers' + params);
    const content = document.getElementById('pageContent');

    // 获取设置（用于显示距离）
    let settings = {};
    try { settings = await api('/api/settings'); } catch(e) {}

    const myLat = parseFloat(settings.my_latitude) || 31.2036;
    const myLon = parseFloat(settings.my_longitude) || 121.6040;

    // 计算距离
    customers.forEach(c => {
        if (c.latitude && c.longitude) {
            c._dist = calcDistance(myLat, myLon, c.latitude, c.longitude);
        }
    });
    customers.sort((a, b) => (a._dist || 999) - (b._dist || 999));

    content.innerHTML = `
        <div class="m-search-bar">
            <input type="text" placeholder="🔍 搜索客户..." value="${search}"
                oninput="clearTimeout(window._searchTimer); window._searchTimer=setTimeout(()=>loadCustomersMobile(this.value), 300)">
        </div>
        <div class="m-card">
            ${customers.length === 0 ? '<div class="m-empty"><div class="icon">📭</div>暂无客户</div>' :
                customers.map(c => `
                    <div class="m-customer-item" onclick="viewCustomerMobile(${c.id})">
                        <div class="m-customer-avatar">${c.name.charAt(0)}</div>
                        <div class="m-customer-info">
                            <div class="m-customer-name">${c.name} ${categoryBadge(c.category)}</div>
                            <div class="m-customer-meta">${c.company || ''} · ${c.phone || ''}</div>
                        </div>
                        ${c._dist != null ? `<div class="m-customer-distance">${c._dist.toFixed(1)}km</div>` : ''}
                    </div>
                `).join('')}
        </div>
    `;
}

async function viewCustomerMobile(id) {
    const data = await api(`/api/customers/${id}`);
    const c = data.customer;
    const content = document.getElementById('pageContent');

    content.innerHTML = `
        <div class="m-card">
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;">
                <div class="m-customer-avatar" style="width:50px;height:50px;font-size:20px;">${c.name.charAt(0)}</div>
                <div>
                    <div style="font-size:18px;font-weight:700;">${c.name}</div>
                    <div style="font-size:13px;color:#888;">${c.company || ''}</div>
                </div>
            </div>
            <div style="font-size:14px;line-height:2;">
                <div>📞 ${c.phone || '-'}</div>
                <div>📧 ${c.email || '-'}</div>
                <div>📍 ${c.address || '-'}</div>
                <div>🏷️ ${categoryBadge(c.category)} <span class="badge priority-${c.priority}">${c.priority}优先级</span></div>
            </div>
            ${c.notes ? `<div class="alert alert-info" style="margin-top:12px;">📝 ${c.notes}</div>` : ''}
        </div>

        <div class="m-card">
            <div class="m-card-title">
                <span>📋 跟进事项 (${data.tasks.length})</span>
            </div>
            ${data.tasks.length === 0 ? '<div class="m-empty"><div class="icon">📭</div>暂无事项</div>' :
                data.tasks.map(t => `
                    <div class="m-task-item priority-${t.priority}">
                        <div class="m-task-title">${t.title}</div>
                        <div class="m-task-bottom">
                            <span class="badge status-${t.status}">${t.status}</span>
                            <div class="progress-bar" style="width:80px;"><div class="progress-fill" style="width:${t.progress}%">${t.progress}%</div></div>
                        </div>
                    </div>
                `).join('')}
        </div>

        <button class="btn btn-outline" style="width:100%;padding:12px;" onclick="switchPage('customers')">← 返回客户列表</button>
    `;
}

// ==================== 地图 ====================

let mobileMap = null;
let mobileMyMarker = null;
let mobileCircle = null;
let mobileCustomerMarkers = [];
let mobileRadius = 10;

async function loadMapMobile() {
    const content = document.getElementById('pageContent');

    content.innerHTML = `
        <div class="m-map-container" id="mapContainer">
            <div id="mobileMap"></div>
        </div>
        <div class="m-card">
            <div class="m-card-title">
                <span>📍 附近客户（<span id="mNearbyCount">0</span>）</span>
                <span style="font-size:13px;color:#888;">
                    <input type="range" id="mRadiusSlider" min="1" max="50" value="10" style="width:80px;vertical-align:middle;">
                    <span id="mRadiusVal">10km</span>
                </span>
            </div>
            <div id="mNearbyList"></div>
        </div>
        <button class="btn btn-primary" style="width:100%;padding:12px;margin-bottom:12px;" onclick="locateMobile()">📡 定位到我</button>
    `;

    // 动态加载 Leaflet
    if (!window.L) {
        await loadScript('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js');
        await loadCSS('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css');
    }

    // 获取设置和客户
    const settings = await api('/api/settings');
    let myLat = parseFloat(settings.my_latitude) || 31.2036;
    let myLon = parseFloat(settings.my_longitude) || 121.6040;
    mobileRadius = parseFloat(settings.default_radius_km) || 10;

    document.getElementById('mRadiusSlider').value = mobileRadius;
    document.getElementById('mRadiusVal').textContent = mobileRadius + 'km';
    document.getElementById('mRadiusSlider').oninput = function() {
        mobileRadius = parseInt(this.value);
        document.getElementById('mRadiusVal').textContent = mobileRadius + 'km';
        updateMobileMap(myLat, myLon);
    };

    const customers = await api('/api/customers');

    // 初始化地图
    mobileMap = L.map('mobileMap').setView([myLat, myLon], 13);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19, attribution: '© OSM'
    }).addTo(mobileMap);

    updateMobileMap(myLat, myLon, customers);

    // 尝试 GPS 定位
    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
            (pos) => {
                myLat = pos.coords.latitude;
                myLon = pos.coords.longitude;
                updateMobileMap(myLat, myLon, customers);
            },
            () => {},
            { timeout: 5000 }
        );
    }

    async function updateMobileMap(lat, lon, custs) {
        if (!custs) custs = customers;
        // 清除旧标记
        if (mobileMyMarker) mobileMap.removeLayer(mobileMyMarker);
        if (mobileCircle) mobileMap.removeLayer(mobileCircle);
        mobileCustomerMarkers.forEach(m => mobileMap.removeLayer(m));
        mobileCustomerMarkers = [];

        // 我的位置
        const myIcon = L.divIcon({
            html: '<div style="width:16px;height:16px;background:#e74c3c;border:3px solid #fff;border-radius:50%;box-shadow:0 0 6px rgba(231,76,60,0.6);"></div>',
            iconSize: [16, 16], iconAnchor: [8, 8]
        });
        mobileMyMarker = L.marker([lat, lon], { icon: myIcon }).addTo(mobileMap);

        // 范围圆
        mobileCircle = L.circle([lat, lon], {
            radius: mobileRadius * 1000,
            color: '#667eea', fillColor: '#667eea',
            fillOpacity: 0.08, weight: 2, dashArray: '5,5'
        }).addTo(mobileMap);

        mobileMap.setView([lat, lon], 13);

        // 附近客户
        const nearby = [];
        custs.forEach(c => {
            if (c.latitude && c.longitude) {
                const dist = calcDistance(lat, lon, c.latitude, c.longitude);
                if (dist <= mobileRadius) {
                    c._dist = dist;
                    nearby.push(c);

                    const colors = { 'VIP客户': '#f39c12', '重要客户': '#3498db', '普通客户': '#95a5a6' };
                    const color = colors[c.category] || '#95a5a6';
                    const icon = L.divIcon({
                        html: `<div style="width:12px;height:12px;background:${color};border:2px solid #fff;border-radius:50%;"></div>`,
                        iconSize: [12, 12], iconAnchor: [6, 6]
                    });
                    const marker = L.marker([c.latitude, c.longitude], { icon })
                        .bindPopup(`<div style="min-width:150px;"><strong>${c.name}</strong><br>${c.company||''}<br>📞 ${c.phone||''}<br>📏 ${dist.toFixed(2)}km</div>`);
                    marker.addTo(mobileMap);
                    mobileCustomerMarkers.push(marker);
                }
            }
        });

        nearby.sort((a, b) => a._dist - b._dist);
        document.getElementById('mNearbyCount').textContent = nearby.length;
        document.getElementById('mNearbyList').innerHTML = nearby.length === 0 ?
            '<div class="m-empty"><div class="icon">🗺️</div>附近暂无客户</div>' :
            nearby.map(c => `
                <div class="m-customer-item" onclick="viewCustomerMobile(${c.id})">
                    <div class="m-customer-avatar">${c.name.charAt(0)}</div>
                    <div class="m-customer-info">
                        <div class="m-customer-name">${c.name}</div>
                        <div class="m-customer-meta">${c.company || ''}</div>
                    </div>
                    <div class="m-customer-distance">${c._dist.toFixed(1)}km</div>
                </div>
            `).join('');
    }

    function locateMobile() {
        if (!navigator.geolocation) { showToast('不支持定位', 'error'); return; }
        showToast('正在定位...');
        navigator.geolocation.getCurrentPosition(
            (pos) => {
                updateMobileMap(pos.coords.latitude, pos.coords.longitude);
                showToast('已定位', 'success');
            },
            (err) => showToast('定位失败: ' + err.message, 'error'),
            { enableHighAccuracy: true, timeout: 10000 }
        );
    }
    window.locateMobile = locateMobile;
    window.viewCustomerMobile = viewCustomerMobile;
}

// ==================== 事项看板 ====================

async function loadTasksMobile() {
    const tasks = await api('/api/tasks');
    const content = document.getElementById('pageContent');

    // 按状态分组
    const groups = { '待处理': [], '进行中': [], '已完成': [] };
    tasks.forEach(t => {
        if (groups[t.status]) groups[t.status].push(t);
        else if (t.status === '已搁置') groups['待处理'].push(t);
    });

    // 优先按距离排序待处理
    const today = new Date().toISOString().substring(0, 10);

    content.innerHTML = `
        ${groups['待处理'].length > 0 ? `
            <div class="m-card">
                <div class="m-card-title"><span>📋 待处理 (${groups['待处理'].length})</span></div>
                ${groups['待处理'].map(t => `
                    <div class="m-task-item priority-${t.priority}" onclick="viewCustomerMobile(${t.customer_id})">
                        <div class="m-task-title">${t.title}</div>
                        <div class="m-task-customer">👤 ${t.customer_name} · ${t.customer_company || ''}</div>
                        <div class="m-task-bottom">
                            <span class="badge priority-${t.priority}">${t.priority}</span>
                            <span style="font-size:12px;color:${isOverdue(t.due_date,t.status)?'#e74c3c':'#888'}">${formatDate(t.due_date)}</span>
                        </div>
                    </div>
                `).join('')}
            </div>
        ` : ''}

        ${groups['进行中'].length > 0 ? `
            <div class="m-card">
                <div class="m-card-title"><span>🔄 进行中 (${groups['进行中'].length})</span></div>
                ${groups['进行中'].map(t => `
                    <div class="m-task-item priority-${t.priority}" onclick="viewCustomerMobile(${t.customer_id})">
                        <div class="m-task-title">${t.title}</div>
                        <div class="m-task-customer">👤 ${t.customer_name}</div>
                        <div class="progress-bar" style="margin:6px 0;"><div class="progress-fill" style="width:${t.progress}%">${t.progress}%</div></div>
                        <div class="m-task-bottom">
                            <span class="badge priority-${t.priority}">${t.priority}</span>
                            <span style="font-size:12px;color:${isOverdue(t.due_date,t.status)?'#e74c3c':'#888'}">${formatDate(t.due_date)}</span>
                        </div>
                    </div>
                `).join('')}
            </div>
        ` : ''}

        ${groups['已完成'].length > 0 ? `
            <div class="m-card">
                <div class="m-card-title"><span>✅ 已完成 (${groups['已完成'].length})</span></div>
                ${groups['已完成'].slice(0, 5).map(t => `
                    <div class="m-task-item" style="border-left-color:#27ae60;opacity:0.7;">
                        <div class="m-task-title">${t.title}</div>
                        <div class="m-task-customer">👤 ${t.customer_name}</div>
                    </div>
                `).join('')}
            </div>
        ` : ''}

        ${tasks.length === 0 ? '<div class="m-empty"><div class="icon">📝</div>暂无事项</div>' : ''}
    `;
}

// ==================== 报告 ====================

async function loadReportMobile() {
    const reports = await api('/api/reports');
    const content = document.getElementById('pageContent');

    content.innerHTML = `
        <div class="m-card">
            <button class="btn btn-primary" style="width:100%;padding:14px;font-size:16px;" onclick="generateReportMobile()">
                ⚡ 立即生成今日报告
            </button>
        </div>

        <div class="m-card">
            <div class="m-card-title"><span>📁 历史报告</span></div>
            ${reports.length === 0 ? '<div class="m-empty"><div class="icon">📭</div>暂无报告</div>' :
                reports.map(r => `
                    <div class="m-report-item">
                        <div>
                            <div class="filename">📄 ${r.filename.replace('daily_report_','').replace('.html','')}</div>
                            <div class="meta">📅 ${r.created} · ${r.size}</div>
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

// 暴露给全局
window.switchPage = switchPage;
window.loadCustomersMobile = loadCustomersMobile;
window.viewCustomerMobile = viewCustomerMobile;
window.generateReportMobile = generateReportMobile;
window.isOverdue = isOverdue;
window.formatDate = formatDate;
window.categoryBadge = categoryBadge;
window.calcDistance = calcDistance;
