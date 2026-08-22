const { request } = require('../../utils/request.js');

Page({
  data: { id: '', detail: null, matters: [] },
  onLoad(query) {
    this.setData({ id: query.id });
    this.load();
  },
  load() {
    request('/api/customers/' + this.data.id)
      .then((d) => this.setData({ detail: (d && d.customer) || null }))
      .catch(() => {});
    // 后端路由统一为 /api/tasks（事项 = tasks）
    request('/api/tasks?customer_id=' + this.data.id)
      .then((m) => this.setData({ matters: (m && m.tasks) || [] }))
      .catch(() => {});
  }
});
