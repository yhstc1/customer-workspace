const { request } = require('../../utils/request.js');

const EXPORT_TYPES = [
  { key: 'customers', name: '客户' },
  { key: 'business', name: '业务台账' },
  { key: 'all', name: '全量备份' },
];

Page({
  data: {
    exportTypes: EXPORT_TYPES,
    kind: 'customers',
    exporting: false,
    // 导入区
    importKind: 'customers',
    importText: '',
    importing: false,
    importResult: '',
    importDetails: [],
    importDetailsMore: 0,
    // 由列表页带入的预选类型
    presetKind: '',
  },

  onLoad(query) {
    if (query && query.kind) {
      const valid = EXPORT_TYPES.some((t) => t.key === query.kind);
      if (valid) {
        this.setData({ kind: query.kind, presetKind: query.kind });
      }
    }
  },

  chooseExportKind(e) {
    this.setData({ kind: e.currentTarget.dataset.key });
  },

  chooseImportKind(e) {
    this.setData({ importKind: e.currentTarget.dataset.key });
  },

  onImportText(e) {
    this.setData({ importText: e.detail.value });
  },

  // ============ 导出 ============
  doExport() {
    if (this.data.exporting) return;
    this.setData({ exporting: true });
    const kind = this.data.kind;
    const fmt = kind === 'all' ? 'json' : 'csv';
    request('/api/export', { method: 'POST', data: { kind, format: fmt } })
      .then((r) => this._handleExportResult(r, kind, fmt))
      .catch((err) => {
        this.setData({ exporting: false });
        dd.showToast({ content: (err && err.message) || '导出失败', type: 'fail' });
      });
  },

  _handleExportResult(r, kind, fmt) {
    this.setData({ exporting: false });
    // OSS 未配置：后端直接返回文本片段，复制到剪贴板
    if (r && r.warning && r.content) {
      dd.setClipboard({ text: r.content });
      dd.showModal({
        title: '已复制到剪贴板',
        content: '当前未配置云端存储，已导出内容的前 5000 字复制到剪贴板，可粘贴到备忘录保存。建议配置 OSS 后重新导出获得完整文件。',
        showCancel: false,
      });
      return;
    }
    if (r && r.url) {
      this._downloadAndSave(r.url, kind, fmt);
      return;
    }
    dd.showToast({ content: '导出完成', type: 'success' });
  },

  _downloadAndSave(url, kind, fmt) {
    dd.showLoading({ content: '下载中…' });
    dd.downloadFile({
      url,
      success: (dl) => {
        dd.hideLoading();
        const filePath = dl.filePath || (dl.apFilePath);
        if (!filePath) {
          dd.showToast({ content: '下载失败', type: 'fail' });
          return;
        }
        dd.saveFileToDisk({
          filePath,
          success: () => dd.showToast({ content: '已保存到文件', type: 'success' }),
          fail: () => {
            // 部分环境无保存权限，退化为复制链接
            dd.setClipboard({ text: url });
            dd.showModal({
              title: '已复制下载链接',
              content: '当前环境无法保存到本地文件，下载链接已复制到剪贴板（1 小时内有效），可粘贴到浏览器下载。',
              showCancel: false,
            });
          },
        });
      },
      fail: () => {
        dd.hideLoading();
        dd.setClipboard({ text: url });
        dd.showToast({ content: '下载失败，链接已复制', type: 'fail' });
      },
    });
  },

  // ============ 导入 ============
  doImport() {
    if (this.data.importing) return;
    const text = (this.data.importText || '').trim();
    if (!text) {
      dd.showToast({ content: '请先粘贴 CSV 内容', type: 'fail' });
      return;
    }
    this.setData({ importing: true, importResult: '' });
    request('/api/import', {
      method: 'POST',
      data: { kind: this.data.importKind, csv: text },
    })
      .then((r) => {
        const imported = (r && r.imported) || 0;
        const skipped = (r && r.skipped) || 0;
        const details = (r && r.skipped_details) || [];
        const summary = '成功导入 ' + imported + ' 条' + (skipped > 0 ? '，剔除 ' + skipped + ' 条' : '');
        // 明细最多展示 20 条，超出提示折叠
        const shown = details.slice(0, 20);
        this.setData({
          importing: false,
          importResult: summary,
          importDetails: shown,
          importDetailsMore: details.length > shown.length ? (details.length - shown.length) : 0,
          importText: '',
        });
        dd.showToast({ content: summary, type: skipped > 0 ? 'none' : 'success' });
      })
      .catch((err) => {
        this.setData({ importing: false, importResult: '导入失败：' + ((err && err.message) || '未知错误'), importDetails: [] });
        dd.showToast({ content: (err && err.message) || '导入失败', type: 'fail' });
      });
  },

  copySkippedDetails() {
    const d = this.data.importDetails || [];
    if (!d.length) return;
    const text = d.map((x) => '第' + x.line + '行 ' + (x.key || '') + '：' + x.reason).join('\n');
    dd.setClipboard({ text });
    dd.showToast({ content: '剔除明细已复制', type: 'success' });
  },

  copyTemplate() {
    const tpl = this.data.importKind === 'business'
      ? 'customer_id,company_name,business_type,business_level,number,contract_code,contract_amount,start_date,end_date,business_address,date,user_name,parent_id,notes'
      : 'company,name,phone,address,business_type,importance,tier,notes';
    dd.setClipboard({ text: tpl });
    dd.showToast({ content: '模板表头已复制', type: 'success' });
  },
});
