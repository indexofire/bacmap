(function () {
  try {
    var saved = localStorage.getItem('bacmap-theme');
    var pref = saved === 'light' || saved === 'gray' || saved === 'system' || saved === 'dark' ? saved : 'dark';
    var systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    var resolved = pref === 'system' ? (systemDark ? 'dark' : 'light') : pref;
    document.documentElement.dataset.theme = resolved;
    document.documentElement.style.colorScheme = resolved === 'dark' ? 'dark' : 'light';
  } catch (e) {
    document.documentElement.dataset.theme = 'dark';
  }
})();
