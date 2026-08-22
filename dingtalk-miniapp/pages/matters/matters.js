const { request } = require('../../utils/request.js');

Page({
  data: { list: [], filter: 'all' },
  onShow() { this.load(); },
  load() {
    // 后端路由统一为 /api/tasks；status 取值为中文：进行中 / 已挂起 / 已完结
    const statusMap = { pending: '进行中', suspended: '已挂起', done: '已完结' };
    const q = this.data.filter === 'all' ? '' : '?status=' + (statusMap[this.data.filter] || this.data.filter);
    request('/api/tasks' + q)
      .then((l) => this.setData({ list: (l && l.tasks) || [] }))
      .catch(() => {});
  },
  setFilter(e) {
    this.setData({ filter: e.currentTarget.dataset.f });
    this.load();
  }
});
