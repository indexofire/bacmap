(function () {
  try {
    var saved = localStorage.getItem('bacmap-theme');
    var pref = saved === 'light' || saved === 'system' || saved === 'dark' ? saved : 'dark';
    var systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    var resolved = pref === 'system' ? (systemDark ? 'dark' : 'light') : pref;
    document.documentElement.dataset.theme = resolved;
    document.documentElement.style.colorScheme = resolved;
  } catch (e) {
    document.documentElement.dataset.theme = 'dark';
  }
})();
