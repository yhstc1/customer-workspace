const auth = require('./utils/auth.js');

App({
  globalData: {
    userId: '',
    token: '',
    authReady: null
  },
  onLaunch() {
    // 钉钉免登：换取 userId 与登录态，把 Promise 暴露给页面/请求层等待
    this.globalData.authReady = auth.login().then((info) => {
      this.globalData.userId = info.id || info.userId || '';
      const cached = dd.getStorageSync({ key: 'sessionToken' });
      this.globalData.token = (cached && cached.data) || '';
    }).catch((e) => {
      const detail = (e && e.message) ? e.message : (e ? JSON.stringify(e) : '请检查网络');
      console.error('[app] login failed', e);
      dd.alert({ content: '登录失败：' + detail });
      throw e;
    });
  }
});
