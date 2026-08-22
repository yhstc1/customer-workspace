const auth = require('./utils/auth.js');

App({
  globalData: {
    userId: '',
    token: ''
  },
  onLaunch() {
    // 钉钉免登：换取 userId 与登录态
    auth.login().then((info) => {
      this.globalData.userId = info.userId;
      this.globalData.token = info.token;
    }).catch((e) => {
      dd.alert({ content: '登录失败：' + (e.message || '请检查网络') });
    });
  }
});
