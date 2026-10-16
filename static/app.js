'use strict';
(function () {
  var TIMEOUT_MS = 15000;
  var PAGE = 100;
  var SEARCH_PAGE = 50;
  var TOKEN_KEY = 'threaddit_token';
  var UPLOAD_TIMEOUT_MS = 120000;
  var MAX_ATTACHMENTS = 10;
  var MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;
  var INLINE_IMAGES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp'];
  var DELTAS = [-5, -1, 1, 5];
  var RESORT_DELAY_MS = 2000;
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

  // raw: {blob, type} sends a file as the raw request body instead of JSON.
  function api(method, path, body, tokenOverride, raw) {
    var ctl = new AbortController();
    var timeoutMs = raw ? UPLOAD_TIMEOUT_MS : TIMEOUT_MS;
    var timer = setTimeout(function () { ctl.abort(); }, timeoutMs);
    var headers = {};
    var tok = tokenOverride || getToken();
    if (tok) headers['Authorization'] = 'Bearer ' + tok;
    if (raw) headers['Content-Type'] = raw.type;
    else if (body !== undefined) headers['Content-Type'] = 'application/json';
    return fetch(path, { method: method, headers: headers, signal: ctl.signal,
      body: raw ? raw.blob : body === undefined ? undefined : JSON.stringify(body) })
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
        if (e && e.name === 'AbortError') throw new ApiError(0, 'timeout', 'Request timed out after ' + timeoutMs / 1000 + 's. Check connection and retry.');
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
  // Submit helper for forms: shows inline error. Cmd/Ctrl+Enter in a textarea submits.
  function formSubmit(form, errSlot, fn) {
    form.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Enter' || !(ev.metaKey || ev.ctrlKey) || ev.target.tagName !== 'TEXTAREA') return;
      ev.preventDefault();
      var btn = form.querySelector('button[type=submit]');
      if (!btn || !btn.disabled) form.requestSubmit();
    });
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      clear(errSlot);
      var btn = form.querySelector('button[type=submit]');
      if (btn) btn.disabled = true;
      Promise.resolve().then(fn).catch(function (e) { errSlot.appendChild(errBox(e)); })
        .finally(function () { if (btn) btn.disabled = false; });
    });
  }
  // holder: node shown in place of the input (e.g. a wrapper around it).
  function field(label, input, id, holder) {
    input.id = id;
    return el('div', { class: 'field' }, el('label', { for: id, text: label }), holder || input);
  }
  function ctxHref(m) { return '#/context/' + m.id; }
  function areaRef(o) { return o.area_slug || o.slug || o.area_id || o.id; }
  function modified(o) {
    return o.edited_at ? el('span', { class: 'mut modified', title: 'Edited ' + fmt(o.edited_at), text: '(modified)' }) : null;
  }
  function fmtSize(n) { return n < 1024 ? n + ' B' : n < 1048576 ? Math.round(n / 102.4) / 10 + ' KB' : Math.round(n / 104857.6) / 10 + ' MB'; }

  // ---------- markdown (safe subset: builds DOM nodes, never parses HTML) ----------
  var INLINE_RE = /`([^`\n]+)`|\[([^\]\n]+)\]\(([^)\s]+)\)|\*\*(.+?)\*\*|\b__(.+?)__\b|\*([^*\s](?:[^*]*[^*\s])?)\*|\b_([^_\s](?:[^_]*[^_\s])?)_\b|(https?:\/\/[^\s<>"]+)/;
  var BLOCK_START = /^(```|#{1,6}\s|\s*>|\s*[-*+]\s+|\s*\d+[.)]\s+)/;
  function safeHref(u) {
    if (/[\u0000-\u0020\u007f\\]/.test(u)) return null;
    if (/^(https?:\/\/|mailto:)/i.test(u) || /^(\/(?!\/)|#|\.\.?\/)/.test(u)) return u;
    return null;
  }
  function mdInline(text, parent, opts, depth) {
    var rest = text;
    while (rest) {
      var m = INLINE_RE.exec(rest);
      if (!m) { parent.appendChild(document.createTextNode(rest)); return; }
      if (m.index) parent.appendChild(document.createTextNode(rest.slice(0, m.index)));
      rest = rest.slice(m.index + m[0].length);
      if (m[8] !== undefined) {
        // bare URL: leave trailing punctuation (and an unbalanced closing paren) outside the link
        var url = m[8], tail = url.match(/[.,;:!?'*_]+$|\)+$/);
        while (tail && (tail[0][0] !== ')' || (url.match(/\(/g) || []).length < (url.match(/\)/g) || []).length)) {
          url = url.slice(0, -1); rest = tail[0].slice(-1) + rest; tail = url.match(/[.,;:!?'*_]+$|\)+$/);
        }
        var bare = opts.noLinks ? null : safeHref(url);
        parent.appendChild(bare ? el('a', { href: bare, rel: 'noopener noreferrer', target: '_blank', text: url }) : document.createTextNode(url));
      } else if (m[1] !== undefined) {
        parent.appendChild(el('code', { text: m[1] }));
      } else if (m[2] !== undefined) {
        var href = opts.noLinks ? null : safeHref(m[3]);
        if (href) parent.appendChild(el('a', { href: href, rel: 'noopener noreferrer', target: /^https?:/i.test(href) ? '_blank' : null, text: m[2] }));
        else parent.appendChild(document.createTextNode(opts.noLinks ? m[2] : m[0]));
      } else {
        var strong = m[4] !== undefined || m[5] !== undefined;
        var inner = strong ? (m[4] !== undefined ? m[4] : m[5]) : (m[6] !== undefined ? m[6] : m[7]);
        var node = el(strong ? 'strong' : 'em');
        if (depth < 4) mdInline(inner, node, opts, depth + 1); else node.textContent = inner;
        parent.appendChild(node);
      }
    }
  }
  function mdBlocks(lines, parent, depth) {
    var i = 0, m;
    while (i < lines.length) {
      var line = lines[i];
      if (!line.trim()) { i++; continue; }
      if (/^```/.test(line)) {
        var code = []; i++;
        while (i < lines.length && !/^```\s*$/.test(lines[i])) code.push(lines[i++]);
        i++;
        parent.appendChild(el('pre', null, el('code', { text: code.join('\n') })));
      } else if ((m = /^(#{1,6})\s+(.*)$/.exec(line))) {
        var h = el('h' + Math.min(m[1].length + 2, 6), { class: 'mdh' });
        mdInline(m[2], h, {}, 0); parent.appendChild(h); i++;
      } else if (/^\s*>/.test(line)) {
        var quoted = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) quoted.push(lines[i++].replace(/^\s*> ?/, ''));
        var bq = el('blockquote');
        if (depth < 4) mdBlocks(quoted, bq, depth + 1); else bq.textContent = quoted.join('\n');
        parent.appendChild(bq);
      } else if (/^\s*[-*+]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
        var ordered = /^\s*\d+[.)]\s+/.test(line);
        var itemRe = ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-*+]\s+/;
        var list = el(ordered ? 'ol' : 'ul');
        while (i < lines.length && itemRe.test(lines[i])) {
          var li = el('li'); mdInline(lines[i].replace(itemRe, ''), li, {}, 0); list.appendChild(li); i++;
        }
        parent.appendChild(list);
      } else {
        var p = el('p');
        var first = true;
        while (i < lines.length && lines[i].trim() && (first || !BLOCK_START.test(lines[i]))) {
          if (!first) p.appendChild(el('br'));
          mdInline(lines[i], p, {}, 0); first = false; i++;
        }
        parent.appendChild(p);
      }
    }
  }
  function renderMarkdown(text) {
    var root = el('div', { class: 'md body' });
    mdBlocks(String(text).replace(/\r\n?/g, '\n').split('\n'), root, 0);
    return root;
  }
  // Inline markdown only (thread titles). noLinks when the title already sits inside a link.
  function renderInline(text, noLinks) {
    var span = el('span', { class: 'md-inline' });
    mdInline(String(text), span, { noLinks: noLinks }, 0);
    return span;
  }

  // ---------- attachments ----------
  var blobCache = {};
  function releaseBlobs() {
    Object.keys(blobCache).forEach(function (k) { blobCache[k].then(function (u) { URL.revokeObjectURL(u); }, function () {}); });
    blobCache = {};
    closeLightbox();
  }
  // <img> and <a> cannot send the bearer header, so fetch the file and use an object URL.
  function attachmentUrl(a) {
    if (!blobCache[a.id]) {
      blobCache[a.id] = fetch(a.url, { headers: { Authorization: 'Bearer ' + getToken() } }).then(function (r) {
        if (!r.ok) throw new ApiError(r.status, 'http_' + r.status, 'Could not load ' + a.filename);
        return r.blob();
      }).then(function (b) { return URL.createObjectURL(b); });
      blobCache[a.id].catch(function () { delete blobCache[a.id]; });
    }
    return blobCache[a.id];
  }
  var lightboxOpener = null;
  function closeLightbox() {
    var box = document.getElementById('lightbox');
    if (box) box.remove();
    document.removeEventListener('keydown', lightboxKey);
    if (lightboxOpener && document.contains(lightboxOpener)) lightboxOpener.focus();
    lightboxOpener = null;
  }
  function lightboxKey(ev) { if (ev.key === 'Escape') closeLightbox(); }
  function openLightbox(url, filename, opener) {
    closeLightbox();
    lightboxOpener = opener;
    var box = el('div', { id: 'lightbox', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Image preview: ' + filename, tabindex: '-1', onclick: closeLightbox },
      el('img', { src: url, alt: filename }));
    document.body.appendChild(box);
    document.addEventListener('keydown', lightboxKey);
    box.focus();
  }
  function attachmentsNode(m) {
    if (!m.attachments || !m.attachments.length) return null;
    var box = el('div', { class: 'attachments' });
    m.attachments.forEach(function (a) {
      if (INLINE_IMAGES.indexOf(a.content_type) >= 0) {
        var img = el('img', { class: 'thumb', alt: a.filename });
        var btn = el('button', { type: 'button', class: 'thumbbtn', 'aria-label': 'Open image ' + a.filename, title: a.filename }, img);
        attachmentUrl(a).then(function (u) {
          img.src = u;
          btn.addEventListener('click', function () { openLightbox(u, a.filename, btn); });
        }).catch(function () { btn.textContent = a.filename + ' (failed to load)'; });
        box.appendChild(btn);
      } else {
        box.appendChild(el('a', { class: 'attfile', href: a.url, download: a.filename, text: a.filename + ' (' + fmtSize(a.size) + ')', onclick: function (ev) {
          ev.preventDefault();
          attachmentUrl(a).then(function (u) {
            var dl = el('a', { href: u, download: a.filename }); document.body.appendChild(dl); dl.click(); dl.remove();
          }).catch(function (e) { toast(e.message, true); });
        } }));
      }
    });
    return box;
  }
  // Local draft for a text input: restored on build, saved on input, cleared() after a successful send.
  function persist(input, key) {
    var k = 'threaddit:draft:' + (me ? me.id : 0) + ':' + key;
    try { var saved = localStorage.getItem(k); if (saved !== null) input.value = saved; } catch (e) { /* storage unavailable */ }
    input.addEventListener('input', function () {
      try { if (input.value) localStorage.setItem(k, input.value); else localStorage.removeItem(k); } catch (e) { /* storage unavailable */ }
    });
    return function cleared() { try { localStorage.removeItem(k); } catch (e) { /* storage unavailable */ } };
  }
  // File input for thread/message forms: upload() sends not-yet-uploaded files and resolves to all ids.
  // The input sits behind a 📎 toggle; dropTarget(form) accepts files dragged onto the form.
  var pickerSeq = 0;
  function filePicker() {
    var files = [];
    var id = 'files-' + (++pickerSeq);
    var list = el('ul', { class: 'filelist' });
    var input = el('input', { type: 'file', multiple: true, id: id });
    var uploading = false;
    var panel = el('div', { class: 'field', hidden: true }, el('label', { for: id, text: 'Attach files (max 10, 10 MB each)' }), input);
    var toggle = el('button', { type: 'button', class: 'small', title: 'Attach files (or drop them on the form)', 'aria-label': 'Toggle attachments', 'aria-expanded': 'false', text: '📎', onclick: function () {
      panel.hidden = !panel.hidden; toggle.setAttribute('aria-expanded', String(!panel.hidden));
    } });
    function addFiles(fileList) {
      Array.prototype.forEach.call(fileList, function (file) {
        if (files.length >= MAX_ATTACHMENTS) { toast('At most ' + MAX_ATTACHMENTS + ' attachments.', true); return; }
        if (file.size > MAX_ATTACHMENT_BYTES) { toast(file.name + ' is larger than 10 MB.', true); return; }
        files.push({ file: file, id: null });
      });
      paintList();
    }
    function dropTarget(form) {
      var depth = 0;
      function hasFiles(ev) { return ev.dataTransfer && Array.prototype.indexOf.call(ev.dataTransfer.types, 'Files') >= 0; }
      form.addEventListener('dragenter', function (ev) { if (!hasFiles(ev) || input.disabled) return; depth++; form.classList.add('dragover'); });
      form.addEventListener('dragover', function (ev) { if (hasFiles(ev) && !input.disabled) ev.preventDefault(); });
      form.addEventListener('dragleave', function (ev) { if (!hasFiles(ev)) return; if (--depth <= 0) { depth = 0; form.classList.remove('dragover'); } });
      form.addEventListener('drop', function (ev) {
        if (!hasFiles(ev)) return;
        ev.preventDefault(); depth = 0; form.classList.remove('dragover');
        if (!input.disabled) addFiles(ev.dataTransfer.files);
      });
      return form;
    }
    function paintList() {
      clear(list);
      files.forEach(function (f, i) {
        list.appendChild(el('li', null, f.file.name + ' (' + fmtSize(f.file.size) + ') ',
          el('button', { type: 'button', class: 'small', 'aria-label': 'Remove ' + f.file.name, text: 'Remove', disabled: uploading, onclick: function () { if (uploading) return; files.splice(i, 1); paintList(); } })));
      });
    }
    input.addEventListener('change', function () { addFiles(input.files); input.value = ''; });
    function upload() {
      var batch = files.slice();
      uploading = true; input.disabled = true; paintList();
      return batch.reduce(function (p, f) {
        return p.then(function () {
          if (f.id) return null;
          return api('POST', '/api/attachments' + qs({ filename: f.file.name }), undefined, undefined,
            { blob: f.file, type: f.file.type || 'application/octet-stream' }).then(function (r) { f.id = r.id; });
        });
      }, Promise.resolve()).then(function (ids) {
        uploading = false; input.disabled = false; paintList();
        return batch.map(function (f) { return f.id; });
      }, function (e) {
        uploading = false; input.disabled = false; paintList();
        throw e;
      });
    }
    return { node: el('div', { class: 'attach' }, toggle, panel, list), toggle: toggle, upload: upload, dropTarget: dropTarget };
  }

  // ---------- @mention autocomplete ----------
  var usersPromise = null;
  function loadUsers() {
    if (!usersPromise) usersPromise = api('GET', '/api/users').then(function (r) { return r.users; }).catch(function () { usersPromise = null; return []; });
    return usersPromise;
  }
  // Wraps a textarea; typing @prefix shows approved users. Returns the wrapper to put in the DOM.
  function mentionable(ta) {
    var pop = el('div', { class: 'mention-pop hidden', role: 'listbox', 'aria-label': 'Mention suggestions' });
    var wrap = el('div', { class: 'mwrap' }, ta, pop);
    var items = [], active = 0, range = null;
    function close() { pop.classList.add('hidden'); clear(pop); items = []; range = null; }
    function paintPop() {
      clear(pop);
      items.forEach(function (u, i) {
        pop.appendChild(el('div', { class: 'mention-item' + (i === active ? ' active' : ''), role: 'option', 'aria-selected': i === active ? 'true' : 'false',
          onmousedown: function (ev) { ev.preventDefault(); choose(i); } },
          el('strong', { text: '@' + u.username }), ' ', badge(u.account_type), ' ',
          el('span', { class: 'mut', text: (u.description || '').slice(0, 60) })));
      });
    }
    function choose(i) {
      var u = items[i];
      if (!u || !range) return;
      var ins = '@' + u.username + ' ';
      ta.value = ta.value.slice(0, range.start) + ins + ta.value.slice(range.end);
      var pos = range.start + ins.length;
      close(); ta.focus(); ta.setSelectionRange(pos, pos);
    }
    function update() {
      var upto = ta.value.slice(0, ta.selectionStart);
      var m = /(^|[^A-Za-z0-9_-])@([A-Za-z0-9_-]*)$/.exec(upto);
      if (!m) { close(); return; }
      var prefix = m[2].toLowerCase();
      var found = { start: upto.length - m[2].length - 1, end: upto.length };
      loadUsers().then(function (users) {
        if (ta.value.slice(0, ta.selectionStart) !== upto) return;
        items = users.filter(function (u) { return u.username.toLowerCase().indexOf(prefix) === 0; }).slice(0, 8);
        if (!items.length) { close(); return; }
        range = found; active = 0; pop.classList.remove('hidden'); paintPop();
      });
    }
    ta.addEventListener('input', update);
    ta.addEventListener('blur', close);
    ta.addEventListener('keydown', function (ev) {
      if (pop.classList.contains('hidden') || !items.length) return;
      if (ev.key === 'ArrowDown') { ev.preventDefault(); active = (active + 1) % items.length; paintPop(); }
      else if (ev.key === 'ArrowUp') { ev.preventDefault(); active = (active + items.length - 1) % items.length; paintPop(); }
      else if ((ev.key === 'Enter' && !ev.metaKey && !ev.ctrlKey) || ev.key === 'Tab') { ev.preventDefault(); choose(active); }
      else if (ev.key === 'Escape') { ev.preventDefault(); close(); }
    });
    return wrap;
  }

  // ---------- chrome ----------
  function renderChrome() {
    var nav = document.getElementById('nav');
    var who = document.getElementById('whoami');
    clear(nav); clear(who);
    document.getElementById('searchform').classList.toggle('hidden', !me);
    if (!me) return;
    var h = location.hash || '#/';
    [['#/', 'Areas'], ['#/attention', 'Attention'], ['#/activity', 'Activity'], ['#/users', 'Users']]
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
    var descInput = el('textarea', { maxlength: 1000, rows: 3 });
    typeSel.addEventListener('change', function () { descInput.required = typeSel.value === 'agent'; });
    var regErr = el('div'); var regOut = el('div');
    var regForm = el('form', null, field('Username (3-32 letters, digits, _ or -)', nameInput, 'reg-name'), field('Account type', typeSel, 'reg-type'),
      field('Description (required for agents, shown on the Users page)', descInput, 'reg-desc'), regErr,
      el('button', { type: 'submit', class: 'primary', text: 'Register' }));
    formSubmit(regForm, regErr, function () {
      return api('POST', '/api/register', { username: nameInput.value.trim(), account_type: typeSel.value, description: descInput.value.trim() }, '').then(function (r) {
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
    me = null; usersPromise = null; renderChrome();
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
    releaseBlobs();
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
    else if (parts[0] === 'users') fn = viewUsers;
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
          el('a', { href: '#/area/' + areaRef(a), text: a.name, class: 't' }),
          el('div', { class: 'mut', text: a.active_threads + ' active · ' + a.closed_threads + ' closed' }),
          el('div', { class: 'mut', text: a.last_activity_at ? 'Last activity ' + fmt(a.last_activity_at) : 'No activity' }),
          el('p', { class: 'body mut', text: (a.description || '').slice(0, 160) })));
      });
      root.appendChild(g);
      return root;
    });
  }

  // ---------- area ----------
  // list score tint: >=5 red, 1-4 orange, 0 default, -1 to -4 faded, <= -5 nearly white
  function scoreClass(v) { return 'sc ' + (v >= 5 ? 'sc-hot' : v > 0 ? 'sc-warm' : v <= -5 ? 'sc-cold' : v < 0 ? 'sc-cool' : ''); }
  // onVoted(): called after a quick vote changed t.importance (used to re-sort the list)
  function threadRow(t, onVoted) {
    var link = el('a', { class: 't', href: '#/thread/' + t.id }, renderInline(t.title, true));
    var score = el('span', { text: String(t.importance) });
    // quick +/-1 on the OP (importance = OP score); closed threads are read-only
    function vote(d) {
      return t.closed ? null : el('button', { type: 'button', class: 'qv', 'aria-label': (d > 0 ? 'Upvote ' : 'Downvote ') + t.title, title: d > 0 ? '+1' : '-1', text: d > 0 ? '▲' : '▼', onclick: function (ev) {
        act(ev.currentTarget, function () { return api('POST', '/api/messages/' + t.op_message_id + '/votes', { delta: d }).then(function (r) { t.importance = r.score; score.textContent = String(r.score); imp.className = 'imp ' + scoreClass(r.score); if (onVoted) onVoted(); }); });
      } });
    }
    var imp = el('div', { class: 'imp ' + scoreClass(t.importance), title: 'Importance (OP score)' }, vote(1), score, el('small', { text: 'score' }), vote(-1));
    var row = el('div', { class: 'card thread' }, imp,
      el('div', { class: 'grow' },
        el('div', null, t.pinned ? el('span', { class: 'badge pin', text: 'pinned' }) : null, ' ',
          t.closed ? el('span', { class: 'badge closed', text: 'closed: ' + t.closed.reason }) : null, ' ',
          link, ' ', modified(t)),
        el('div', { class: 'mut' }, t.area_name + ' · ', userTag(t.owner), ' · ' + t.message_count + ' msgs · created ' + fmt(t.created_at) + ' · active ' + fmt(t.last_activity_at)),
        t.pending_attention ? el('span', { class: 'attn', text: t.pending_attention + ' need your attention' }) : null));
    row.thread = t;
    return row;
  }
  function viewArea(id, params) {
    var state = params.get('state') || 'active';
    var sort = params.get('sort') || 'importance';
    var dated = sort === 'created' || sort === 'activity';
    var order = dated && params.get('order') === 'asc' ? 'asc' : 'desc';
    return api('GET', '/api/areas/' + encodeURIComponent(id)).then(function (area) {
      return api('GET', '/api/threads' + qs({ area_id: area.id, state: state, sort: sort, order: order, limit: PAGE })).then(function (list) { return [area, list]; });
    }).then(function (rs) {
      var area = rs[0], list = rs[1];
      var page = el('div', { class: 'with-side' });
      var root = el('div', { class: 'main-col' });
      var slot = el('div');
      root.appendChild(el('div', { class: 'row' }, el('h1', { class: 'grow', text: area.name }),
        el('button', { type: 'button', text: 'Edit area', onclick: function () {
          if (slot.firstChild && slot.dataset.k === 'e') { clear(slot); return; }
          clear(slot); slot.dataset.k = 'e'; slot.appendChild(areaForm(area, function (a) {
            var q = location.hash.indexOf('?'), next = '#/area/' + areaRef(a) + (q >= 0 ? location.hash.slice(q) : '');
            if (location.hash === next) route(); else location.hash = next;
          }));
        } }),
        el('button', { type: 'button', class: 'primary', text: 'New thread', onclick: function () {
          if (slot.firstChild && slot.dataset.k === 't') { clear(slot); return; }
          clear(slot); slot.dataset.k = 't'; slot.appendChild(threadForm(area, function () { clear(slot); }));
        } })));
      page.appendChild(root);
      page.appendChild(el('aside', { class: 'side card', 'aria-label': 'Area description' }, el('h2', { text: 'About this area' }),
        area.description ? renderMarkdown(area.description) : el('div', { class: 'body', text: '(none)' })));
      root.appendChild(slot);
      function go(s, o, d) { location.hash = '#/area/' + id + qs({ state: s, sort: o, order: d === 'asc' ? 'asc' : '' }); }
      var sortSel = el('select', { onchange: function () { go(state, sortSel.value, order); } },
        [['importance', 'Importance'], ['activity', 'Recent activity'], ['created', 'Created']].map(function (o) {
          return el('option', { value: o[0], text: o[1], selected: o[0] === sort }); }));
      var orderSel = el('select', { id: 'ordersel', 'aria-label': 'Order', onchange: function () { go(state, sort, orderSel.value); } },
        [['desc', 'Newest first'], ['asc', 'Oldest first']].map(function (o) {
          return el('option', { value: o[0], text: o[1], selected: o[0] === order }); }));
      var stateSel = el('select', { onchange: function () { go(stateSel.value, sort, order); } },
        [['active', 'Active'], ['closed', 'Closed only'], ['all', 'Active + closed']].map(function (o) {
          return el('option', { value: o[0], text: o[1], selected: o[0] === state }); }));
      root.appendChild(el('div', { class: 'row' }, el('label', { for: 'sortsel', text: 'Sort' }), sortSel, dated ? orderSel : null, el('label', { for: 'statesel', text: 'Show' }), stateSel));
      sortSel.id = 'sortsel'; stateSel.id = 'statesel';
      // importance sort: re-order loaded rows 2s after the last quick vote (debounced), mirroring server order
      // (score, then last activity, then created, newest first)
      var resortTimer = null;
      function cmp(p, q) { return p < q ? -1 : p > q ? 1 : 0; }
      function resort() {
        [pinnedRows, rows].forEach(function (box) {
          Array.prototype.slice.call(box.children).sort(function (x, y) {
            var a = x.thread, b = y.thread;
            return (b.importance - a.importance) || cmp(b.last_activity_at, a.last_activity_at) || cmp(b.created_at, a.created_at) || (b.id - a.id);
          }).forEach(function (n) { box.appendChild(n); });
        });
      }
      function voted() { if (sort !== 'importance') return; clearTimeout(resortTimer); resortTimer = setTimeout(resort, RESORT_DELAY_MS); }
      var pinnedRows = el('div');
      if (list.pinned.length) { root.appendChild(el('h2', { text: 'Pinned' })); root.appendChild(pinnedRows); list.pinned.forEach(function (t) { pinnedRows.appendChild(threadRow(t, voted)); }); }
      root.appendChild(el('h2', { text: state === 'closed' ? 'Closed threads' : 'Threads' }));
      if (!list.threads.length && !list.pinned.length) root.appendChild(el('div', { class: 'empty', text: 'No threads here.' }));
      var rows = el('div'); var more = el('div'); var offset = 0;
      root.appendChild(rows); root.appendChild(more);
      function showPage(page) {
        page.threads.forEach(function (t) { rows.appendChild(threadRow(t, voted)); });
        offset += page.threads.length;
        clear(more);
        if (page.has_more) more.appendChild(el('button', { type: 'button', text: 'Load more threads', onclick: function (ev) {
          act(ev.currentTarget, function () {
            return api('GET', '/api/threads' + qs({ area_id: area.id, state: state, sort: sort, order: order, limit: PAGE, offset: offset })).then(showPage);
          });
        } }));
      }
      showPage(list);
      return page;
    });
  }
  function threadForm(area, close) {
    var title = el('input', { type: 'text', required: true, maxlength: 200 });
    var body = el('textarea', { required: true, maxlength: 20000 });
    var picker = filePicker();
    var err = el('div');
    var f = el('form', { class: 'card' }, el('h2', { text: 'New thread in ' + area.name }), field('Title', title, 'th-title'),
      field('Opening post (use @username to notify an agent)', body, 'th-body', mentionable(body)), picker.node, err, el('button', { type: 'submit', class: 'primary', text: 'Create thread' }), ' ',
      el('button', { type: 'button', text: 'Cancel', onclick: function () { clearTitle(); clearBody(); close(); } }));
    picker.dropTarget(f);
    var clearTitle = persist(title, 'thread:' + area.id + ':title'), clearBody = persist(body, 'thread:' + area.id + ':body');
    formSubmit(f, err, function () {
      return picker.upload().then(function (ids) {
        return api('POST', '/api/threads', { area_id: area.id, title: title.value.trim(), body: body.value, attachment_ids: ids });
      }).then(function (r) { clearTitle(); clearBody(); location.hash = '#/thread/' + r.thread.id; });
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
    var editing = false;
    var draft = null;
    function editForm() {
      var ta = el('textarea', { required: true, maxlength: 20000, 'aria-label': 'Edit message' }); ta.value = m.body;
      var clearStored = persist(ta, 'edit:' + m.id);
      if (draft !== null) ta.value = draft;
      ta.addEventListener('input', function () { draft = ta.value; });
      var err = el('div');
      var f = el('form', null, mentionable(ta), err, el('button', { type: 'submit', class: 'primary small', text: 'Save edit' }), ' ',
        el('button', { type: 'button', class: 'small', text: 'Cancel', onclick: function () { editing = false; draft = null; clearStored(); paint(); } }));
      formSubmit(f, err, function () {
        return api('PATCH', '/api/messages/' + m.id, { body: ta.value }).then(function (nm) { m.body = nm.body; m.edited_at = nm.edited_at; editing = false; draft = null; clearStored(); paint(); });
      });
      return f;
    }
    function paint() {
      var closed = ctx.closed || !!m.thread_closed_reason;
      clear(body);
      body.appendChild(el('div', { class: 'row' }, userTag(m.author),
        m.is_op ? el('span', { class: 'badge closed', text: 'OP' }) : null,
        el('span', { class: 'mut', text: fmt(m.created_at) }), modified(m),
        m.my_attention ? el('span', { class: 'attn', title: 'reason: ' + m.my_attention.reason, text: 'attention: ' + m.my_attention.status }) : null,
        links ? el('a', { href: ctxHref(m), text: 'context' }) : null));
      body.appendChild(editing ? editForm() : renderMarkdown(m.body));
      add(body, attachmentsNode(m));
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
      if (me.id === m.author.id) {
        body.appendChild(document.createTextNode(' '));
        body.appendChild(el('button', { type: 'button', class: 'small', disabled: closed || editing, text: 'Edit', onclick: function () { editing = true; paint(); } }));
      }
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
    var picker = filePicker();
    var err = el('div');
    var f = el('form', null, mentionable(ta), picker.node, err, el('button', { type: 'submit', class: 'primary small', text: 'Post reply' }));
    picker.dropTarget(f);
    var clearDraft = persist(ta, 'reply:' + parent.thread_id + ':' + parent.id);
    formSubmit(f, err, function () {
      return picker.upload().then(function (ids) {
        var body = { body: ta.value, attachment_ids: ids };
        if (parent !== null && parent.id) body.parent_id = parent.id;
        return api('POST', '/api/threads/' + parent.thread_id + '/messages', body);
      }).then(function (r) { clearDraft(); return done(r); });
    });
    return f;
  }

  // ---------- thread ----------
  function viewThread(id, targetParam) {
    return api('GET', '/api/threads/' + encodeURIComponent(id)).then(function (d) {
      var t = d.thread;
      var root = el('div');
      var ctx = { closed: !!t.closed, targetId: targetParam ? Number(targetParam) : null, added: function () { route(); } };
      root.appendChild(el('div', { class: 'mut' }, el('a', { href: '#/area/' + areaRef(t), text: t.area_name })));
      var titleSlot = el('div');
      function paintTitle() {
        clear(titleSlot);
        titleSlot.appendChild(el('div', { class: 'row' }, el('h1', { class: 'grow' }, renderInline(t.title, false), ' ', modified(t)),
          t.pinned ? el('span', { class: 'badge pin', text: 'pinned' }) : null));
      }
      function titleForm() {
        var input = el('input', { type: 'text', required: true, maxlength: 200, value: t.title, 'aria-label': 'Edit title' });
        var clearDraft = persist(input, 'title:' + t.id);
        var err = el('div');
        var f = el('form', { class: 'row' }, input, el('button', { type: 'submit', class: 'primary small', text: 'Save title' }), el('button', { type: 'button', class: 'small', text: 'Cancel', onclick: function () { clearDraft(); paintTitle(); } }), err);
        formSubmit(f, err, function () { return api('PATCH', '/api/threads/' + t.id, { title: input.value.trim() }).then(function () { clearDraft(); route(); }); });
        return f;
      }
      paintTitle();
      root.appendChild(titleSlot);
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
        controls.appendChild(el('button', { type: 'button', disabled: !!t.closed, text: 'Edit title', onclick: function () { clear(titleSlot); titleSlot.appendChild(titleForm()); titleSlot.querySelector('input').focus(); } }));
        controls.appendChild(el('button', { type: 'button', disabled: !!t.closed, text: t.pinned ? 'Unpin' : 'Pin to top', onclick: function (ev) {
          act(ev.currentTarget, function () { return api('PUT', '/api/threads/' + t.id + '/pin', { pinned: !t.pinned }).then(route); }); } }));
      }
      root.appendChild(controls);
      root.appendChild(el('h2', { text: 'Messages' }));
      var tree = buildTree(d.messages);
      if (!tree.length) root.appendChild(el('div', { class: 'empty', text: 'No messages.' }));
      tree.forEach(function (n) { root.appendChild(renderMsgNode(n, ctx, 0, true)); });
      var errSlot = el('div'); var ta = el('textarea', { required: true, maxlength: 20000 });
      var picker = filePicker();
      var f = el('form', { class: 'card' }, field(t.closed ? 'Thread closed: reopen to reply' : 'Add top-level reply (@username to notify an agent)', ta, 'top-reply', mentionable(ta)), picker.node, errSlot,
        el('button', { type: 'submit', class: 'primary', disabled: !!t.closed, text: 'Post' }));
      if (t.closed) ta.disabled = true;
      if (t.closed) { picker.node.querySelector('input').disabled = true; picker.toggle.disabled = true; }
      picker.dropTarget(f);
      var clearDraft = t.closed ? function () {} : persist(ta, 'top:' + t.id);
      formSubmit(f, errSlot, function () {
        return picker.upload().then(function (ids) { return api('POST', '/api/threads/' + t.id + '/messages', { body: ta.value, attachment_ids: ids }); }).then(function () { clearDraft(); route(); });
      });
      root.appendChild(f);
      return root;
    });
  }

  // ---------- context ----------
  function viewContext(id) {
    return api('GET', '/api/messages/' + encodeURIComponent(id) + '/context').then(function (c) {
      var root = el('div');
      var closed = !!c.thread.closed;
      root.appendChild(el('div', { class: 'mut' }, el('a', { href: '#/area/' + areaRef(c.area), text: c.area.name })));
      root.appendChild(el('h1', null, renderInline(c.thread.title, false), ' ', modified(c.thread)));
      root.appendChild(el('div', { class: 'card' }, el('div', { class: 'mut', text: 'Area description / instructions' }), c.area.description ? renderMarkdown(c.area.description) : el('div', { class: 'body', text: '(none)' })));
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
          box.appendChild(el('div', { class: 'mut' }, m.area_name + ' › ', el('a', { href: '#/thread/' + m.thread_id }, renderInline(m.thread_title, true)), ' · reason: ' + (m.my_attention ? m.my_attention.reason : ''), ' ',
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
        areas: { title: 'Areas', draw: function (a) { return el('div', { class: 'card' }, el('a', { href: '#/area/' + areaRef(a), text: a.name }), el('div', { class: 'body mut', text: a.snippet })); } },
        threads: { title: 'Threads', draw: function (t) { return el('div', { class: 'card' }, el('a', { href: '#/thread/' + t.id }, renderInline(t.title, true)), ' ', modified(t), ' ', el('span', { class: 'mut', text: t.area_name }), t.closed_reason ? el('span', { class: 'badge closed', text: ' closed: ' + t.closed_reason }) : null); } },
        messages: { title: 'Messages', draw: function (m) {
          return el('div', { class: 'card' },
            el('div', { class: 'mut' }, m.area_name + ' › ', el('a', { href: '#/thread/' + m.thread_id }, renderInline(m.thread_title, true)), ' · ', userTag(m.author), ' · ' + fmt(m.created_at), ' ', modified(m),
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
    message_edited: 'edited a message in', thread_edited: 'edited thread', thread_closed: 'closed thread', thread_reopened: 'reopened thread', thread_pinned: 'pinned thread', thread_unpinned: 'unpinned thread' };
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
            : e.thread_id ? '#/thread/' + e.thread_id : e.area_id ? '#/area/' + areaRef(e) : '#/';
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

  // ---------- users ----------
  function viewUsers() {
    return api('GET', '/api/users').then(function (r) {
      var root = el('div'); root.appendChild(el('h1', { text: 'Users' }));
      r.users.forEach(function (u) {
        var card = el('div', { class: 'card user' });
        function paintUser() {
          clear(card);
          card.appendChild(el('div', { class: 'row' }, el('div', { class: 'grow' }, userTag(u), u.id === me.id ? el('span', { class: 'mut', text: ' (you)' }) : null),
            u.id === me.id ? el('button', { type: 'button', class: 'small', text: 'Edit description', onclick: function () { clear(card); card.appendChild(descForm()); } }) : null));
          card.appendChild(el('div', { class: 'body userdesc' + (u.description ? '' : ' mut'), text: u.description || '(no description)' }));
        }
        function descForm() {
          var ta = el('textarea', { maxlength: 1000, 'aria-label': 'Your description', required: u.account_type === 'agent' }); ta.value = u.description;
          var err = el('div');
          var f = el('form', null, el('div', null, userTag(u)), ta, err, el('button', { type: 'submit', class: 'primary small', text: 'Save description' }), ' ',
            el('button', { type: 'button', class: 'small', text: 'Cancel', onclick: paintUser }));
          formSubmit(f, err, function () {
            return api('PATCH', '/api/me', { description: ta.value.trim() }).then(function (nu) { u.description = nu.description; me.description = nu.description; usersPromise = null; paintUser(); });
          });
          return f;
        }
        paintUser();
        root.appendChild(card);
      });
      return root;
    });
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
