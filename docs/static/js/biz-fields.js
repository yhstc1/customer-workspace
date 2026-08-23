// ============================================================
// 业务字段单一数据源（PC 与移动端共用，避免两端字段集分叉）
// 任何业务类型要增/改字段，只改本文件 BIZ_TYPE_FIELDS 一处即可，
// PC 表单、PC 详情面板、移动端表单/详情 全部自动同步。
// 注意：移动端 mobile.js 目前仍内联了一份相同的配置（APK 离线壳约束）；
// 本文件是规范来源，移动端后续重打包时应改为加载本文件以消除重复。
// ============================================================

// 业务类型全集（顺序即「业务类型」下拉/分类菜单顺序）
var BIZ_TYPE_LIST = ['互联网专线', '电路', '算网项目', 'U+产品', '数智惠企', '冰激凌', '魔方卡', '副卡', '宽带', '固话'];
var BIZ_TYPE_LIST_LEFT = ['互联网专线', '电路', '算网项目', 'U+产品', '数智惠企'];
var BIZ_TYPE_LIST_RIGHT = ['冰激凌', '魔方卡', '副卡', '宽带', '固话'];

// 主卡 / 子卡类型
var BIZ_MAIN_TYPES = ['数智惠企', '冰激凌'];
var BIZ_CHILD_TYPES = ['副卡', '宽带', '固话'];
// 主卡底部内联子卡上限（副卡≤4、宽带≤2、固话≤1）
var BIZ_SUB_MAX = { '副卡': 4, '宽带': 2, '固话': 1 };

// 字段元数据：key 与 businesses 表列名一致；label/type 仅控制前端展示与输入控件
var BIZ_FIELD_POOL = {
    business_level:   { key: 'business_level',   label: '业务层级',     type: 'text' },
    business_package: { key: 'business_package', label: '业务套餐',     type: 'text' },
    contract_amount:  { key: 'contract_amount',  label: '合同金额 (¥)', type: 'number' },
    number:           { key: 'number',           label: '号码',         type: 'text' },
    contract_code:    { key: 'contract_code',    label: '合同编码',     type: 'text' },
    start_date:       { key: 'start_date',       label: '开始时间',     type: 'date' },
    end_date:         { key: 'end_date',         label: '结束时间',     type: 'date' },
    business_address: { key: 'business_address', label: '业务地址',     type: 'text' },
    date:             { key: 'date',             label: '办理日期',     type: 'date' },
    user_name:        { key: 'user_name',        label: '使用人',       type: 'text' },
    parent_id:        { key: 'parent_id',        label: '关联主卡',     type: 'parent' },
    notes:            { key: 'notes',            label: '备注',         type: 'textarea' }
};

// 每个业务类型选配的字段 key 有序列表（顺序即表单顺序）。
// parent_id 由结构化的「关联主卡」控件单独处理，不在此清单内。
// business_package（原 PC「业务套餐」）与 business_level（原仅移动端）已并入，两端统一。
var BIZ_TYPE_FIELDS = {
    '互联网专线': ['business_level', 'business_package', 'contract_amount', 'number', 'start_date', 'end_date', 'business_address', 'contract_code', 'notes'],
    '电路':       ['business_level', 'business_package', 'contract_amount', 'number', 'start_date', 'end_date', 'business_address', 'contract_code', 'notes'],
    '算网项目':   ['business_level', 'business_package', 'contract_amount', 'number', 'start_date', 'end_date', 'contract_code', 'notes'],
    'U+产品':     ['business_level', 'business_package', 'contract_amount', 'number', 'start_date', 'end_date', 'contract_code', 'notes'],
    '数智惠企':   ['business_level', 'business_package', 'date', 'number', 'user_name', 'notes'],
    '冰激凌':     ['business_level', 'business_package', 'date', 'number', 'user_name', 'notes'],
    '魔方卡':     ['business_package', 'date', 'number', 'user_name', 'notes'],
    '副卡':       ['date', 'number', 'user_name', 'notes', 'parent_id'],
    '宽带':       ['date', 'number', 'user_name', 'business_address', 'notes', 'parent_id'],
    '固话':       ['date', 'number', 'user_name', 'business_address', 'notes', 'parent_id']
};

// 字段值展示（与移动端 bizFieldDisplay 对齐）：金额带 ¥、日期取 YYYYMM、空值显示 -
function bizFieldDisplay(f, raw) {
    if (f.type === 'number') return (raw != null && raw !== '' && !isNaN(Number(raw))) ? '¥' + Number(raw).toLocaleString() : '-';
    if (f.type === 'date') return raw ? String(raw).replace(/-/g, '').substring(0, 6) : '-';
    return (raw != null && raw !== '') ? raw : '-';
}

