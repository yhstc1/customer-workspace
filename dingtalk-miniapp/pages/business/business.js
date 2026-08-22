const { request } = require('../../utils/request.js');

Page({
  data: { list: [] },
  onShow() { this.load(); },
  load() {
    request('/api/business')
      .then((r) => this.setData({ list: (r && r.businesses) || [] }))
      .catch(() => {});
  },
  goExport() {
    dd.navigateTo({ url: '/pages/export/export?kind=business' });
  },
  goImport() {
    dd.navigateTo({ url: '/pages/export/export?kind=business' });
  }
});
