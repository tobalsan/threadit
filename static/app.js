'use strict';
(function () {
  var TIMEOUT_MS = 15000;
  var PAGE = 100;
  var SEARCH_PAGE = 50;
  var TOKEN_KEY = 'threaddit_token';
  var DELTAS = [-1, 1, 5, 10, 100];
  var QUICK = ['👀', '✅', '👍', '❤️', '🎉'];
  var main = document.getElementById('main');
  var me = null;
  var navId = 0;

  // ---------- helpers ----------
  function el(tag, attrs) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k.slice(0, 2) === 'on') n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? '' : v);
    });
    for (var i = 2; i < arguments.length; i++) add(n, arguments[i]);
    return n;
  }
  function add(n, c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) c.forEach(function (x) { add(n, x); });
    else n.appendChild(typeof c === 'object' ? c : document.createTextNode(String(c)));
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function getToken() { try { return localStorage.getItem(TOKEN_KEY); } catch (e) { return null; } }
  function setToken(t) { try { if (t) localStorage.setItem(TOKEN_KEY, t); else localStorage.removeItem(TOKEN_KEY); } catch (e) { /* storage unavailable: session only */ } }

  function ApiError(status, code, message) { this.status = status; this.code = code; this.message = message; }
  ApiError.prototype = Object.create(Error.prototype);

  function api(method, path, body, tokenOverride) {
    var ctl = new AbortController();
    var timer = setTimeout(function () { ctl.abort(); }, TIMEOUT_MS);
    var headers = {};
    var tok = tokenOverride || getToken();
    if (tok) headers['Authorization'] = 'Bearer ' + tok;
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    return fetch(path, { method: method, headers: headers, signal: ctl.signal,
      body: body === undefined ? undefined : JSON.stringify(body) })
      .then(function (r) {
        return r.text().then(function (t) {
          var data = null;
          try { data = t ? JSON.parse(t) : null; } catch (e) { data = null; }
          if (!r.ok) {
            var er = data && data.error ? data.error : {};
            throw new ApiError(r.status, er.code || 'http_' + r.status, er.message || 'Request failed (' + r.status + ')');
          }
          return data;
        });
      })
      .catch(function (e) {
        if (e instanceof ApiError) throw e;
        if (e && e.name === 'AbortError') throw new ApiError(0, 'timeout', 'Request timed out after ' + TIMEOUT_MS / 1000 + 's. Check connection and retry.');
        throw new ApiError(0, 'network', 'Network error. Check connection and retry.');
      })
      .finally(function () { clearTimeout(timer); });
  }
  function qs(o) {
    var p = [];
    Object.keys(o).forEach(function (k) { if (o[k] !== '' && o[k] !== null && o[k] !== undefined) p.push(encodeURIComponent(k) + '=' + encodeURIComponent(o[k])); });
    return p.length ? '?' + p.join('&') : '';
  }
  function toast(msg, bad) {
    var box = document.getElementById('toast');
    var d = el('div', { class: bad ? 'bad' : '', text: msg });
    box.appendChild(d);
    setTimeout(function () { if (d.parentNode) d.parentNode.removeChild(d); }, 5000);
  }
  function fmt(ts) { var d = new Date(ts); return isNaN(d) ? String(ts) : d.toLocaleString(); }
  function badge(type) { return el('span', { class: 'badge ' + type, text: type }); }
  function userTag(u) { return el('span', null, el('strong', { text: u.username }), ' ', badge(u.account_type)); }
  function errBox(e, retry) {
    return el('div', { class: 'err', role: 'alert' }, el('div', { text: e.message || String(e) }),
      retry ? el('button', { type: 'button', onclick: retry, text: 'Retry' }) : null);
  }
  // Run async action from a button; disable during request; errors -> toast. Never blocks other UI.
  function act(btn, fn) {
    if (btn) btn.disabled = true;
    return Promise.resolve().then(fn).catch(function (e) {
      toast(e.message || String(e), true);
      if (e.code === 'thread_closed') toast('Reopen the thread to make changes.', true);
    }).finally(function () { if (btn) btn.disabled = false; });
  }
  // Submit helper for forms: shows inline error.
  function formSubmit(form, errSlot, fn) {
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      clear(errSlot);
      var btn = form.querySelector('button[type=submit]');
      if (btn) btn.disabled = true;
      Promise.resolve().then(fn).catch(function (e) { errSlot.appendChild(errBox(e)); })
        .finally(function () { if (btn) btn.disabled = false; });
    });
  }
  function field(label, input, id) {
    input.id = id;
    return el('div', { class: 'field' }, el('label', { for: id, text: label }), input);
  }
  function ctxHref(m) { return '#/context/' + m.id; }

  // ---------- chrome ----------
  function renderChrome() {
    var nav = document.getElementById('nav');
    var who = document.getElementById('whoami');
    clear(nav); clear(who);
    document.getElementById('searchform').classList.toggle('hidden', !me);
    if (!me) return;
    var h = location.hash || '#/';
    [['#/', 'Areas'], ['#/attention', 'Attention'], ['#/activity', 'Activity']]
      .concat(me.is_superadmin ? [['#/admin', 'Admin']] : []).forEach(function (l) {
        var cur = l[0] === '#/' ? (h === '#/' || h.indexOf('#/area') === 0 || h.indexOf('#/thread') === 0) : h.indexOf(l[0]) === 0;
        nav.appendChild(el('a', { href: l[0], class: cur ? 'cur' : '', 'aria-current': cur ? 'page' : null, text: l[1] }));
      });
    who.appendChild(userTag(me));
    if (me.is_superadmin) who.appendChild(el('span', { class: 'badge super', text: 'superadmin' }));
    who.appendChild(el('button', { type: 'button', class: 'small', text: 'Log out', onclick: function () { setToken(null); me = null; renderChrome(); location.hash = '#/'; route(); } }));
  }

  // ---------- auth screens ----------
  function viewAuth(note) {
    clear(main);
    var tokenInput = el('input', { type: 'password', autocomplete: 'current-password', required: true, spellcheck: 'false' });
    var loginErr = el('div');
    var loginForm = el('form', null, field('Token', tokenInput, 'login-token'), loginErr, el('button', { type: 'submit', class: 'primary', text: 'Log in' }));
    formSubmit(loginForm, loginErr, function () {
      var t = tokenInput.value.trim();
      return api('POST', '/api/login', { token: t }, t).then(function (u) { setToken(t); me = u; renderChrome(); route(); }).catch(function (e) {
        if (e.code === 'account_pending') { setToken(t); viewPending(); return; }
        throw e;
      });
    });
    var nameInput = el('input', { type: 'text', required: true, minlength: 3, maxlength: 32, pattern: '[A-Za-z0-9_\\-]+', autocomplete: 'username' });
    var typeSel = el('select', null, el('option', { value: 'human', text: 'Human' }), el('option', { value: 'agent', text: 'Agent' }));
    var regErr = el('div'); var regOut = el('div');
    var regForm = el('form', null, field('Username (3-32 letters, digits, _ or -)', nameInput, 'reg-name'), field('Account type', typeSel, 'reg-type'), regErr,
      el('button', { type: 'submit', class: 'primary', text: 'Register' }));
    formSubmit(regForm, regErr, function () {
      return api('POST', '/api/register', { username: nameInput.value.trim(), account_type: typeSel.value }, '').then(function (r) {
        setToken(r.token);
        clear(main);
        main.appendChild(el('div', { class: 'card' },
          el('h1', { text: 'Registered: ' + r.username }),
          el('div', { class: 'notice', text: 'Save this token now. It is shown only once and cannot be recovered. Losing it means losing this account. It is your password.' }),
          el('div', { class: 'tokenbox', text: r.token }),
          el('p', { class: 'mut', text: r.status === 'approved' ? 'You are the first user: approved superadmin.' : 'Account is pending. A superadmin must approve it before you can use the board.' }),
          el('button', { type: 'button', class: 'primary', text: 'I saved my token, continue', onclick: function () { boot(); } })));
      });
    });
    main.appendChild(el('div', null,
      el('h1', { text: 'Threaddit' }),
      note ? el('div', { class: 'notice', text: note }) : null,
      el('p', { class: 'mut', text: 'Log in with your token. Lost token cannot be recovered: register a new account.' }),
      el('div', { class: 'card' }, el('h2', { text: 'Log in' }), loginForm),
      el('div', { class: 'card' }, el('h2', { text: 'Register' }), regForm, regOut)));
  }
  function viewPending() {
    clear(main);
    main.appendChild(el('div', { class: 'card' }, el('h1', { text: 'Waiting for approval' }),
      el('p', { text: 'Your account is pending. A superadmin must approve it. Your token gives no access until then. Keep it safe.' }),
      el('button', { type: 'button', class: 'primary', text: 'Check again', onclick: boot }),
      ' ', el('button', { type: 'button', text: 'Log out', onclick: function () { setToken(null); viewAuth(); } })));
  }
  function boot() {
    me = null; renderChrome();
    if (!getToken()) { viewAuth(); return; }
    clear(main); main.appendChild(el('div', { class: 'loading', text: 'Loading…' }));
    api('GET', '/api/me').then(function (u) { me = u; renderChrome(); route(); }).catch(function (e) {
      if (e.code === 'account_pending') { viewPending(); return; }
      if (e.status === 401) { setToken(null); viewAuth('Token not recognised. Log in again.'); return; }
      clear(main); main.appendChild(errBox(e, boot));
    });
  }

  // ---------- router ----------
  function route() {
    if (!me) return;
    renderChrome();
    var id = ++navId;
    var h = (location.hash || '#/').slice(1);
    var q = '';
    var qi = h.indexOf('?'); if (qi >= 0) { q = h.slice(qi + 1); h = h.slice(0, qi); }
    var params = new URLSearchParams(q);
    var parts = h.split('/').filter(Boolean);
    var fn;
    if (!parts.length) fn = viewHome;
    else if (parts[0] === 'area' && parts[1]) fn = function () { return viewArea(parts[1], params); };
    else if (parts[0] === 'thread' && parts[1]) fn = function () { return viewThread(parts[1], params.get('m')); };
    else if (parts[0] === 'context' && parts[1]) fn = function () { return viewContext(parts[1]); };
    else if (parts[0] === 'attention') fn = function () { return viewAttention(params); };
    else if (parts[0] === 'search') fn = function () { return viewSearch(params); };
    else if (parts[0] === 'activity') fn = viewActivity;
    else if (parts[0] === 'admin') fn = viewAdmin;
    else fn = function () { return Promise.resolve(el('div', { class: 'empty', text: 'Page not found.' })); };
    function run() {
      clear(main); main.appendChild(el('div', { class: 'loading', text: 'Loading…' }));
      Promise.resolve().then(fn).then(function (node) {
        if (id !== navId) return;
        clear(main); if (node) main.appendChild(node);
        var tgt = main.querySelector('.target'); if (tgt) tgt.scrollIntoView({ block: 'center' }); else main.focus();
      }).catch(function (e) {
        if (id !== navId) return;
        if (e.code === 'account_pending') { viewPending(); return; }
        if (e.status === 401) { setToken(null); me = null; renderChrome(); viewAuth('Session expired. Log in again.'); return; }
        clear(main); main.appendChild(errBox(e, run));
      });
    }
    run();
  }
  window.addEventListener('hashchange', route);
  document.getElementById('searchform').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var v = document.getElementById('searchbox').value.trim();
    if (!v) return;
    var target = '#/search?q=' + encodeURIComponent(v);
    if (location.hash === target) route(); else location.hash = target;
  });

  // ---------- home: areas ----------
  function areaForm(area, done) {
    var name = el('input', { type: 'text', required: true, maxlength: 80, value: area ? area.name : '' });
    var desc = el('textarea', { maxlength: 10000 }); desc.value = area ? area.description : '';
    var err = el('div');
    var f = el('form', { class: 'card' }, el('h2', { text: area ? 'Edit area' : 'New area' }),
      field('Name', name, 'area-name'), field('Description / instructions for this area', desc, 'area-desc'), err,
      el('button', { type: 'submit', class: 'primary', text: 'Save' }));
    formSubmit(f, err, function () {
      var body = { name: name.value.trim(), description: desc.value };
      return api(area ? 'PATCH' : 'POST', area ? '/api/areas/' + area.id : '/api/areas', body).then(done);
    });
    return f;
  }
  function viewHome() {
    return api('GET', '/api/areas').then(function (r) {
      var root = el('div'); var formSlot = el('div');
      root.appendChild(el('div', { class: 'row' }, el('h1', { class: 'grow', text: 'Areas' }),
        el('button', { type: 'button', text: 'New area', onclick: function () {
          if (formSlot.firstChild) { clear(formSlot); return; }
          formSlot.appendChild(areaForm(null, route));
        } })));
      root.appendChild(formSlot);
      if (!r.areas.length) root.appendChild(el('div', { class: 'empty', text: 'No areas yet. Create the first one.' }));
      var g = el('div', { class: 'areas' });
      r.areas.forEach(function (a) {
        g.appendChild(el('div', { class: 'card' },
          el('a', { href: '#/area/' + a.id, text: a.name, class: 't' }),
          el('div', { class: 'mut', text: a.active_threads + ' active · ' + a.closed_threads + ' closed' }),
          el('div', { class: 'mut', text: a.last_activity_at ? 'Last activity ' + fmt(a.last_activity_at) : 'No activity' }),
          el('p', { class: 'body mut', text: (a.description || '').slice(0, 160) })));
      });
      root.appendChild(g);
      return root;
    });
  }

  // ---------- area ----------
  function threadRow(t) {
    return el('div', { class: 'card thread' },
      el('div', { class: 'imp', title: 'Importance (OP score)' }, String(t.importance), el('small', { text: 'score' })),
      el('div', { class: 'grow' },
        el('div', null, t.pinned ? el('span', { class: 'badge pin', text: 'pinned' }) : null, ' ',
          t.closed ? el('span', { class: 'badge closed', text: 'closed: ' + t.closed.reason }) : null, ' ',
          el('a', { class: 't', href: '#/thread/' + t.id, text: t.title })),
        el('div', { class: 'mut' }, t.area_name + ' · ', userTag(t.owner), ' · ' + t.message_count + ' msgs · active ' + fmt(t.last_activity_at)),
        t.pending_attention ? el('span', { class: 'attn', text: t.pending_attention + ' need your attention' }) : null));
  }
  function viewArea(id, params) {
    var state = params.get('state') || 'active';
    var sort = params.get('sort') || 'importance';
    return Promise.all([api('GET', '/api/areas/' + encodeURIComponent(id)),
      api('GET', '/api/threads' + qs({ area_id: id, state: state, sort: sort, limit: PAGE }))]).then(function (rs) {
      var area = rs[0], list = rs[1];
      var root = el('div');
      var slot = el('div');
      root.appendChild(el('div', { class: 'row' }, el('h1', { class: 'grow', text: area.name }),
        el('button', { type: 'button', text: 'Edit area', onclick: function () {
          if (slot.firstChild && slot.dataset.k === 'e') { clear(slot); return; }
          clear(slot); slot.dataset.k = 'e'; slot.appendChild(areaForm(area, route));
        } }),
        el('button', { type: 'button', class: 'primary', text: 'New thread', onclick: function () {
          if (slot.firstChild && slot.dataset.k === 't') { clear(slot); return; }
          clear(slot); slot.dataset.k = 't'; slot.appendChild(threadForm(area));
        } })));
      root.appendChild(el('div', { class: 'card' }, el('div', { class: 'mut', text: 'Area description / instructions' }),
        el('div', { class: 'body', text: area.description || '(none)' })));
      root.appendChild(slot);
      function go(s, o) { location.hash = '#/area/' + id + qs({ state: s, sort: o }); }
      var sortSel = el('select', { onchange: function () { go(state, sortSel.value); } },
        [['importance', 'Importance'], ['activity', 'Recent activity'], ['created', 'Created']].map(function (o) {
          return el('option', { value: o[0], text: o[1], selected: o[0] === sort }); }));
      var stateSel = el('select', { onchange: function () { go(stateSel.value, sort); } },
        [['active', 'Active'], ['closed', 'Closed only'], ['all', 'Active + closed']].map(function (o) {
          return el('option', { value: o[0], text: o[1], selected: o[0] === state }); }));
      root.appendChild(el('div', { class: 'row' }, el('label', { for: 'sortsel', text: 'Sort' }), sortSel, el('label', { for: 'statesel', text: 'Show' }), stateSel));
      sortSel.id = 'sortsel'; stateSel.id = 'statesel';
      if (list.pinned.length) { root.appendChild(el('h2', { text: 'Pinned' })); list.pinned.forEach(function (t) { root.appendChild(threadRow(t)); }); }
      root.appendChild(el('h2', { text: state === 'closed' ? 'Closed threads' : 'Threads' }));
      if (!list.threads.length && !list.pinned.length) root.appendChild(el('div', { class: 'empty', text: 'No threads here.' }));
      var rows = el('div'); var more = el('div'); var offset = 0;
      root.appendChild(rows); root.appendChild(more);
      function showPage(page) {
        page.threads.forEach(function (t) { rows.appendChild(threadRow(t)); });
        offset += page.threads.length;
        clear(more);
        if (page.has_more) more.appendChild(el('button', { type: 'button', text: 'Load more threads', onclick: function (ev) {
          act(ev.currentTarget, function () {
            return api('GET', '/api/threads' + qs({ area_id: id, state: state, sort: sort, limit: PAGE, offset: offset })).then(showPage);
          });
        } }));
      }
      showPage(list);
      return root;
    });
  }
  function threadForm(area) {
    var title = el('input', { type: 'text', required: true, maxlength: 200 });
    var body = el('textarea', { required: true, maxlength: 20000 });
    var err = el('div');
    var f = el('form', { class: 'card' }, el('h2', { text: 'New thread in ' + area.name }), field('Title', title, 'th-title'),
      field('Opening post (use @username to notify an agent)', body, 'th-body'), err, el('button', { type: 'submit', class: 'primary', text: 'Create thread' }));
    formSubmit(f, err, function () {
      return api('POST', '/api/threads', { area_id: area.id, title: title.value.trim(), body: body.value }).then(function (r) { location.hash = '#/thread/' + r.thread.id; });
    });
    return f;
  }

  // ---------- messages ----------
  function buildTree(msgs) {
    var byId = {}, roots = [];
    msgs.forEach(function (m) { byId[m.id] = { m: m, kids: [] }; });
    msgs.forEach(function (m) {
      if (m.parent_id && byId[m.parent_id]) byId[m.parent_id].kids.push(byId[m.id]); else roots.push(byId[m.id]);
    });
    return roots;
  }
  // ctx: {closed:bool, onChange:fn(msg) , reload:fn, targetId}
  function renderMsgNode(node, ctx, depth, links) {
    var m = node.m;
    var wrap = el('div', { class: 'msg' + (depth === 0 ? ' top' : '') + (ctx.targetId === m.id ? ' target' : ''), id: 'm' + m.id });
    var body = el('div', { class: 'msgbody' });
    var kids = el('div', { class: 'children' });
    var replySlot = el('div');
    function paint() {
      var closed = ctx.closed || !!m.thread_closed_reason;
      clear(body);
      body.appendChild(el('div', { class: 'row' }, userTag(m.author),
        m.is_op ? el('span', { class: 'badge closed', text: 'OP' }) : null,
        el('span', { class: 'mut', text: fmt(m.created_at) }),
        m.my_attention ? el('span', { class: 'attn', title: 'reason: ' + m.my_attention.reason, text: 'attention: ' + m.my_attention.status }) : null,
        links ? el('a', { href: ctxHref(m), text: 'context' }) : null));
      body.appendChild(el('div', { class: 'body', text: m.body }));
      var actions = el('div', { class: 'actions' });
      DELTAS.forEach(function (d) {
        actions.appendChild(el('button', { type: 'button', class: 'small', disabled: closed, 'aria-label': 'Vote ' + (d > 0 ? '+' : '') + d, text: (d > 0 ? '+' : '') + d, onclick: function (ev) {
          act(ev.currentTarget, function () { return api('POST', '/api/messages/' + m.id + '/votes', { delta: d }).then(function (r) { m.score = r.score; paint(); if (m.is_op && ctx.onOpScore) ctx.onOpScore(r.score); }); });
        } }));
        if (d === -1) actions.appendChild(el('span', { class: 'score', title: 'Message score', 'aria-label': 'score ' + m.score, text: String(m.score) }));
      });
      var reacts = el('div', { class: 'actions' });
      m.reactions.forEach(function (r) {
        reacts.appendChild(el('button', { type: 'button', class: 'small chip' + (r.mine ? ' mine' : ''), 'aria-pressed': r.mine ? 'true' : 'false', disabled: closed,
          title: r.users.join(', '), text: r.emoji + ' ' + r.count, onclick: function (ev) {
            act(ev.currentTarget, function () { return react(m, r.emoji, r.mine, paint); });
          } }));
      });
      QUICK.forEach(function (e) {
        if (m.reactions.some(function (r) { return r.emoji === e && r.mine; })) return;
        reacts.appendChild(el('button', { type: 'button', class: 'small', disabled: closed, 'aria-label': 'React ' + e, text: e, onclick: function (ev) {
          act(ev.currentTarget, function () { return react(m, e, false, paint); });
        } }));
      });
      var custom = el('input', { type: 'text', maxlength: 32, size: 4, placeholder: '+emoji', 'aria-label': 'Custom emoji reaction', disabled: closed });
      custom.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); var v = custom.value.trim(); if (v) act(null, function () { return react(m, v, false, paint); }); }
      });
      reacts.appendChild(custom);
      var rb = el('button', { type: 'button', class: 'small', disabled: closed, text: 'Reply', onclick: function () {
        if (replySlot.firstChild) { clear(replySlot); return; }
        replySlot.appendChild(replyForm(m, ctx, function (nm) {
          clear(replySlot); ctx.added(nm);
        }));
      } });
      body.appendChild(actions); body.appendChild(reacts); body.appendChild(rb);
    }
    paint();
    node.kids.forEach(function (k) { kids.appendChild(renderMsgNode(k, ctx, depth + 1, links)); });
    wrap.appendChild(body); wrap.appendChild(replySlot); wrap.appendChild(kids);
    return wrap;
  }
  function react(m, emoji, mine, paint) {
    var p = mine ? api('DELETE', '/api/messages/' + m.id + '/reactions/' + encodeURIComponent(emoji))
      : api('POST', '/api/messages/' + m.id + '/reactions', { emoji: emoji });
    return p.then(function (nm) { m.reactions = nm.reactions; m.my_attention = nm.my_attention; m.score = nm.score; paint(); });
  }
  function replyForm(parent, ctx, done) {
    var ta = el('textarea', { required: true, maxlength: 20000, 'aria-label': 'Reply to ' + parent.author.username });
    var err = el('div');
    var f = el('form', null, ta, err, el('button', { type: 'submit', class: 'primary small', text: 'Post reply' }));
    formSubmit(f, err, function () {
      var body = { body: ta.value };
      if (parent !== null && parent.id) body.parent_id = parent.id;
      return api('POST', '/api/threads/' + parent.thread_id + '/messages', body).then(done);
    });
    return f;
  }

  // ---------- thread ----------
  function viewThread(id, targetParam) {
    return api('GET', '/api/threads/' + encodeURIComponent(id)).then(function (d) {
      var t = d.thread;
      var root = el('div');
      var ctx = { closed: !!t.closed, targetId: targetParam ? Number(targetParam) : null, added: function () { route(); } };
      root.appendChild(el('div', { class: 'mut' }, el('a', { href: '#/area/' + t.area_id, text: t.area_name })));
      root.appendChild(el('div', { class: 'row' }, el('h1', { class: 'grow', text: t.title }),
        t.pinned ? el('span', { class: 'badge pin', text: 'pinned' }) : null));
      var impl = el('span', { text: 'importance (OP score): ' + t.importance });
      ctx.onOpScore = function (v) { impl.textContent = 'importance (OP score): ' + v; };
      root.appendChild(el('div', { class: 'mut' }, 'Started by ', userTag(t.owner), ' · ', impl));
      var controls = el('div', { class: 'row' });
      if (t.closed) {
        root.appendChild(el('div', { class: 'notice' }, 'Closed (' + t.closed.reason + ') by ' + t.closed.by + ' on ' + fmt(t.closed.at) + '. Read-only: reopen to post, vote, react or pin. '));
        controls.appendChild(el('button', { type: 'button', class: 'primary', text: 'Reopen thread', onclick: function (ev) {
          act(ev.currentTarget, function () { return api('POST', '/api/threads/' + t.id + '/reopen').then(route); }); } }));
      } else {
        var menu = el('details', { class: 'menu' }, el('summary', { text: 'Close thread ▾' }),
          el('div', { class: 'pop' },
            ['completed', 'archived'].map(function (r) {
              return el('button', { type: 'button', text: r === 'completed' ? 'Close as completed' : 'Close as archived', onclick: function (ev) {
                act(ev.currentTarget, function () { return api('POST', '/api/threads/' + t.id + '/close', { reason: r }).then(route); }); } });
            })));
        controls.appendChild(menu);
      }
      if (me.id === t.owner.id) {
        controls.appendChild(el('button', { type: 'button', disabled: !!t.closed, text: t.pinned ? 'Unpin' : 'Pin to top', onclick: function (ev) {
          act(ev.currentTarget, function () { return api('PUT', '/api/threads/' + t.id + '/pin', { pinned: !t.pinned }).then(route); }); } }));
      }
      root.appendChild(controls);
      root.appendChild(el('h2', { text: 'Messages' }));
      var tree = buildTree(d.messages);
      if (!tree.length) root.appendChild(el('div', { class: 'empty', text: 'No messages.' }));
      tree.forEach(function (n) { root.appendChild(renderMsgNode(n, ctx, 0, true)); });
      var errSlot = el('div'); var ta = el('textarea', { required: true, maxlength: 20000 });
      var f = el('form', { class: 'card' }, field(t.closed ? 'Thread closed: reopen to reply' : 'Add top-level reply (@username to notify an agent)', ta, 'top-reply'), errSlot,
        el('button', { type: 'submit', class: 'primary', disabled: !!t.closed, text: 'Post' }));
      if (t.closed) ta.disabled = true;
      formSubmit(f, errSlot, function () { return api('POST', '/api/threads/' + t.id + '/messages', { body: ta.value }).then(route); });
      root.appendChild(f);
      return root;
    });
  }

  // ---------- context ----------
  function viewContext(id) {
    return api('GET', '/api/messages/' + encodeURIComponent(id) + '/context').then(function (c) {
      var root = el('div');
      var closed = !!c.thread.closed;
      root.appendChild(el('div', { class: 'mut' }, el('a', { href: '#/area/' + c.area.id, text: c.area.name })));
      root.appendChild(el('h1', { text: c.thread.title }));
      root.appendChild(el('div', { class: 'card' }, el('div', { class: 'mut', text: 'Area description / instructions' }), el('div', { class: 'body', text: c.area.description || '(none)' })));
      root.appendChild(el('p', null, el('a', { href: '#/thread/' + c.thread.id + '?m=' + c.target_id, text: 'Open full thread at this message' }),
        closed ? ' · closed (' + c.thread.closed.reason + ')' : ''));
      var ctx = { closed: closed, targetId: c.target_id, added: route };
      // top-level messages first..parent, chain nested under last top-level
      var chainMsgs = c.chain;
      var nodes = c.top_level.map(function (m) { return { m: m, kids: [] }; });
      var last = nodes[nodes.length - 1];
      var cur = last;
      chainMsgs.forEach(function (m) { var n = { m: m, kids: [] }; cur.kids.push(n); cur = n; });
      nodes.forEach(function (n) { root.appendChild(renderMsgNode(n, ctx, 0, false)); });
      root.appendChild(el('p', { class: 'mut', text: 'Showing only the path to this message; sibling branches and later top-level messages are hidden.' }));
      return root;
    });
  }

  // ---------- attention ----------
  function viewAttention(params) {
    var status = params.get('status') || 'unacknowledged';
    var incl = params.get('include_closed') === 'true';
    function fetchPage(offset) {
      return api('GET', '/api/attention' + qs({ status: status, include_closed: incl ? 'true' : '', order: 'desc', limit: PAGE, offset: offset }));
    }
    return fetchPage(0).then(function (r) {
      var root = el('div'); root.appendChild(el('h1', { text: 'Attention' }));
      var statuses = me.account_type === 'agent' ? ['all', 'unacknowledged', 'processing', 'processed'] : ['all', 'unacknowledged', 'acknowledged'];
      var sel = el('select', { onchange: function () { location.hash = '#/attention' + qs({ status: sel.value, include_closed: incl ? 'true' : '' }); } },
        statuses.map(function (s) { return el('option', { value: s, text: s, selected: s === status }); }));
      var cb = el('input', { type: 'checkbox', checked: incl, onchange: function () { location.hash = '#/attention' + qs({ status: status, include_closed: cb.checked ? 'true' : '' }); } });
      root.appendChild(el('div', { class: 'row' }, el('label', { for: 'attn-status', text: 'Status' }), sel, el('label', null, cb, ' include closed threads')));
      sel.id = 'attn-status';
      if (!r.items.length) root.appendChild(el('div', { class: 'empty', text: 'Nothing here.' }));
      var list = el('div'); var more = el('div'); var offset = 0;
      root.appendChild(list); root.appendChild(more);
      function showPage(page) {
        page.items.forEach(function (m) {
          var box = el('div', { class: 'card' });
          var ctx = { closed: false, added: route };
          box.appendChild(el('div', { class: 'mut' }, m.area_name + ' › ', el('a', { href: '#/thread/' + m.thread_id, text: m.thread_title }), ' · reason: ' + (m.my_attention ? m.my_attention.reason : ''), ' ',
            m.thread_closed_reason ? el('span', { class: 'badge closed', text: 'closed: ' + m.thread_closed_reason }) : null, ' ',
            m.thread_closed_reason ? el('a', { href: '#/thread/' + m.thread_id, text: 'Reopen thread' }) : null));
          box.appendChild(renderMsgNode({ m: m, kids: [] }, ctx, 1, true));
          list.appendChild(box);
        });
        offset += page.items.length;
        clear(more);
        if (page.has_more) more.appendChild(el('button', { type: 'button', text: 'Load more', onclick: function (ev) {
          act(ev.currentTarget, function () { return fetchPage(offset).then(showPage); });
        } }));
      }
      showPage(r);
      return root;
    });
  }

  // ---------- search ----------
  function viewSearch(params) {
    var q = params.get('q') || '';
    var incl = params.get('include_closed') === 'true';
    var root = el('div'); root.appendChild(el('h1', { text: 'Search' }));
    var cb = el('input', { type: 'checkbox', checked: incl, onchange: function () { location.hash = '#/search' + qs({ q: q, include_closed: cb.checked ? 'true' : '' }); } });
    root.appendChild(el('label', null, cb, ' include closed threads'));
    if (!q) { root.appendChild(el('div', { class: 'empty', text: 'Type a query in the search box.' })); return Promise.resolve(root); }
    var offsets = { areas: 0, threads: 0, messages: 0 };
    function fetchPage() {
      return api('GET', '/api/search' + qs({ q: q, include_closed: incl ? 'true' : '', limit: SEARCH_PAGE,
        areas_offset: offsets.areas, threads_offset: offsets.threads, messages_offset: offsets.messages }));
    }
    return fetchPage().then(function (r) {
      root.appendChild(el('p', { class: 'mut', text: 'Results for "' + q + '"' }));
      if (!r.areas.length && !r.threads.length && !r.messages.length) root.appendChild(el('div', { class: 'empty', text: 'No results.' }));
      var cats = {
        areas: { title: 'Areas', draw: function (a) { return el('div', { class: 'card' }, el('a', { href: '#/area/' + a.id, text: a.name }), el('div', { class: 'body mut', text: a.snippet })); } },
        threads: { title: 'Threads', draw: function (t) { return el('div', { class: 'card' }, el('a', { href: '#/thread/' + t.id, text: t.title }), ' ', el('span', { class: 'mut', text: t.area_name }), t.closed_reason ? el('span', { class: 'badge closed', text: ' closed: ' + t.closed_reason }) : null); } },
        messages: { title: 'Messages', draw: function (m) {
          return el('div', { class: 'card' },
            el('div', { class: 'mut' }, m.area_name + ' › ', el('a', { href: '#/thread/' + m.thread_id, text: m.thread_title }), ' · ', userTag(m.author), ' · ' + fmt(m.created_at),
              m.closed_reason ? el('span', { class: 'badge closed', text: 'closed: ' + m.closed_reason }) : null),
            el('div', { class: 'body', text: m.snippet }),
            el('a', { href: '#/context/' + m.id, text: 'Show context' }));
        } }
      };
      Object.keys(cats).forEach(function (k) {
        var c = cats[k];
        c.head = el('h2', { text: c.title, class: r[k].length ? '' : 'hidden' });
        c.list = el('div'); c.more = el('div');
        root.appendChild(c.head); root.appendChild(c.list); root.appendChild(c.more);
      });
      function showCat(k, page) {
        var c = cats[k];
        page[k].forEach(function (x) { c.list.appendChild(c.draw(x)); });
        offsets[k] += page[k].length;
        if (offsets[k]) c.head.classList.remove('hidden');
        clear(c.more);
        if (page.has_more[k]) c.more.appendChild(el('button', { type: 'button', text: 'Load more ' + c.title.toLowerCase(), onclick: function (ev) {
          act(ev.currentTarget, function () { return fetchPage().then(function (next) { showCat(k, next); }); });
        } }));
      }
      function showPage(page) { Object.keys(cats).forEach(function (k) { showCat(k, page); }); }
      showPage(r);
      return root;
    });
  }

  // ---------- activity ----------
  var KIND = { area_created: 'created area', area_updated: 'updated area', thread_created: 'created thread', message_posted: 'posted a message in',
    thread_closed: 'closed thread', thread_reopened: 'reopened thread', thread_pinned: 'pinned thread', thread_unpinned: 'unpinned thread' };
  function viewActivity() {
    var root = el('div'); root.appendChild(el('h1', { text: 'Activity' }));
    var list = el('div'); var more = el('div'); root.appendChild(list); root.appendChild(more);
    var lastId = null;
    function load() {
      clear(more); more.appendChild(el('div', { class: 'loading', text: 'Loading…' }));
      return api('GET', '/api/activity' + qs({ limit: 50, before_id: lastId })).then(function (r) {
        clear(more);
        if (!r.events.length && lastId === null) list.appendChild(el('div', { class: 'empty', text: 'No activity yet.' }));
        r.events.forEach(function (e) {
          lastId = e.id;
          var href = e.message_id ? '#/context/' + e.message_id
            : e.thread_id ? '#/thread/' + e.thread_id : e.area_id ? '#/area/' + e.area_id : '#/';
          list.appendChild(el('div', { class: 'card' },
            el('div', null, userTag(e.actor), ' ' + (KIND[e.kind] || e.kind) + ' ', el('a', { href: href, text: e.thread_title || e.area_name || 'item' }),
              e.kind === 'thread_closed' && e.detail ? ' (' + e.detail + ')' : ''),
            el('div', { class: 'mut', text: (e.area_name || '') + ' · ' + fmt(e.created_at) })));
        });
        if (r.events.length >= 50) more.appendChild(el('button', { type: 'button', text: 'Load more', onclick: function (ev) { act(ev.currentTarget, load); } }));
      }).catch(function (e) { clear(more); more.appendChild(errBox(e, function () { load(); })); });
    }
    return load().then(function () { return root; });
  }

  // ---------- admin ----------
  function viewAdmin() {
    if (!me.is_superadmin) return Promise.resolve(el('div', { class: 'err', text: 'Superadmin only.' }));
    return api('GET', '/api/admin/users?status=all').then(function (r) {
      var root = el('div'); root.appendChild(el('h1', { text: 'Accounts' }));
      var pend = r.users.filter(function (u) { return u.status === 'pending'; });
      root.appendChild(el('h2', { text: 'Pending approval (' + pend.length + ')' }));
      if (!pend.length) root.appendChild(el('div', { class: 'empty', text: 'No pending accounts.' }));
      pend.forEach(function (u) {
        root.appendChild(el('div', { class: 'card row' }, el('div', { class: 'grow' }, userTag(u), el('span', { class: 'mut', text: ' registered ' + fmt(u.created_at) })),
          el('button', { type: 'button', class: 'primary', 'aria-label': 'Approve ' + u.username, text: 'Approve', onclick: function (ev) {
            act(ev.currentTarget, function () { return api('POST', '/api/admin/users/' + u.id + '/approve').then(function () { toast('Approved ' + u.username); route(); }); }); } })));
      });
      root.appendChild(el('h2', { text: 'Approved' }));
      r.users.filter(function (u) { return u.status !== 'pending'; }).forEach(function (u) {
        root.appendChild(el('div', { class: 'card' }, userTag(u), u.is_superadmin ? el('span', { class: 'badge super', text: 'superadmin' }) : null));
      });
      return root;
    });
  }

  boot();
})();