// ============================================================
// 业务列表 / 详情 共享渲染（业务页 与 客户详情页 共用，确保两端完全一致）
// 单一数据源：业务页 business.html 与客户详情页 customers.html 都调用这里的函数，
// 不再各自维护一份树渲染 / 详情面板，避免两端分叉。
// ============================================================

// HTML 转义（与移动端 esc 对齐）
function escHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
}

// 三栏 biz-row 同行样式（与移动端 biz-row 一致）
function bizRowHtml(label, value) {
    return '<div class="form-group biz-row"><label>' + escHtml(label) + '</label><div>' + escHtml(value == null ? '' : value) + '</div></div>';
}

// 渲染「主卡 + 可折叠子卡」树（返回 <tr> 片段，不含外层 <table>）。
// list: 当前要展示的业务（已按 tab/搜索过滤）；all: 用于查找子卡的完整数组；
// opts: { expandState, actions(默认 true), listVar(默认 'allBusinesses') }
function renderBizTreeHtml(list, all, opts) {
    all = all || list || [];
    opts = opts || {};
    const expandState = opts.expandState || {};
    const roots = (list || []).filter(function (b) { return !b.parent_id; });
    if (!roots.length) return '';
    const listVar = opts.listVar || 'allBusinesses';
    const onRowClick = opts.onRowClick || function (id) { return 'openBizDetail(' + id + ', ' + listVar + ')'; };
    const withActions = opts.actions !== false;
    let rows = '';
    roots.forEach(function (root) {
        const kids = all.filter(function (b) { return b.parent_id === root.id; });
        const expanded = expandState[root.id] !== false; // 默认展开
        rows += bizRootRowHtml(root, kids.length, expanded, onRowClick, withActions);
        if (expanded) kids.forEach(function (k) { rows += bizChildRowHtml(k, root.id, onRowClick, withActions); });
    });
    return rows;
}

