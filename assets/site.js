// Research page: search, theme/status filters, BibTeX copy.
(function () {
  // BibTeX copy buttons (research page and paper pages)
  document.querySelectorAll('.bib-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var src = document.getElementById('bib-' + btn.dataset.bib);
      if (!src) return;
      var text = src.textContent.trim();
      var done = function () {
        var old = btn.textContent;
        btn.textContent = 'Copied';
        btn.classList.add('copied');
        setTimeout(function () { btn.textContent = old; btn.classList.remove('copied'); }, 1500);
      };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, function () {});
    });
  });

  var list = document.getElementById('paper-list');
  if (!list) return;
  var search = document.getElementById('rt-search');
  var count = document.getElementById('rt-count');
  var papers = Array.prototype.slice.call(list.querySelectorAll('.paper'));
  var groups = Array.prototype.slice.call(list.querySelectorAll('.theme-group'));
  var empty = document.getElementById('rt-empty');
  var state = { status: 'all', q: '' };

  function apply() {
    var shown = 0;
    papers.forEach(function (p) {
      var okStatus = state.status === 'all' || p.dataset.status === state.status;
      var okQ = !state.q || p.dataset.search.indexOf(state.q) !== -1;
      p.hidden = !(okStatus && okQ);
      if (!p.hidden) shown++;
    });
    groups.forEach(function (g) {
      g.hidden = !g.querySelector('.paper:not([hidden])');
    });
    count.textContent = shown + (shown === 1 ? ' paper' : ' papers');
    empty.hidden = shown !== 0;
  }

  document.querySelectorAll('.chip[data-status]').forEach(function (chip) {
    chip.addEventListener('click', function () {
      document.querySelectorAll('.chip[data-status]').forEach(function (c) { c.setAttribute('aria-pressed', 'false'); });
      chip.setAttribute('aria-pressed', 'true');
      state.status = chip.dataset.status;
      apply();
    });
  });
  search.addEventListener('input', function () { state.q = search.value.trim().toLowerCase(); apply(); });
  apply();
})();
