// Research page: search, status filter, sort; BibTeX copy everywhere.
(function () {
  document.querySelectorAll('.bib-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var src = document.getElementById('bib-' + btn.dataset.bib);
      if (!src || !navigator.clipboard) return;
      navigator.clipboard.writeText(src.textContent.trim()).then(function () {
        var old = btn.textContent;
        btn.textContent = 'Copied';
        btn.classList.add('copied');
        setTimeout(function () { btn.textContent = old; btn.classList.remove('copied'); }, 1500);
      }, function () {});
    });
  });

  var list = document.getElementById('paper-list');
  if (!list) return;
  var flat = document.getElementById('flat-list');
  var search = document.getElementById('rt-search');
  var sortSel = document.getElementById('rt-sort');
  var count = document.getElementById('rt-count');
  var empty = document.getElementById('rt-empty');
  var papers = Array.prototype.slice.call(list.querySelectorAll('.paper'));
  var homes = papers.map(function (p) { return p.parentNode; });   // original theme sections
  var groups = Array.prototype.slice.call(list.querySelectorAll('.theme-group'));
  var rank = { review: 0, working: 1, progress: 2, published: 3 };
  var state = { status: 'all', q: '', sort: 'topic' };

  function arrange() {
    if (state.sort === 'topic') {
      // put every card back into its theme section, in original order
      papers.slice().sort(function (a, b) { return a.dataset.order - b.dataset.order; })
        .forEach(function (p) { homes[papers.indexOf(p)].appendChild(p); });
      list.hidden = false; flat.hidden = true;
      return;
    }
    var cmp = {
      status: function (a, b) { return rank[a.dataset.status] - rank[b.dataset.status] || a.dataset.order - b.dataset.order; },
      year: function (a, b) { return b.dataset.year - a.dataset.year || a.dataset.order - b.dataset.order; },
      title: function (a, b) { return a.dataset.title.localeCompare(b.dataset.title); }
    }[state.sort];
    papers.slice().sort(cmp).forEach(function (p) { flat.appendChild(p); });
    list.hidden = true; flat.hidden = false;
  }

  function apply() {
    var shown = 0;
    papers.forEach(function (p) {
      var ok = (state.status === 'all' || p.dataset.status === state.status) &&
               (!state.q || p.dataset.search.indexOf(state.q) !== -1);
      p.hidden = !ok;
      if (ok) shown++;
    });
    groups.forEach(function (g) { g.hidden = !g.querySelector('.paper:not([hidden])'); });
    count.textContent = shown + (shown === 1 ? ' paper' : ' papers');
    empty.hidden = shown !== 0;
  }

  function update(fn) {
    if (document.startViewTransition) document.startViewTransition(fn); else fn();
  }

  document.querySelectorAll('.chip[data-status]').forEach(function (chip) {
    chip.addEventListener('click', function () {
      document.querySelectorAll('.chip[data-status]').forEach(function (c) { c.setAttribute('aria-pressed', 'false'); });
      chip.setAttribute('aria-pressed', 'true');
      state.status = chip.dataset.status;
      update(apply);
    });
  });
  search.addEventListener('input', function () { state.q = search.value.trim().toLowerCase(); apply(); });
  sortSel.addEventListener('change', function () { state.sort = sortSel.value; update(function () { arrange(); apply(); }); });
  apply();
})();
