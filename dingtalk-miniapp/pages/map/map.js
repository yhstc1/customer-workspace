const { request } = require('../../utils/request.js');

Page({
  data: { nearby: [], myLng: 0, myLat: 0 },
  onShow() { this.loadNearby(); },
  loadNearby() {
    // 本机定位 → 后端(调腾讯地图)算附近公司
    dd.getLocation({
      success: (loc) => {
        this.setData({ myLng: loc.longitude, myLat: loc.latitude });
        request('/api/nearby?lat=' + loc.latitude + '&lng=' + loc.longitude)
          .then((l) => this.setData({ nearby: (l && l.nearby) || [] }))
          .catch(() => {});
      },
      fail: () => dd.showToast({ content: '定位失败', type: 'fail' })
    });
  },
  openNav(e) {
    const id = e.currentTarget.dataset.id;
    dd.navigateTo({ url: '/pages/customer-detail/customer-detail?id=' + id });
  }
});
