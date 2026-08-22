// 后端 API 基础地址：部署到阿里云 FC 后填入其 HTTP 触发器公网端点
// 本地/联调阶段可先填 ngrok 或 FC 临时地址
const config = {
  // 阿里云 FC HTTP 触发器公网端点（P2 已部署）
  apiBase: 'https://crm-api-ixbdhqkitv.cn-hangzhou.fcapp.run',
  // Workbuddy连接 组织 corpId（免登 requestAuthCode 必填）
  corpId: 'ding49b7555f7b0e7c421b9a8c00fa015bc5',
  // 本应用 AppKey（已建，密钥存于 .internal_app_secret）
  appKey: 'dingnurzg7xk1gmitlar'
};

module.exports = config;
