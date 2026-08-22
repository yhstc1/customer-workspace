const { request } = require('../../utils/request.js');

Page({
  data: { list: [], loading: true, keyword: '' },
  onShow() { this.load(); },
  load() {
    this.setData({ loading: true });
    request('/api/customers?keyword=' + encodeURIComponent(this.data.keyword))
      .then((payload) => this.setData({ list: (payload && payload.customers) || [], loading: false }))
      .catch((e) => {
        this.setData({ loading: false });
        dd.showToast({ content: e.message || '加载失败', type: 'fail' });
      });
  },
  onSearch(e) {
    this.setData({ keyword: e.detail.value });
    this.load();
  },
  goDetail(e) {
    const id = e.currentTarget.dataset.id;
    dd.navigateTo({ url: '/pages/customer-detail/customer-detail?id=' + id });
  },
  goExport() {
    dd.navigateTo({ url: '/pages/export/export?kind=customers' });
  },
  goImport() {
    dd.navigateTo({ url: '/pages/export/export?kind=customers' });
  }
});
