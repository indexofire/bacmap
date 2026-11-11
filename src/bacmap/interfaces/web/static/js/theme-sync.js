/* bacmap legacy 页面主题同步（v1.10.23）。
 *
 * 与 Vue 控制台同源共享 localStorage（bacmap-theme）；经 CSP
 * script-src 'self' 允许（外置同源文件，内联会被拦）。嵌入 iframe
 * （控制台 LegacyEmbedView）时自动跟随控制台 dark/gray/light 三态。
 */
(function () {
  try {
    var t = localStorage.getItem("bacmap-theme");
    document.documentElement.dataset.theme =
      t === "light" || t === "gray" ? t : "dark";
  } catch (e) {
    /* 无 localStorage 环境（严格沙箱）：保持默认暗色 */
  }
})();
