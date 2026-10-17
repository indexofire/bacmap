// 任务详情状态轮询（外置以配合严格 CSP：禁止内联脚本）。
// 通过 #status[data-task-id] 取任务 ID，2s 轮询 fragment，仅在内容变化时写 DOM。
(function () {
  var box = document.getElementById('status');
  if (!box) return;
  var taskId = box.getAttribute('data-task-id');
  if (!taskId) return;
  var url = '/tasks/' + encodeURIComponent(taskId) + '/fragment';
  var TERMINAL = ['succeeded', 'failed', 'cancelled'];
  var last = null;
  var before = null;

  function currentState() {
    var el = box.querySelector('[data-state]');
    return el ? el.getAttribute('data-state') : null;
  }

  // 审批表单正在编辑（聚焦或有未提交修改）时跳过本轮，避免轮询覆盖输入。
  function formBusy() {
    var ae = document.activeElement;
    if (ae && box.contains(ae)) return true;
    var controls = box.querySelectorAll('input, textarea, select');
    for (var i = 0; i < controls.length; i++) {
      var el = controls[i];
      if (el.type === 'submit' || el.type === 'button') continue;
      if (typeof el.value === 'string' && el.value !== el.defaultValue) return true;
      var opts = el.selectedOptions || [];
      for (var j = 0; j < opts.length; j++) {
        if (!opts[j].defaultSelected) return true;
      }
    }
    return false;
  }

  function schedule() {
    setTimeout(tick, 2000);
  }

  function tick() {
    if (formBusy()) { schedule(); return; }
    fetch(url)
      .then(function (r) { return r.ok ? r.text() : Promise.reject(r.status); })
      .then(function (html) {
        if (html !== last) {
          last = html;
          box.innerHTML = html;
          var after = currentState();
          if (after !== before) {
            // 仅状态真实变化时做淡入（内容未变不写 DOM，aria-live 不重复播报）
            box.classList.remove('live--swap');
            void box.offsetWidth;
            box.classList.add('live--swap');
            before = after;
          }
          if (TERMINAL.indexOf(after) !== -1) return; // 终态：停止轮询
        }
        schedule();
      })
      .catch(function () { schedule(); });
  }

  before = currentState();
  tick();
})();