function bizRootRowHtml(root, kidCount, expanded, onRowClick, withActions) {
    const caret = kidCount ? (expanded ? '▾' : '▸') : '';
    const actions = withActions ?
        '<button class="btn btn-outline btn-sm" onclick="event.stopPropagation();editBusiness(' + root.id + ')">编辑</button>' +
        '<button class="btn btn-danger btn-sm" onclick="event.stopPropagation();deleteBusiness(' + root.id + ', \'' + (root.company_name || '').replace(/'/g, "\\'") + '\')">删除</button>' : '';
    return '<tr class="biz-root-row" style="cursor:pointer;" onclick="' + onRowClick(root.id) + '">' +
        '<td onclick="event.stopPropagation();toggleBizExpand(' + root.id + ')" style="text-align:center;">' + caret + '</td>' +
        '<td><strong>' + escHtml(root.company_name) + '</strong>' + (kidCount ? ' <span class="biz-badge">' + kidCount + ' 子卡</span>' : '') + '</td>' +
        '<td>' + escHtml(root.business_type) + '</td>' +
        '<td>' + escHtml(root.contract_code) + '</td>' +
        '<td>' + (root.contract_amount != null ? '¥' + Number(root.contract_amount).toLocaleString() : '-') + '</td>' +
        '<td>' + escHtml(root.number) + '</td>' +
        '<td style="white-space:nowrap;">' + ((root.start_date || '?') + ' ~ ' + (root.end_date || '?')) + '</td>' +
        '<td>' + actions + '</td>' +
    '</tr>';
}

function bizChildRowHtml(k, rootId, onRowClick, withActions) {
    const actions = withActions ?
        '<button class="btn btn-outline btn-sm" onclick="event.stopPropagation();editBusiness(' + k.id + ')">编辑</button>' +
        '<button class="btn btn-danger btn-sm" onclick="event.stopPropagation();deleteBusiness(' + k.id + ', \'' + (k.company_name || '').replace(/'/g, "\\'") + '\')">删除</button>' : '';
    return '<tr class="biz-child-row" style="cursor:pointer;background:#fafbfc;" onclick="' + onRowClick(rootId) + '">' +
        '<td></td>' +
        '<td style="padding-left:30px;color:#555;">↳ ' + escHtml(k.business_type) + (k.number ? ' · ' + escHtml(k.number) : '') + '</td>' +
        '<td></td><td></td><td></td>' +
        '<td>' + escHtml(k.user_name) + '</td>' +
        '<td style="color:#888;">' + (escHtml(k.business_address || k.notes) || '') + '</td>' +
        '<td>' + actions + '</td>' +
    '</tr>';
}

// 只读业务详情面板（对齐移动端 paintBizDetail：主卡 + 嵌套子卡，字段由 BIZ_TYPE_FIELDS 数据驱动）
function ensureBizDetailModal() {
    if (document.getElementById('bizDetailModal')) return;
    const div = document.createElement('div');
    div.className = 'modal-overlay';
    div.id = 'bizDetailModal';
    div.innerHTML = '<div class="modal" style="max-width:720px;">' +
        '<div class="modal-header"><h3 id="bizDetailTitle">业务详情</h3><button class="modal-close" onclick="closeBizDetail()">&times;</button></div>' +
        '<div id="bizDetailBody" style="max-height:70vh;overflow:auto;"></div></div>';
    document.body.appendChild(div);
}

function openBizDetail(id, list) {
    list = list || [];
    const biz = list.find(function (b) { return b.id === id; });
    if (!biz) return;
    // 点子卡也归集到其所属根主卡，展示「主卡 + 全部子卡」
    let root = biz;
    if (biz.parent_id) {
        const p = list.find(function (x) { return x.id === biz.parent_id; });
        if (p) root = p;
    }
    const rootId = root.id;
    const children = list.filter(function (x) { return x.parent_id === rootId; });
    // 编辑/删除按钮仅当本页提供了对应处理函数时显示（业务页有，客户详情页无 → 改为跳转业务页管理）
    const canManage = (typeof window.editBusiness === 'function' && typeof window.deleteBusiness === 'function');

    ensureBizDetailModal();
    document.getElementById('bizDetailTitle').textContent = root.business_type || '业务详情';
    let html = '<div class="biz-detail">';
    // 主卡
    html += '<div class="biz-card">';
    html += bizRowHtml('关联客户', root.company_name);
    html += bizRowHtml('业务类型', root.business_type);
    (BIZ_TYPE_FIELDS[root.business_type] || []).forEach(function (k) {
        const f = BIZ_FIELD_POOL[k];
        if (!f || k === 'parent_id') return;
        html += bizRowHtml(f.label, bizFieldDisplay(f, root[k]));
    });
    html += canManage ?
        '<div style="margin-top:10px;display:flex;gap:8px;">' +
            '<button class="btn btn-primary btn-sm" style="flex:1;" onclick="closeBizDetail();editBusiness(' + root.id + ')">编辑主卡</button>' +
            '<button class="btn btn-danger btn-sm" style="flex:1;" onclick="closeBizDetail();deleteBusiness(' + root.id + ', \'' + (root.company_name || '').replace(/'/g, "\\'") + '\')">删除主卡</button>' +
        '</div>' :
        '<div style="margin-top:10px;display:flex;gap:8px;">' +
            '<button class="btn btn-primary btn-sm" style="flex:1;" onclick="closeBizDetail();window.location.href=\'/business\'">在业务页管理</button>' +
        '</div>';
    html += '</div>';

    // 子卡区
    if (children.length) {
        html += '<div class="biz-card biz-card-wide" style="margin-top:12px;">';
        html += '<div class="biz-card-title">子卡（' + children.length + '）</div>';
        children.forEach(function (ch) {
            const isCur = (ch.id === biz.id);
            const childShow = ['date', 'number', 'user_name', 'notes'];
            if ((BIZ_TYPE_FIELDS[ch.business_type] || []).indexOf('business_address') !== -1) childShow.push('business_address');
            html += '<div class="biz-child-card' + (isCur ? ' biz-child-card--current' : '') + '">';
            html += '<div class="biz-child-card-head">' + escHtml(ch.business_type) + (isCur ? ' · 当前' : '') + '</div>';
            childShow.forEach(function (k) {
                const f = BIZ_FIELD_POOL[k];
                if (!f) return;
                const disp = bizFieldDisplay(f, ch[k]);
                if (!disp || disp === '-') return;
                html += bizRowHtml(f.label, disp);
            });
            if (canManage) {
                html += '<div style="margin-top:8px;display:flex;gap:8px;">' +
                    '<button class="btn btn-outline btn-sm" style="flex:1;" onclick="closeBizDetail();editBusiness(' + ch.id + ')">编辑</button>' +
                    '<button class="btn btn-outline btn-sm" style="flex:1;" onclick="closeBizDetail();deleteBusiness(' + ch.id + ', \'' + (ch.company_name || '').replace(/'/g, "\\'") + '\')">删除</button>' +
                    '</div>';
            }
            html += '</div>';
        });
        html += '</div>';
    }
    html += '</div>';
    document.getElementById('bizDetailBody').innerHTML = html;
    document.getElementById('bizDetailModal').classList.add('show');
}

function closeBizDetail() {
    const m = document.getElementById('bizDetailModal');
    if (m) m.classList.remove('show');
}
