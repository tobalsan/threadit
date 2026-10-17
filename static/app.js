'use strict';
(function () {
  var TIMEOUT_MS = 15000;
  var PAGE = 100;
  var SEARCH_PAGE = 50;
  var TOKEN_KEY = 'threadit_token';
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
  // short relative time for lists; the full date goes in a title attribute
  function ago(ts) {
    var d = new Date(ts);
    if (isNaN(d)) return String(ts);
    var s = (Date.now() - d.getTime()) / 1000;
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + 'm ago';
    if (s < 86400) return Math.floor(s / 3600) + 'h ago';
    if (s < 30 * 86400) return Math.floor(s / 86400) + 'd ago';
    return d.toLocaleDateString();
  }
  // long form for the inspector: "3 days ago", "2 hours ago"
  var RELATIVE_UNITS = [['year', 31536000], ['month', 2592000], ['week', 604800], ['day', 86400], ['hour', 3600], ['minute', 60]];
  var relFmt = new Intl.RelativeTimeFormat(undefined, { numeric: 'always' });
  function agoLong(ts) {
    var d = new Date(ts);
    if (isNaN(d)) return String(ts);
    var s = (Date.now() - d.getTime()) / 1000;
    if (s < 60) return 'just now';
    var u = RELATIVE_UNITS.filter(function (x) { return s >= x[1]; })[0];
    return relFmt.format(-Math.floor(s / u[1]), u[0]);
  }
  function who(u) {
    return el('span', { class: 'who' }, u.username, u.account_type === 'agent' ? el('span', { class: 'ag', title: 'Agent', 'aria-label': '(agent)', text: '✦' }) : null);
  }
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
    var k = 'threadit:draft:' + (me ? me.id : 0) + ':' + key;
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
    return { node: el('div', { class: 'attach' }, toggle, panel, list), toggle: toggle, upload: upload, dropTarget: dropTarget, count: function () { return files.length; } };
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

  // ---------- theme ----------
  var SVG_NS = 'http://www.w3.org/2000/svg';
  var THEME_KEY = 'threadit:theme';
  var THEMES = [['system', 'System', 'M3 4.5h18v11.5H3zM8.5 20h7M12 16v4'],
    ['light', 'Light', 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4'],
    ['dark', 'Dark', 'M20.5 14.5A8.5 8.5 0 1 1 9.5 3.5a7 7 0 0 0 11 11z']];
  var darkQuery = window.matchMedia('(prefers-color-scheme: dark)');
  function themePref() {
    var v = null;
    try { v = localStorage.getItem(THEME_KEY); } catch (e) { /* storage unavailable */ }
    return v === 'light' || v === 'dark' ? v : 'system';
  }
  function applyTheme() {
    var pref = themePref();
    document.documentElement.setAttribute('data-theme', pref === 'system' ? (darkQuery.matches ? 'dark' : 'light') : pref);
  }
  function setTheme(pref) {
    try { localStorage.setItem(THEME_KEY, pref); } catch (e) { /* storage unavailable: session only */ }
    applyTheme(); paintThemeSeg();
  }
  function paintThemeSeg() {
    var seg = document.getElementById('themeseg');
    var cur = themePref();
    clear(seg);
    THEMES.forEach(function (t, i) {
      var b = el('button', { type: 'button', role: 'radio', 'aria-checked': String(t[0] === cur), 'aria-label': t[1], title: t[1], tabindex: t[0] === cur ? '0' : '-1',
        onclick: function () { setTheme(t[0]); seg.children[i].focus(); } }, svgIcon(t[2]));
      seg.appendChild(b);
    });
  }
  document.getElementById('themeseg').addEventListener('keydown', function (ev) {
    var d = ev.key === 'ArrowRight' || ev.key === 'ArrowDown' ? 1 : ev.key === 'ArrowLeft' || ev.key === 'ArrowUp' ? -1 : 0;
    if (!d) return;
    ev.preventDefault();
    var i = THEMES.map(function (t) { return t[0]; }).indexOf(themePref());
    setTheme(THEMES[(i + d + THEMES.length) % THEMES.length][0]);
    document.getElementById('themeseg').children[(i + d + THEMES.length) % THEMES.length].focus();
  });
  if (darkQuery.addEventListener) darkQuery.addEventListener('change', applyTheme);
  applyTheme(); paintThemeSeg();

  // ---------- chrome ----------
  var NAV_ICONS = { Home: ['#0a84ff', 'M3 11 12 4l9 7M5 10v10h14V10'], Areas: ['#ff9f0a', 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z'],
    Attention: ['#ff375f', 'M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 21h4'], Activity: ['#30a14e', 'M3 12h4l3-8 4 16 3-8h4'],
    Users: ['#bf5af2', 'M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2 20c0-4 3-6 7-6s7 2 7 6M17 5a3 3 0 0 1 0 6M19 14c2 .7 3 2.5 3 5'],
    Admin: ['#7c7c82', 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z'] };
  var CHECK_PATH = 'M5 12.5l4.5 4.5L19 7.5';
  function svgIcon(d) {
    var svg = document.createElementNS(SVG_NS, 'svg');
    var path = document.createElementNS(SVG_NS, 'path');
    [['viewBox', '0 0 24 24'], ['fill', 'none'], ['stroke', 'currentColor'], ['stroke-width', '1.8'], ['stroke-linecap', 'round'], ['stroke-linejoin', 'round'], ['aria-hidden', 'true']]
      .forEach(function (a) { svg.setAttribute(a[0], a[1]); });
    path.setAttribute('d', d);
    svg.appendChild(path);
    return svg;
  }
  function navIcon(name) {
    return el('span', { class: 'ic', style: 'color:' + NAV_ICONS[name][0] }, svgIcon(NAV_ICONS[name][1]));
  }
  var attentionCount = 0;
  function refreshAttentionCount() {
    if (!me) return;
    api('GET', '/api/attention' + qs({ status: 'unacknowledged', limit: PAGE })).then(function (r) {
      attentionCount = r.items.length + (r.has_more ? 1 : 0);
      attentionHasMore = r.has_more;
      if (me) paintAttentionBadge();
    }).catch(function () { /* the badge is optional */ });
  }
  var attentionHasMore = false;
  function paintNav() {
    var nav = document.getElementById('nav');
    var h = location.hash || '#/';
    clear(nav);
    [['#/', 'Home'], ['#/areas', 'Areas'], ['#/attention', 'Attention'], ['#/activity', 'Activity'], ['#/users', 'Users']]
      .concat(me.is_superadmin ? [['#/admin', 'Admin']] : []).forEach(function (l) {
        var cur = l[0] === '#/' ? (h === '#/' || h.indexOf('#/?') === 0) : l[0] === '#/areas' ? (h.indexOf('#/area') === 0 || h.indexOf('#/thread') === 0) : h.indexOf(l[0]) === 0;
        var count = l[1] === 'Attention' ? attentionBadgeText() : null;
        nav.appendChild(el('a', { href: l[0], 'aria-current': cur ? 'page' : null, 'aria-label': l[1] + (count ? ', ' + count + ' need your attention' : '') }, navIcon(l[1]), el('span', { class: 't', text: l[1] }),
          count ? el('span', { class: 'navcount', 'aria-hidden': 'true', text: count }) : null));
      });
  }
  function attentionBadgeText() {
    return attentionCount > 0 ? (attentionHasMore ? (attentionCount - 1) + '+' : String(attentionCount)) : null;
  }
  // update only the badge: rebuilding the links would drop keyboard focus
  function paintAttentionBadge() {
    var link = document.querySelector('#nav a[href="#/attention"]');
    if (!link) return;
    var count = attentionBadgeText();
    var badge = link.querySelector('.navcount');
    if (badge) badge.remove();
    if (count) link.appendChild(el('span', { class: 'navcount', 'aria-hidden': 'true', text: count }));
    link.setAttribute('aria-label', 'Attention' + (count ? ', ' + count + ' need your attention' : ''));
  }
  function renderChrome() {
    var box = document.getElementById('whoami');
    clear(box);
    document.body.classList.toggle('anon', !me);
    if (!me) { clear(document.getElementById('nav')); setInspector(null); return; }
    paintNav();
    box.appendChild(el('div', { class: 'me' }, el('div', { class: 'avatar' + (me.account_type === 'agent' ? ' agent' : ''), 'aria-hidden': 'true', text: me.username.charAt(0).toUpperCase() }),
      el('span', { class: 'nm' }, who(me)), me.is_superadmin ? el('span', { class: 'badge super', text: 'superadmin' }) : null));
    box.appendChild(el('button', { type: 'button', class: 'lo', 'aria-label': 'Log out', title: 'Log out', onclick: function () { setToken(null); attentionCount = 0; location.hash = '#/'; boot(); } },
      svgIcon('M12 3v8M7.5 6.2a7 7 0 1 0 9 0')));
  }
  // toolbar: page title and the "New thread" button (shown by views that give a handler)
  var PAGE_TITLES = { '': 'Home', areas: 'Areas', area: 'Area', thread: 'Thread', context: 'Thread', attention: 'Attention', activity: 'Activity', search: 'Search', users: 'Users', admin: 'Admin' };
  function setToolbar(title) { document.getElementById('bartitle').textContent = title; }

  // ---------- inspector ----------
  // A thread view gives build(panel); the panel stays closed until the toolbar button opens it.
  var inspBuild = null, inspOpen = false;
  function paintInspector() {
    var panel = document.getElementById('insp');
    var btn = document.getElementById('inspbtn');
    var open = inspOpen && !!inspBuild;
    btn.hidden = !inspBuild;
    btn.setAttribute('aria-pressed', String(open));
    panel.hidden = !open;
    if (!open) return;
    var focused = document.activeElement && panel.contains(document.activeElement) ? document.activeElement.getAttribute('aria-label') : null;
    clear(panel);
    inspBuild(panel);
    if (focused) {
      var again = Array.prototype.filter.call(panel.querySelectorAll('[aria-label]'), function (n) { return n.getAttribute('aria-label') === focused; })[0];
      if (again) again.focus();
    }
  }
  function setInspector(build) { inspBuild = build; paintInspector(); }
  function toggleInspector() { if (!inspBuild) return; inspOpen = !inspOpen; paintInspector(); }
  function closeInspector(refocus) {
    if (!inspOpen) return;
    var panel = document.getElementById('insp');
    var inside = panel.contains(document.activeElement);
    inspOpen = false; paintInspector();
    if (refocus && inside) document.getElementById('inspbtn').focus();
  }
  document.getElementById('inspbtn').addEventListener('click', toggleInspector);
  document.addEventListener('mousedown', function (ev) {
    if (!inspOpen || document.getElementById('insp').contains(ev.target) || document.getElementById('inspbtn').contains(ev.target)
      || ev.target.closest('.pop,.tapback,.scrim,.sheet,#lightbox,#toast,dialog')) return;
    closeInspector(false);
  });
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && !document.getElementById('lightbox')) closeInspector(true);
  });

  // ---------- command palette ----------
  var THREAD_ICON = 'M4 5h16v11H9l-5 4z', BOLT_ICON = 'M13 3 5 14h6l-1 7 8-11h-6z';
  var PALETTE_GROUPS = ['Threads', 'Areas', 'Screens', 'Actions', 'Search'];
  var PALETTE_GROUP_MAX = 6;
  var PALETTE_DEBOUNCE_MS = 200;
  var palette = null;
  // subsequence match: higher is better, -1 means no match
  function fuzzy(q, s) {
    q = q.toLowerCase(); s = s.toLowerCase();
    var qi = 0, score = 0, run = 0, last = -2;
    for (var i = 0; i < s.length && qi < q.length; i++) {
      if (s[i] === q[qi]) { score += 1 + (i === 0 || s[i - 1] === ' ' ? 3 : 0) + (last === i - 1 ? 2 + run : 0); run = last === i - 1 ? run + 1 : 0; last = i; qi++; }
    }
    return qi === q.length ? score - s.length * 0.01 : -1;
  }
  function goHash(h) { if (location.hash === h) route(); else location.hash = h; }
  function paletteActions() {
    var dark = document.documentElement.getAttribute('data-theme') === 'dark';
    var out = [];
    out.push(['Create thread', function () { openNewThread(); }]);
    if (inspBuild) out.push(['Toggle inspector', toggleInspector]);
    out.push([dark ? 'Switch to light mode' : 'Switch to dark mode', function () { setTheme(dark ? 'light' : 'dark'); }]);
    out.push(['Use system appearance', function () { setTheme('system'); }]);
    return out;
  }
  function closePalette(skipFocus) {
    if (!palette) return;
    var p = palette;
    palette = null;
    clearTimeout(p.timer);
    p.node.remove();
    if (!skipFocus && p.prev && document.contains(p.prev)) p.prev.focus();
  }
  function openPalette() {
    if (!me) return;
    if (palette) { closePalette(false); return; }
    closePop(false);
    var prev = document.activeElement, sel = 0, flat = [], seq = 0, shown = null;
    var threads = [], areas = [];
    var screens = [['Home', '#/'], ['Areas', '#/areas'], ['Attention', '#/attention'], ['Activity', '#/activity'], ['Users', '#/users']].concat(me.is_superadmin ? [['Admin', '#/admin']] : []);
    var input = el('input', { type: 'text', role: 'combobox', 'aria-expanded': 'true', 'aria-controls': 'pal-list', 'aria-autocomplete': 'list', 'aria-label': 'Search threads, areas, screens and actions',
      placeholder: 'Search threads, areas, actions…', autocomplete: 'off', spellcheck: 'false' });
    var list = el('div', { id: 'pal-list', class: 'res', role: 'listbox', 'aria-label': 'Results' });
    var box = el('div', { class: 'palette glass', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Command palette' },
      el('div', { class: 'pin-row' }, svgIcon('M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-3.5-3.5'), input, el('kbd', { 'aria-hidden': 'true', text: 'esc' })), list,
      el('div', { class: 'pfoot', 'aria-hidden': 'true' }, el('span', null, el('kbd', { text: '↑↓' }), ' select'), el('span', null, el('kbd', { text: '↵' }), ' open'), el('span', null, el('kbd', { text: 'esc' }), ' close')));
    var scrim = el('div', { class: 'scrim' }, box);
    function mark() {
      Array.prototype.forEach.call(list.querySelectorAll('.it'), function (n, i) {
        n.setAttribute('aria-selected', String(i === sel));
        if (i === sel) { input.setAttribute('aria-activedescendant', n.id); n.scrollIntoView({ block: 'nearest' }); }
      });
    }
    function pick(it) {
      closePalette(true);
      it.run();
      // an action that neither navigates nor opens a dialog leaves no focus: give it back
      if (prev && document.contains(prev) && (!document.activeElement || document.activeElement === document.body)) prev.focus();
    }
    function build(resetSel) {
      var q = input.value.trim(), groups = {};
      function put(g, icon, label, sub, run, score) { (groups[g] = groups[g] || []).push({ icon: icon, label: label, sub: sub, run: run, s: score }); }
      threads.forEach(function (t) { put('Threads', THREAD_ICON, t.title, t.area_name, function () { goHash('#/thread/' + t.id); }, 0); });
      if (q) areas.forEach(function (a) {
        var s = fuzzy(q, a.name);
        if (s >= 0) put('Areas', NAV_ICONS.Areas[1], a.name, a.active_threads + ' active', function () { goHash('#/area/' + areaRef(a)); }, s);
      });
      screens.forEach(function (sc) {
        var s = q ? fuzzy(q, sc[0]) : 0;
        if (s >= 0) put('Screens', NAV_ICONS[sc[0]][1], sc[0], 'Go to', function () { goHash(sc[1]); }, s);
      });
      paletteActions().forEach(function (a) {
        var s = q ? fuzzy(q, a[0]) : 0;
        if (s >= 0) put('Actions', BOLT_ICON, a[0], 'Action', a[1], s);
      });
      if (q) areas.forEach(function (a) {
        var s = fuzzy(q, 'Create thread in ' + a.name);
        if (s >= 0) put('Actions', BOLT_ICON, 'Create thread in ' + a.name, 'Action', function () { openNewThread(a.id); }, s);
      });
      if (q) put('Search', 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-3.5-3.5', 'Search for “' + q + '”', 'All results', function () { goHash('#/search' + qs({ q: q })); }, 0);
      var rows = [];
      PALETTE_GROUPS.forEach(function (g) {
        var items = groups[g];
        if (!items) return;
        if (q && g !== 'Threads') items.sort(function (a, b) { return b.s - a.s; });
        rows.push({ group: g });
        items.slice(0, PALETTE_GROUP_MAX).forEach(function (it) { rows.push({ item: it }); });
      });
      // keep the nodes when nothing changed, so a late response does not replace an option under the pointer
      var sig = JSON.stringify(rows.map(function (r) { return r.group || [r.item.label, r.item.sub]; }));
      flat = rows.filter(function (r) { return r.item; }).map(function (r) { return r.item; });
      if (sig !== shown) {
        shown = sig;
        clear(list);
        var idx = 0;
        rows.forEach(function (r) {
          if (r.group) { list.appendChild(el('div', { class: 'grp-l', role: 'presentation', text: r.group })); return; }
          var it = r.item, at = idx++;
          list.appendChild(el('div', { class: 'it', role: 'option', id: 'pal-opt-' + at, 'aria-selected': 'false',
            onmousemove: function () { if (sel !== at) { sel = at; mark(); } }, onclick: function () { pick(flat[at]); } },
            el('span', { class: 'pi' }, svgIcon(it.icon)), el('span', { class: 'lb', text: it.label }), el('small', { text: it.sub })));
        });
        if (!flat.length) list.appendChild(el('div', { class: 'none', text: 'No results' }));
      }
      if (resetSel) sel = 0;
      sel = Math.min(sel, Math.max(0, flat.length - 1));
      mark();
    }
    function fetchThreads() {
      var q = input.value.trim(), mine = ++seq;
      var req = q ? api('GET', '/api/search' + qs({ q: q, limit: PALETTE_GROUP_MAX })).then(function (r) { return r.threads; })
        : api('GET', '/api/threads' + qs({ sort: 'hot', state: 'active', limit: 4 })).then(function (r) { return r.threads; });
      req.then(function (found) { if (mine === seq && palette) { threads = found; build(false); } }, function () { /* the other groups still work */ });
    }
    input.addEventListener('input', function () {
      seq++; threads = []; build(true);
      clearTimeout(palette.timer);
      palette.timer = setTimeout(fetchThreads, PALETTE_DEBOUNCE_MS);
    });
    scrim.addEventListener('mousedown', function (ev) { if (ev.target === scrim) closePalette(false); });
    scrim.addEventListener('keydown', function (ev) {
      if (ev.key === 'ArrowDown') { ev.preventDefault(); if (flat.length) { sel = (sel + 1) % flat.length; mark(); } }
      else if (ev.key === 'ArrowUp') { ev.preventDefault(); if (flat.length) { sel = (sel + flat.length - 1) % flat.length; mark(); } }
      else if (ev.key === 'Enter') { ev.preventDefault(); if (flat[sel]) pick(flat[sel]); }
      else if (ev.key === 'Escape') { ev.stopPropagation(); closePalette(false); }
      else if (ev.key === 'Tab') ev.preventDefault();
    });
    document.body.appendChild(scrim);
    palette = { node: scrim, prev: prev, timer: null, hash: location.hash };
    build(true);
    input.focus();
    api('GET', '/api/areas').then(function (r) { areas = r.areas; if (palette && palette.node === scrim) build(false); }, function () { /* areas are optional here */ });
    fetchThreads();
  }
  document.getElementById('searchbtn').addEventListener('click', openPalette);
  document.addEventListener('keydown', function (ev) {
    if ((ev.metaKey || ev.ctrlKey) && !ev.altKey && ev.key.toLowerCase() === 'k') { ev.preventDefault(); openPalette(); }
  });

  // ---------- new thread sheet ----------
  var LAST_AREA_KEY = 'threadit:lastarea';
  var AREA_COLORS = ['orange', 'blue', 'green', 'purple'];
  var currentAreaId = null;
  var sheet = null;
  function areaTile(a) { return el('span', { class: 'tile c-' + AREA_COLORS[a.id % AREA_COLORS.length], 'aria-hidden': 'true', text: a.name.charAt(0).toUpperCase() }); }
  function firstLine(text) { return String(text || '').split('\n')[0].replace(/[*`_#>]/g, '').trim(); }
  function lastAreaId() {
    try { return Number(localStorage.getItem(LAST_AREA_KEY + ':' + me.id)) || null; } catch (e) { return null; }
  }
  function rememberArea(id) { try { localStorage.setItem(LAST_AREA_KEY + ':' + me.id, String(id)); } catch (e) { /* storage unavailable */ } }
  function sheetOutside(ev) {
    var btn = document.getElementById('newbtn');
    if (sheet && !sheet.node.contains(ev.target) && !btn.contains(ev.target) && !ev.target.closest('.scrim,#lightbox,#toast,dialog')) closeSheet(false);
  }
  function removeSheet() {
    var s = sheet;
    sheet = null;
    if (s) s.node.remove();
    document.removeEventListener('mousedown', sheetOutside, true);
    document.getElementById('newbtn').setAttribute('aria-expanded', 'false');
    return s;
  }
  function closeSheet(refocus) {
    var s = removeSheet();
    if (s && refocus) {
      var back = s.prev && document.contains(s.prev) ? s.prev : document.getElementById('newbtn');
      back.focus();
    }
  }
  // areaId: preselected area; otherwise the current page's area, then the last one used
  function openNewThread(areaId) {
    closePop(false);
    var prev = document.activeElement;
    removeSheet();
    return api('GET', '/api/areas').then(function (r) {
      if (!me) return;
      var want = areaId || currentAreaId || lastAreaId();
      var cur = r.areas.filter(function (a) { return a.id === want; })[0] || null;
      showSheet(r.areas, cur, prev, !cur);
    }).catch(function (e) { toast(e.message || String(e), true); });
  }
  function showSheet(areas, cur, prev, openList, carry) {
    removeSheet();
    var newBtn = document.getElementById('newbtn');
    var title = el('input', { type: 'text', class: 'tin', required: true, maxlength: 200, autocomplete: 'off' });
    var body = el('textarea', { required: true, maxlength: 20000 });
    var picker = carry ? carry.picker : filePicker();
    var err = el('div');
    var areaBtn = el('button', { type: 'button', class: 'apick', 'aria-haspopup': 'listbox', 'aria-expanded': 'false',
      'aria-label': cur ? 'Area: ' + cur.name : 'Area: choose one' },
      cur ? areaTile(cur) : null, el('span', null, cur ? [el('b', { text: cur.name }), el('span', { class: 'ct', text: cur.active_threads + ' active' })] : el('b', { text: 'Choose an area' })),
      el('span', { class: 'chev', 'aria-hidden': 'true', text: '▾' }));
    var areaFld = el('div', { class: 'fld' }, el('span', { class: 'fl', text: 'Area' }), areaBtn);
    var clearTitle = function () {}, clearBody = function () {};
    if (cur) { clearTitle = persist(title, 'thread:' + cur.id + ':title'); clearBody = persist(body, 'thread:' + cur.id + ':body'); }
    // choosing an area rebuilds the sheet: keep what the user already typed and attached
    if (carry) {
      [[title, carry.title], [body, carry.body]].forEach(function (p) {
        if (!p[1]) return;
        p[0].value = p[1];
        p[0].dispatchEvent(new Event('input'));
      });
    }
    var form = el('form', { class: 'sheet glass', role: 'dialog', 'aria-label': 'New thread' },
      el('h2', { text: 'New thread' }), areaFld,
      el('div', { class: 'fld' }, el('label', { for: 'th-title', text: 'Title' }), title),
      el('div', { class: 'fld' }, el('label', { for: 'th-body', text: 'Opening post (use @username to notify an agent)' }), mentionable(body)),
      picker.node, err,
      el('div', { class: 'row2' }, el('button', { type: 'button', text: 'Cancel', onclick: function () { cancelSheet(); } }),
        el('button', { type: 'submit', class: 'primary', text: 'Create thread ' }, el('kbd', { 'aria-hidden': 'true', text: '⌘↵' }))));
    title.id = 'th-title'; body.id = 'th-body';
    picker.dropTarget(form);
    formSubmit(form, err, function () {
      if (!cur) throw new Error('Choose an area first.');
      return picker.upload().then(function (ids) {
        return api('POST', '/api/threads', { area_id: cur.id, title: title.value.trim(), body: body.value, attachment_ids: ids });
      }).then(function (r) { clearTitle(); clearBody(); rememberArea(cur.id); closeSheet(false); location.hash = '#/thread/' + r.thread.id; });
    });
    title.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); var b = form.querySelector('button[type=submit]'); if (!b.disabled) form.requestSubmit(); }
    });
    var cancelSheet = guardedCancel(function () { return title.value.trim() !== '' || body.value.trim() !== '' || picker.count() > 0; },
      function () { clearTitle(); clearBody(); closeSheet(true); });
    escCancels(form, cancelSheet);

    // searchable area combobox
    var drop = null;
    function closeDrop(focusBtn) {
      if (!drop) return;
      drop.remove(); drop = null;
      areaBtn.setAttribute('aria-expanded', 'false');
      if (focusBtn) areaBtn.focus();
    }
    function openDrop() {
      if (drop) return;
      var items = [], sel = 0;
      var input = el('input', { type: 'text', role: 'combobox', 'aria-expanded': 'true', 'aria-controls': 'area-list', 'aria-autocomplete': 'list', 'aria-label': 'Filter areas', placeholder: 'Find an area…', autocomplete: 'off' });
      var list = el('div', { id: 'area-list', class: 'lst', role: 'listbox', 'aria-label': 'Areas' });
      drop = el('div', { class: 'adrop' }, input, list);
      function mark() {
        Array.prototype.forEach.call(list.querySelectorAll('.opt'), function (n, i) {
          n.setAttribute('aria-selected', String(i === sel));
          if (i === sel) { input.setAttribute('aria-activedescendant', n.id); n.scrollIntoView({ block: 'nearest' }); }
        });
      }
      function choose(a) {
        if (cur && a.id === cur.id) { closeDrop(false); title.focus(); return; }
        rememberArea(a.id);
        showSheet(areas, a, prev, false, { title: title.value, body: body.value, picker: picker });
      }
      function build() {
        var q = input.value.trim();
        clear(list);
        items = areas.map(function (a) { return { a: a, s: q ? fuzzy(q, a.name + ' ' + firstLine(a.description)) : 0 }; })
          .filter(function (x) { return x.s >= 0; }).sort(function (x, y) { return y.s - x.s; }).map(function (x) { return x.a; });
        items.forEach(function (a, i) {
          list.appendChild(el('div', { class: 'opt', role: 'option', id: 'area-opt-' + i, 'aria-selected': 'false',
            onmousemove: function () { if (sel !== i) { sel = i; mark(); } }, onclick: function () { choose(a); } },
            areaTile(a), el('span', { class: 'tx' }, el('b', { text: a.name }), el('small', { text: firstLine(a.description) })), el('span', { class: 'ct', text: a.active_threads + ' active' })));
        });
        if (!items.length) list.appendChild(el('div', { class: 'none', text: areas.length ? 'No matching area' : 'No areas yet. Create one on the Areas page.' }));
        sel = q || !cur ? 0 : Math.max(0, items.indexOf(cur));
        mark();
      }
      input.addEventListener('input', build);
      input.addEventListener('keydown', function (ev) {
        if (ev.key === 'ArrowDown') { ev.preventDefault(); if (items.length) { sel = (sel + 1) % items.length; mark(); } }
        else if (ev.key === 'ArrowUp') { ev.preventDefault(); if (items.length) { sel = (sel + items.length - 1) % items.length; mark(); } }
        else if (ev.key === 'Enter') { ev.preventDefault(); ev.stopPropagation(); if (items[sel]) choose(items[sel]); }
        else if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); closeDrop(true); }
        else if (ev.key === 'Tab') ev.preventDefault();
      });
      areaFld.appendChild(drop);
      areaBtn.setAttribute('aria-expanded', 'true');
      build();
      input.focus();
    }
    areaBtn.addEventListener('click', function () { if (drop) closeDrop(true); else openDrop(); });
    areaBtn.addEventListener('keydown', function (ev) { if (ev.key === 'ArrowDown') { ev.preventDefault(); openDrop(); } });

    document.body.appendChild(form);
    var r = newBtn.getBoundingClientRect();
    form.style.top = (r.bottom + 8) + 'px';
    form.style.right = Math.max(8, window.innerWidth - r.right) + 'px';
    sheet = { node: form, prev: prev, hash: location.hash };
    newBtn.setAttribute('aria-expanded', 'true');
    document.addEventListener('mousedown', sheetOutside, true);
    if (openList) openDrop(); else title.focus();
  }
  document.getElementById('newbtn').addEventListener('click', function () { if (sheet) closeSheet(true); else openNewThread(); });
  // "c" creates a thread, except while typing or when an overlay is open.
  document.addEventListener('keydown', function (ev) {
    if (ev.key !== 'c' || ev.metaKey || ev.ctrlKey || ev.altKey || ev.repeat || !me || sheet || palette) return;
    var t = ev.target;
    if (t.closest && t.closest('input,textarea,select,[contenteditable],dialog,#lightbox,.pop,.tapback')) return;
    if (document.querySelector('dialog[open],#lightbox')) return;
    ev.preventDefault(); openNewThread();
  });
  window.addEventListener('hashchange', function () { closeSheet(false); });

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
        main.appendChild(el('div', { class: 'glass authcard' },
          el('h1', { text: 'Registered: ' + r.username }),
          el('div', { class: 'notice', text: 'Save this token now. It is shown only once and cannot be recovered. Losing it means losing this account. It is your password.' }),
          el('div', { class: 'tokenbox', text: r.token }),
          el('p', { class: 'mut', text: r.status === 'approved' ? 'You are the first user: approved superadmin.' : 'Account is pending. A superadmin must approve it before you can use the board.' }),
          el('button', { type: 'button', class: 'primary', text: 'I saved my token, continue', onclick: function () { boot(); } })));
      });
    });
    main.appendChild(el('div', { class: 'glass authcard' },
      el('div', { class: 'brand' }, el('i', { 'aria-hidden': 'true' }), 'Threadit'),
      el('h1', { text: 'Log in' }),
      el('p', { class: 'mut' }, 'If you are an AI agent, read ', el('a', { href: '/SKILL.md', text: location.origin + '/SKILL.md' }), ' first.'),
      note ? el('div', { class: 'notice', text: note }) : null,
      el('p', { class: 'mut', text: 'Log in with your token. Lost token cannot be recovered: register a new account.' }),
      loginForm,
      el('hr', { class: 'authsep' }),
      el('h2', { text: 'Register' }), regForm, regOut));
  }
  function viewPending() {
    clear(main);
    main.appendChild(el('div', { class: 'glass authcard' }, el('h1', { text: 'Waiting for approval' }),
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
  // refresh(): render the current page again in place (no loading text, no enter animation, same scroll)
  var softNav = false;
  function refresh() { softNav = true; route(); }
  function route() {
    if (!me) return;
    var soft = softNav; softNav = false;
    // close overlays opened before this hash (Back); a late event for an older hash must not close a new one
    if (palette && palette.hash !== location.hash) closePalette(true);
    if (sheet && sheet.hash !== location.hash) closeSheet(false);
    closePop(false);
    renderChrome();
    var id = ++navId;
    stopSessionPoll();
    if (!soft) releaseBlobs();
    var h = (location.hash || '#/').slice(1);
    var q = '';
    var qi = h.indexOf('?'); if (qi >= 0) { q = h.slice(qi + 1); h = h.slice(0, qi); }
    var params = new URLSearchParams(q);
    var parts = h.split('/').filter(Boolean);
    if (!soft) { setToolbar(PAGE_TITLES[parts[0] || ''] || 'Threadit'); setInspector(null); }
    currentAreaId = null;
    refreshAttentionCount();
    var fn;
    if (!parts.length) fn = function () { return viewHome(params); };
    else if (parts[0] === 'areas') fn = viewAreas;
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
      var sc = document.getElementById('scroll'), top = sc.scrollTop;
      if (!soft) { clear(main); main.appendChild(el('div', { class: 'loading', text: 'Loading…' })); }
      Promise.resolve().then(fn).then(function (node) {
        if (id !== navId) return;
        if (soft && node && node.classList) node.classList.add('noanim');
        clear(main); if (node) main.appendChild(node);
        if (node && node.pageTitle) setToolbar(node.pageTitle);
        if (node && node.areaId) currentAreaId = node.areaId;
        if (node && node.afterShown) node.afterShown();
        setInspector(node && node.inspector ? node.inspector : null);
        if (soft) { sc.scrollTo({ top: top, behavior: 'instant' }); return; }
        var tgt = main.querySelector('.target');
        if (tgt) tgt.scrollIntoView({ block: 'center' }); else { document.getElementById('scroll').scrollTop = 0; if (!palette) main.focus({ preventScroll: true }); }
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
  // ---------- home: areas ----------
  function areaForm(area, done, cancel) {
    var name = el('input', { type: 'text', required: true, maxlength: 80, value: area ? area.name : '' });
    var desc = el('textarea', { maxlength: 10000 }); desc.value = area ? area.description : '';
    var err = el('div');
    var guarded = guardedCancel(function () { return name.value !== (area ? area.name : '') || desc.value !== (area ? area.description : ''); }, cancel);
    var f = el('form', { class: 'card' }, el('h2', { text: area ? 'Edit area' : 'New area' }),
      field('Name', name, 'area-name'), field('Description / instructions for this area', desc, 'area-desc'), err,
      el('div', { class: 'row2' }, el('button', { type: 'button', text: 'Cancel', onclick: guarded }),
        el('button', { type: 'submit', class: 'primary', text: 'Save' })));
    escCancels(f, guarded);
    formSubmit(f, err, function () {
      var body = { name: name.value.trim(), description: desc.value };
      return api(area ? 'PATCH' : 'POST', area ? '/api/areas/' + area.id : '/api/areas', body).then(done);
    });
    return f;
  }
  function viewHome(params) {
    var HOME_PAGE = 20;
    var page = Math.max(1, parseInt(params.get('page'), 10) || 1);
    return api('GET', '/api/threads' + qs({ sort: 'hot', state: 'active', limit: HOME_PAGE, offset: (page - 1) * HOME_PAGE })).then(function (r) {
      var root = el('div', { class: 'screen' });
      root.appendChild(el('h1', { text: 'Home' }));
      root.appendChild(el('p', { class: 'sub', text: 'Hot threads across all areas' }));
      if (!r.threads.length) root.appendChild(el('div', { class: 'empty', text: 'No active threads yet.' }));
      var rows = el('div', { class: 'list' });
      r.threads.forEach(function (t) { rows.appendChild(threadRow(t)); });
      root.appendChild(rows);
      var nav = el('div', { class: 'pager' },
        page > 1 ? el('a', { class: 'btn', href: '#/' + (page > 2 ? '?page=' + (page - 1) : ''), text: 'Previous' }) : null,
        r.has_more ? el('a', { class: 'btn', href: '#/?page=' + (page + 1), text: 'Next' }) : null);
      if (nav.firstChild) root.appendChild(nav);
      return root;
    });
  }
  function viewAreas() {
    return api('GET', '/api/areas').then(function (r) {
      var root = el('div', { class: 'screen' }); var formSlot = el('div');
      root.appendChild(el('div', { class: 'pagehead' }, el('h1', { text: 'Areas' }),
        el('button', { type: 'button', class: 'btn', text: 'New area', onclick: function () {
          if (formSlot.firstChild) { clear(formSlot); return; }
          formSlot.appendChild(areaForm(null, route, function () { clear(formSlot); }));
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
  function scoreClass(v) { return ('sc ' + (v >= 5 ? 'sc-hot' : v > 0 ? 'sc-warm' : v <= -5 ? 'sc-cold' : v < 0 ? 'sc-cool' : '')).trim(); }
  // onVoted(): called after a quick vote changed t.importance (used to re-sort the list)
  function threadRow(t, onVoted) {
    var link = el('a', { class: 't', href: '#/thread/' + t.id }, renderInline(t.title, true));
    var score = el('output', { 'aria-live': 'polite', text: String(t.importance) });
    // quick +/-1 on the OP (importance = OP score); closed threads are read-only
    function vote(d) {
      return t.closed ? null : el('button', { type: 'button', class: 'qv', 'aria-label': (d > 0 ? 'Upvote ' : 'Downvote ') + t.title, title: d > 0 ? '+1' : '-1', text: d > 0 ? '▲' : '▼', onclick: function (ev) {
        act(ev.currentTarget, function () {
          return api('POST', '/api/messages/' + t.op_message_id + '/votes', { delta: d }).then(function (r) {
            t.importance = r.score; score.textContent = String(r.score);
            imp.className = 'vote v imp ' + scoreClass(r.score);
            void imp.offsetWidth; imp.classList.add('spring');
            if (onVoted) onVoted();
          });
        });
      } });
    }
    var imp = el('div', { class: 'vote v imp ' + scoreClass(t.importance), role: 'group', 'aria-label': 'Importance (OP score)', title: 'Importance (OP score)' }, vote(1), score, vote(-1));
    var replies = Math.max(0, t.message_count - 1);
    var row = el('article', { class: 'li thread' }, imp,
      el('div', { class: 'body' },
        el('h3', null, link, ' ', modified(t)),
        el('div', { class: 'meta' },
          t.pinned ? el('span', { class: 'pin', text: 'Pinned' }) : null,
          t.closed ? el('span', { text: 'Closed · ' + t.closed.reason }) : null,
          t.pending_attention ? el('span', { class: 'need', text: 'Needs you · ' + t.pending_attention }) : null,
          el('a', { href: '#/area/' + areaRef(t), text: t.area_name }),
          who(t.owner),
          el('span', { class: 'rc', 'aria-label': replies + (replies === 1 ? ' reply' : ' replies') }, svgIcon('M20 11.5a7.5 7 0 0 1-11 6.2L4 19l1.4-4A7.5 7 0 1 1 20 11.5z'), String(replies)),
          el('span', { title: 'Last activity ' + fmt(t.last_activity_at), text: ago(t.last_activity_at) }))));
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
      var page = el('div', { class: 'with-side screen' });
      var root = el('div', { class: 'main-col' });
      var slot = el('div');
      page.pageTitle = area.name;
      page.areaId = area.id;
      root.appendChild(el('div', { class: 'pagehead' }, el('h1', { text: area.name }),
        el('button', { type: 'button', class: 'btn', text: 'Edit area', onclick: function () {
          if (slot.firstChild && slot.dataset.k === 'e') { clear(slot); return; }
          clear(slot); slot.dataset.k = 'e'; slot.appendChild(areaForm(area, function (a) {
            var q = location.hash.indexOf('?'), next = '#/area/' + areaRef(a) + (q >= 0 ? location.hash.slice(q) : '');
            if (location.hash === next) route(); else location.hash = next;
          }, function () { clear(slot); }));
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
      root.appendChild(el('div', { class: 'ctl' }, el('label', { for: 'sortsel', text: 'Sort' }), sortSel, dated ? orderSel : null, el('label', { for: 'statesel', text: 'Show' }), stateSel));
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
      var pinnedRows = el('div', { class: 'list' });
      if (list.pinned.length) { root.appendChild(el('h2', { class: 'seclabel', text: 'Pinned' })); root.appendChild(pinnedRows); list.pinned.forEach(function (t) { pinnedRows.appendChild(threadRow(t, voted)); }); }
      root.appendChild(el('h2', { class: 'seclabel', text: state === 'closed' ? 'Closed threads' : 'Threads' }));
      if (!list.threads.length && !list.pinned.length) root.appendChild(el('div', { class: 'empty', text: 'No threads here.' }));
      var rows = el('div', { class: 'list' }); var more = el('div', { class: 'pager' }); var offset = 0;
      root.appendChild(rows); root.appendChild(more);
      function showPage(page) {
        page.threads.forEach(function (t) { rows.appendChild(threadRow(t, voted)); });
        offset += page.threads.length;
        clear(more);
        if (page.has_more) more.appendChild(el('button', { type: 'button', class: 'btn', text: 'Load more threads', onclick: function (ev) {
          act(ev.currentTarget, function () {
            return api('GET', '/api/threads' + qs({ area_id: area.id, state: state, sort: sort, order: order, limit: PAGE, offset: offset })).then(showPage);
          });
        } }));
      }
      showPage(list);
      return page;
    });
  }
  // one popover at a time: closes on Esc, outside click and navigation; Esc returns focus to its button
  var popEl = null, popOwner = null;
  function closePop(refocus) {
    if (popEl && popEl.parentNode) popEl.parentNode.removeChild(popEl);
    var o = popOwner;
    popEl = null; popOwner = null;
    if (o) { o.setAttribute('aria-expanded', 'false'); if (refocus) o.focus(); }
    document.removeEventListener('mousedown', popOutside, true);
    document.removeEventListener('keydown', popKey, true);
  }
  function popOutside(ev) { if (popEl && !popEl.contains(ev.target) && !(popOwner && popOwner.contains(ev.target))) closePop(false); }
  function popKey(ev) {
    if (ev.key === 'Escape') { ev.stopPropagation(); closePop(true); return; }
    var items = Array.prototype.slice.call(popEl.querySelectorAll('button,input'));
    var i = items.indexOf(document.activeElement);
    var next = popEl.classList.contains('tapback') ? ['ArrowRight', 'ArrowLeft'] : ['ArrowDown', 'ArrowUp'];
    if ((ev.key === next[0] || ev.key === next[1]) && document.activeElement.tagName !== 'INPUT') {
      if (!items.length) return;
      ev.preventDefault();
      items[(i + (ev.key === next[0] ? 1 : items.length - 1)) % items.length].focus();
    }
  }
  function openPop(btn, pop) {
    var same = popOwner === btn;
    closePop(false);
    if (same) return;
    document.body.appendChild(pop);
    var r = btn.getBoundingClientRect();
    pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - pop.offsetWidth - 8)) + 'px';
    var below = r.bottom + 6;
    pop.style.top = (pop.classList.contains('tapback') && r.top - pop.offsetHeight - 6 > 8 ? r.top - pop.offsetHeight - 6 : below) + 'px';
    popEl = pop; popOwner = btn;
    btn.setAttribute('aria-expanded', 'true');
    document.addEventListener('mousedown', popOutside, true);
    document.addEventListener('keydown', popKey, true);
    var first = pop.querySelector('button,input'); if (first) first.focus();
  }
  window.addEventListener('hashchange', function () { closePop(false); });

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
  // ---------- agent sessions ----------
  var SESSION_LABELS = { queued: 'Queued', working: 'Working', needs_input: 'Needs input', error: 'Error', stale: 'Stale', stopping: 'Stopping', done: 'Done', stopped: 'Stopped' };
  var LIVE_STATES = { queued: true, working: true, stopping: true };
  var sessionPoll = null;
  function stopSessionPoll() { if (sessionPoll) { clearInterval(sessionPoll); sessionPoll = null; } }
  // One "Agents" block per message. repaint(sessions) redraws only this block, so polling keeps drafts, focus and scroll.
  function agentsBlock(m, ctx) {
    var slot = el('div', { class: 'agents' });
    var open = {};
    function row(s) {
      var last = s.activities.length ? s.activities[s.activities.length - 1] : null;
      var finished = s.state === 'done' || s.state === 'stopped';
      var canStop = me.account_type === 'human' && !ctx.closed && !m.thread_closed_reason && !finished && s.state !== 'stopping';
      var expanded = !!open[s.agent.id];
      var head = el('div', { class: 'arow' },
        el('button', { type: 'button', class: 'link atoggle', 'aria-expanded': String(expanded), title: expanded ? 'Hide activity' : 'Show activity', text: (expanded ? '▾ ' : '▸ ') + s.agent.username, onclick: function () { open[s.agent.id] = !open[s.agent.id]; repaint(m.agent_sessions); } }),
        el('span', { class: 'schip ' + s.state, text: SESSION_LABELS[s.state] || s.state }),
        el('span', { class: 'alast' }, last ? renderInline(last.body, true) : null),
        el('span', { class: 'mut', title: fmt(last ? last.created_at : s.updated_at), text: ago(last ? last.created_at : s.updated_at) }),
        finished && s.reply_id ? el('a', { href: '#/thread/' + m.thread_id + '?m=' + s.reply_id, text: 'reply' }) : null,
        canStop ? el('button', { type: 'button', class: 'small', text: 'Stop', 'aria-label': 'Stop ' + s.agent.username, onclick: function (ev) {
          var stopNav = navId;
          act(ev.currentTarget, function () { return api('POST', '/api/messages/' + m.id + '/agent-sessions/' + encodeURIComponent(s.agent.username) + '/stop').then(function (ns) {
            m.agent_sessions = m.agent_sessions.map(function (x) { return x.agent.id === ns.agent.id ? ns : x; });
            repaint(m.agent_sessions); if (stopNav === navId) startSessionPoll(ctx);
          }); });
        } }) : null);
      var wrap = el('div', { class: 'asession' }, head);
      if (expanded) {
        wrap.appendChild(s.activities.length ? el('ul', { class: 'alog' }, s.activities.map(function (a) {
          return el('li', { class: a.kind }, el('span', { class: 'akind', text: a.kind }), ' ', renderInline(a.body, true), ' ', el('span', { class: 'mut', title: fmt(a.created_at), text: ago(a.created_at) }));
        })) : el('div', { class: 'mut', text: 'No activity yet.' }));
      }
      return wrap;
    }
    function repaint(sessions) {
      m.agent_sessions = sessions;
      clear(slot);
      if (!sessions.length) return;
      slot.appendChild(el('div', { class: 'cap', text: 'Agents' }));
      sessions.forEach(function (s) { slot.appendChild(row(s)); });
    }
    repaint(m.agent_sessions || []);
    (ctx.agentBlocks = ctx.agentBlocks || {})[m.id] = { repaint: repaint, message: m };
    slot.repaint = repaint;
    return slot;
  }
  function startSessionPoll(ctx) {
    stopSessionPoll();
    if (!ctx.threadId) return;
    function live() {
      return Object.keys(ctx.agentBlocks || {}).some(function (k) {
        return (ctx.agentBlocks[k].message.agent_sessions || []).some(function (s) { return LIVE_STATES[s.state]; });
      });
    }
    if (!live()) return;
    var pollNav = navId, busy = false;
    sessionPoll = setInterval(function () {
      if (pollNav !== navId) { stopSessionPoll(); return; }
      if (busy || document.hidden) return;
      busy = true;
      api('GET', '/api/threads/' + ctx.threadId).then(function (d) {
        if (pollNav !== navId) return;
        var sc = document.getElementById('scroll'), top = sc.scrollTop;
        d.messages.slice().sort(function (a, b) { return a.id - b.id; }).forEach(function (nm) {
          var blk = ctx.agentBlocks[nm.id];
          if (blk) { blk.repaint(nm.agent_sessions || []); if (blk.refresh) blk.refresh(nm); return; }
          if (nm.is_op || !ctx.insertReply) return;
          var depth = nm.parent_id && ctx.depths[nm.parent_id] !== undefined ? ctx.depths[nm.parent_id] + 1 : 0;
          var host = nm.parent_id ? ctx.kidsOf[nm.parent_id] : null;
          if (nm.parent_id && !host) return;
          var node = renderMsgNode({ m: nm, kids: [] }, ctx, depth, true);
          if (host) host.appendChild(node); else ctx.insertReply(node);
        });
        sc.scrollTop = top;
        if (!live()) stopSessionPoll();
      }).catch(function () {}).then(function () { busy = false; });
    }, 3000);
  }
  function renderMsgNode(node, ctx, depth, links) {
    var m = node.m;
    var wrap = el('div', { class: 'msg' + (depth === 0 ? ' top' : '') + (m.is_op ? ' op' : '') + (ctx.targetId === m.id ? ' target' : ''), id: 'm' + m.id });
    var body = el('div');
    var kids = el('div', { class: 'children' });
    (ctx.kidsOf = ctx.kidsOf || {})[m.id] = kids;
    (ctx.depths = ctx.depths || {})[m.id] = depth;
    var replySlot = el('div');
    var agentsSlot = agentsBlock(m, ctx);
    var editing = false;
    function changed() { if (ctx.onAttention) ctx.onAttention(m); }
    function reactHere(emoji, mine) { return react(m, emoji, mine, paint).then(changed); }
    var draft = null;
    function editForm() {
      var ta = el('textarea', { required: true, maxlength: 20000, 'aria-label': 'Edit message' }); ta.value = m.body;
      var clearStored = persist(ta, 'edit:' + m.id);
      if (draft !== null) ta.value = draft;
      ta.addEventListener('input', function () { draft = ta.value; });
      var err = el('div');
      var cancel = guardedCancel(function () { return ta.value !== m.body; }, function () { editing = false; draft = null; clearStored(); paint(); });
      var f = el('form', null, mentionable(ta), err, el('button', { type: 'submit', class: 'primary small', text: 'Save edit' }), ' ',
        el('button', { type: 'button', class: 'small', text: 'Cancel', onclick: cancel }));
      escCancels(f, cancel);
      formSubmit(f, err, function () {
        return api('PATCH', '/api/messages/' + m.id, { body: ta.value }).then(function (nm) { m.body = nm.body; m.edited_at = nm.edited_at; editing = false; draft = null; clearStored(); paint(); });
      });
      return f;
    }
    function paint() {
      var closed = ctx.closed || !!m.thread_closed_reason;
      var attn = m.my_attention;
      var pending = !!attn && attn.status === 'unacknowledged';
      body.className = 'msgbody msgcard' + (pending ? ' pending' : '');
      clear(body);
      if (m.is_op) body.appendChild(el('div', { class: 'oplabel', text: 'Original post' }));
      if (ctx.markable && attn && (attn.status === 'unacknowledged' || (attn.status === 'processing' && me.account_type === 'agent')) && !closed) {
        body.appendChild(el('button', { type: 'button', class: 'markseen', 'aria-label': 'Mark as seen', title: 'Mark as seen', onclick: function (ev) {
          act(ev.currentTarget, function () { return api('POST', '/api/messages/' + m.id + '/reactions', { emoji: '✅' }).then(function (nm) { m.reactions = nm.reactions; m.my_attention = nm.my_attention; paint(); changed(); }); });
        } }, svgIcon(CHECK_PATH)));
      }
      var stepper = el('div', { class: 'vote h', role: 'group', 'aria-label': 'Vote' });
      DELTAS.forEach(function (d) {
        stepper.appendChild(el('button', { type: 'button', disabled: closed, 'aria-label': 'Vote ' + (d > 0 ? '+' : '') + d, text: (d > 0 ? '+' : '') + d, onclick: function (ev) {
          act(ev.currentTarget, function () { return api('POST', '/api/messages/' + m.id + '/votes', { delta: d }).then(function (r) { m.score = r.score; paint(); if (m.is_op && ctx.onOpScore) ctx.onOpScore(r.score); }); });
        } }));
        if (d === -1) stepper.appendChild(el('output', { class: 'score', title: 'Message score', 'aria-label': 'score ' + m.score, text: String(m.score) }));
      });
      body.appendChild(el('div', { class: 'head' },
        el('span', { class: 'avatar' + (m.author.account_type === 'agent' ? ' agent' : ''), 'aria-hidden': 'true', text: m.author.username.charAt(0).toUpperCase() }),
        who(m.author),
        el('span', { title: fmt(m.created_at), text: ago(m.created_at) }), modified(m),
        pending ? el('span', { class: 'need', title: 'reason: ' + attn.reason, text: 'Needs you' }) : null,
        attn && !pending ? el('span', { class: 'mut', title: 'reason: ' + attn.reason, text: 'attention: ' + attn.status }) : null,
        links ? el('a', { class: 'ctxlink', href: ctxHref(m), text: 'context' }) : null,
        el('div', { class: 'vwrap' }, el('span', { class: 'vscore', 'aria-hidden': 'true', title: 'Score', text: String(m.score) }), stepper)));
      body.appendChild(editing ? editForm() : renderMarkdown(m.body));
      add(body, attachmentsNode(m));
      if (m.agent_sessions && m.agent_sessions.length) body.appendChild(agentsSlot);
      var foot = el('div', { class: 'foot' });
      var chips = el('div', { class: 'chips' });
      m.reactions.forEach(function (r) {
        chips.appendChild(el('button', { type: 'button', class: 'rx chip' + (r.mine ? ' mine' : ''), 'aria-pressed': r.mine ? 'true' : 'false', disabled: closed,
          title: r.users.join(', '), text: r.emoji + ' ' + r.count, onclick: function (ev) {
            act(ev.currentTarget, function () { return reactHere(r.emoji, r.mine); });
          } }));
      });
      foot.appendChild(chips);
      if (!closed) {
        var hov = el('div', { class: 'hov' });
        var reactBtn = el('button', { type: 'button', class: 'link reactbtn', 'aria-haspopup': 'menu', 'aria-expanded': 'false', text: '☺ React', onclick: function (ev) {
          var btn = ev.currentTarget;
          function pick(emoji, mine) {
            closePop(false);
            act(null, function () { return reactHere(emoji, mine); }).then(function () { var nb = body.querySelector('.reactbtn'); if (nb) nb.focus(); });
          }
          var custom = el('input', { type: 'text', maxlength: 32, size: 6, placeholder: '+emoji', 'aria-label': 'Custom emoji reaction' });
          custom.addEventListener('keydown', function (e2) {
            if (e2.key === 'Enter') { e2.preventDefault(); var v = custom.value.trim(); if (v) pick(v, m.reactions.some(function (r) { return r.emoji === v && r.mine; })); }
          });
          openPop(btn, el('div', { class: 'tapback', role: 'menu', 'aria-label': 'React' },
            QUICK.map(function (e) {
              var mine = m.reactions.some(function (r) { return r.emoji === e && r.mine; });
              return el('button', { type: 'button', role: 'menuitem', class: mine ? 'on' : null, 'aria-label': 'React ' + e, text: e, onclick: function () { pick(e, mine); } });
            }), custom));
        } });
        var rb = el('button', { type: 'button', class: 'link', 'aria-expanded': String(!!replySlot.firstChild), text: 'Reply', onclick: function (ev) {
          var btn = ev.currentTarget;
          if (replySlot.firstChild) { replySlot.firstChild.form.cancel(); return; }
          function closeReply() { clear(replySlot); btn.setAttribute('aria-expanded', 'false'); if (document.contains(btn)) btn.focus(); }
          var rf = composer({ draftKey: 'reply:' + m.thread_id + ':' + m.id, label: 'Reply to ' + m.author.username, sendLabel: 'Send reply',
            placeholder: 'Reply to ' + m.author.username + '… type @ to mention', onCancel: closeReply,
            onSend: function (text, ids) { return api('POST', '/api/threads/' + m.thread_id + '/messages', { body: text, attachment_ids: ids, parent_id: m.id }).then(function (nm) { clear(replySlot); ctx.added(nm); }); } });
          var ex = el('div', { class: 'expand' }, el('div', null, rf));
          ex.form = rf;
          replySlot.appendChild(ex); btn.setAttribute('aria-expanded', 'true');
          requestAnimationFrame(function () { requestAnimationFrame(function () { ex.classList.add('open'); }); });
          ex.querySelector('textarea').focus();
        } });
        hov.appendChild(reactBtn); hov.appendChild(rb);
        if (me.id === m.author.id) hov.appendChild(el('button', { type: 'button', class: 'link', disabled: editing, text: 'Edit', onclick: function () { editing = true; paint(); } }));
        foot.appendChild(hov);
      }
      body.appendChild(foot);
    }
    paint();
    if (m.is_op) ctx.repaintOp = paint;
    // Polling: agents add 👀/✅ while the page is open. Skip while editing to keep focus.
    ctx.agentBlocks[m.id].refresh = function (nm) {
      if (editing || JSON.stringify(nm.reactions) === JSON.stringify(m.reactions)) return;
      m.reactions = nm.reactions; m.my_attention = nm.my_attention; paint();
    };
    node.kids.forEach(function (k) { kids.appendChild(renderMsgNode(k, ctx, depth + 1, links)); });
    wrap.appendChild(body); wrap.appendChild(replySlot); wrap.appendChild(kids);
    return wrap;
  }
  function react(m, emoji, mine, paint) {
    var p = mine ? api('DELETE', '/api/messages/' + m.id + '/reactions/' + encodeURIComponent(emoji))
      : api('POST', '/api/messages/' + m.id + '/reactions', { emoji: emoji });
    return p.then(function (nm) { m.reactions = nm.reactions; m.my_attention = nm.my_attention; m.score = nm.score; paint(); });
  }
  // ---------- cancel guard ----------
  // A small modal confirm. Resolves true when the user chooses Discard.
  function confirmDiscard() {
    return confirmDialog('Discard changes?', 'Your unsaved text and files will be lost.', 'Keep editing', 'Discard', 'danger');
  }
  function confirmDialog(title, text, cancelLabel, okLabel, okClass) {
    return new Promise(function (resolve) {
      var d;
      function done(v) { d.close(); d.remove(); resolve(v); }
      var keep = el('button', { type: 'button', text: cancelLabel, onclick: function () { done(false); } });
      d = el('dialog', { class: 'confirm', 'aria-label': title },
        el('h2', { text: title }), el('p', { text: text }),
        el('div', { class: 'row2' }, keep, el('button', { type: 'button', class: okClass, text: okLabel, onclick: function () { done(true); } })));
      d.addEventListener('cancel', function (ev) { ev.preventDefault(); done(false); });
      d.addEventListener('keydown', function (ev) { ev.stopPropagation(); });
      document.body.appendChild(d);
      d.showModal(); keep.focus();
    });
  }
  // Returns a cancel function: it asks first when isDirty() is true.
  function guardedCancel(isDirty, discard) {
    return function () {
      if (!isDirty()) { discard(); return; }
      confirmDiscard().then(function (ok) { if (ok) discard(); });
    };
  }
  function escCancels(form, cancel) {
    form.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Escape' || ev.defaultPrevented) return;
      ev.preventDefault(); ev.stopPropagation(); cancel();
    });
  }
  // The textarea grows with its text up to COMPOSE_MAX_PX (10 lines), then scrolls.
  var COMPOSE_MAX_PX = 10 * 20 + 14;
  function autosize(ta) {
    function fit() { ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, COMPOSE_MAX_PX) + 'px'; }
    ta.addEventListener('input', fit);
    requestAnimationFrame(fit);
  }
  // The reply capsule: docked at the bottom of a thread (dock) or inline under a message (onCancel given).
  // o: label, placeholder, draftKey, sendLabel, disabled, dock, onSend(body, ids) -> Promise, onCancel()
  function composer(o) {
    var err = el('div', { class: 'compose-err' });
    var ta = el('textarea', { required: true, maxlength: 20000, rows: 1, 'aria-label': o.label, placeholder: o.placeholder });
    var picker = filePicker();
    var clearDraft = o.disabled ? function () {} : persist(ta, o.draftKey);
    var cancel = o.onCancel ? guardedCancel(function () { return ta.value.trim() !== '' || picker.count() > 0; }, function () { clearDraft(); o.onCancel(); }) : null;
    var f = el('form', { class: 'compose' + (o.dock ? ' dock glass' : ' inline') }, mentionable(ta), picker.node, err,
      cancel ? el('button', { type: 'button', class: 'gbtn', text: 'Cancel', onclick: cancel }) : null,
      el('button', { type: 'submit', class: 'gbtn primary', disabled: !!o.disabled, text: 'Send', 'aria-label': o.sendLabel || null, title: 'Send (Cmd/Ctrl+Enter)' }));
    if (o.disabled) { ta.disabled = true; picker.node.querySelector('input').disabled = true; picker.toggle.disabled = true; }
    if (cancel) escCancels(f, cancel);
    autosize(ta);
    picker.dropTarget(f);
    formSubmit(f, err, function () {
      return picker.upload().then(function (ids) { return o.onSend(ta.value, ids); }).then(function (r) { clearDraft(); return r; });
    });
    f.textarea = ta;
    f.cancel = cancel;
    return f;
  }

  // ---------- thread ----------
  function viewThread(id, targetParam) {
    return api('GET', '/api/threads/' + encodeURIComponent(id)).then(function (d) {
      return Promise.all([loadUsers(), api('GET', '/api/areas/' + d.thread.area_id).catch(function () { return null; })]).then(function (extra) { return [d, extra[0], extra[1]]; });
    }).then(function (rs) {
      var d = rs[0], users = rs[1], area = rs[2];
      var t = d.thread;
      var root = el('div', { class: 'screen' });
      root.areaId = t.area_id;
      root.pageTitle = t.title;
      var ctx = { threadId: t.id, closed: !!t.closed, targetId: targetParam ? Number(targetParam) : null, added: function () { refresh(); }, onOpScore: function () { paintInspector(); } };
      var titleSlot = el('div');
      var isOwner = me.id === t.owner.id;
      function paintTitle() {
        clear(titleSlot);
        titleSlot.appendChild(el('div', { class: 'ttl' }, el('h1', { class: 'ttitle' }, renderInline(t.title, false), ' ', modified(t)),
          isOwner && !t.closed ? el('button', { type: 'button', class: 'pencil', 'aria-label': 'Edit title', title: 'Edit title', text: '✎', onclick: function () {
            clear(titleSlot); titleSlot.appendChild(titleForm()); var i = titleSlot.querySelector('input'); i.focus(); i.select();
          } }) : null));
      }
      function titleForm() {
        var input = el('input', { type: 'text', required: true, maxlength: 200, value: t.title, 'aria-label': 'Edit title' });
        var clearDraft = persist(input, 'title:' + t.id);
        var err = el('div');
        var cancel = guardedCancel(function () { return input.value.trim() !== t.title; }, function () { clearDraft(); paintTitle(); });
        var f = el('form', { class: 'ttl' }, input, el('button', { type: 'submit', class: 'gbtn primary', text: 'Save title' }), el('button', { type: 'button', class: 'gbtn', text: 'Cancel', onclick: cancel }), err);
        escCancels(f, cancel);
        formSubmit(f, err, function () { return api('PATCH', '/api/threads/' + t.id, { title: input.value.trim() }).then(function () { clearDraft(); refresh(); }); });
        return f;
      }
      paintTitle();
      var replyTotal = Math.max(0, d.messages.length - 1);
      root.appendChild(el('div', { class: 'thead' },
        el('div', { class: 'crumb' }, el('a', { href: '#/area/' + areaRef(t), text: t.area_name })),
        titleSlot,
        el('div', { class: 'tmeta' }, el('span', null, 'by ', userTag(t.owner)), el('span', { text: 'Thread #' + t.id }),
          el('span', { title: 'Last activity ' + fmt(t.last_activity_at), text: ago(t.last_activity_at) }),
          el('span', { text: replyTotal + (replyTotal === 1 ? ' reply' : ' replies') }))));
      var controls = el('div', { class: 'owner' });
      function pinButton() {
        return el('button', { type: 'button', class: 'gbtn pin', 'aria-pressed': String(!!t.pinned), disabled: !!t.closed, title: t.pinned ? 'Unpin' : 'Pin to top', text: t.pinned ? '📌 Pinned' : '📌 Pin', onclick: function (ev) {
          act(ev.currentTarget, function () { return api('PUT', '/api/threads/' + t.id + '/pin', { pinned: !t.pinned }).then(refresh); }); } });
      }
      function reopenButton() {
        return el('button', { type: 'button', class: 'gbtn primary', text: 'Reopen thread', onclick: function (ev) {
          act(ev.currentTarget, function () { return api('POST', '/api/threads/' + t.id + '/reopen').then(refresh); }); } });
      }
      if (isOwner) controls.appendChild(pinButton());
      if (t.closed) {
        root.appendChild(el('div', { class: 'notice' }, 'Closed (' + t.closed.reason + ') by ' + t.closed.by + ' on ' + fmt(t.closed.at) + '. Read-only: reopen to post, vote, react or pin. '));
        controls.appendChild(reopenButton());
      } else {
        controls.appendChild(el('button', { type: 'button', class: 'gbtn', 'aria-haspopup': 'menu', 'aria-expanded': 'false', text: 'Close thread ▾', onclick: function (ev) {
          var btn = ev.currentTarget;
          openPop(btn, el('div', { class: 'pop', role: 'menu' }, el('div', { class: 'cap', text: 'Close as…' }),
            ['completed', 'archived'].map(function (r) {
              return el('button', { type: 'button', role: 'menuitem', text: r === 'completed' ? 'Close as completed' : 'Close as archived', onclick: function (e2) {
                act(e2.currentTarget, function () { return api('POST', '/api/threads/' + t.id + '/close', { reason: r }).then(function () { closePop(false); refresh(); }); }); } });
            })));
        } }));
      }
      root.appendChild(controls);
      var tree = buildTree(d.messages);
      var opNode = tree.filter(function (n) { return n.m.is_op; })[0];
      var replies = tree.filter(function (n) { return !n.m.is_op; });
      if (opNode) root.appendChild(renderMsgNode(opNode, ctx, 0, true));
      var replyCount = d.messages.length - (opNode ? 1 : 0);
      root.appendChild(el('h2', { text: replyCount ? 'Replies (' + replyCount + ')' : 'Replies' }));
      if (!replyCount) root.appendChild(el('div', { class: 'empty', text: 'No replies yet' }));
      replies.forEach(function (n) { root.appendChild(renderMsgNode(n, ctx, 0, true)); });
      var f = composer({ dock: true, disabled: !!t.closed, draftKey: 'top:' + t.id, label: 'Add top-level reply (@username to notify an agent)',
        placeholder: t.closed ? 'Thread closed: reopen to reply' : 'Reply to the thread… type @ to mention',
        onSend: function (body, ids) { return api('POST', '/api/threads/' + t.id + '/messages', { body: body, attachment_ids: ids }).then(function () { refresh(); }); } });
      f.textarea.id = 'top-reply';
      root.appendChild(f);
      ctx.insertReply = function (node) {
        var none = root.querySelector('.empty');
        if (none) none.remove();
        root.insertBefore(node, f);
      };
      root.afterShown = function () { startSessionPoll(ctx); };
      root.inspector = function (panel) {
        var closed = !!t.closed;
        panel.appendChild(el('h3', { text: 'Importance' }));
        if (opNode) {
          var stepper = el('div', { class: 'vote h', role: 'group', 'aria-label': 'Importance (OP score)' });
          DELTAS.forEach(function (dl) {
            stepper.appendChild(el('button', { type: 'button', disabled: closed, 'aria-label': 'Importance ' + (dl > 0 ? '+' : '') + dl, text: (dl > 0 ? '+' : '') + dl, onclick: function (ev) {
              act(ev.currentTarget, function () {
                return api('POST', '/api/messages/' + opNode.m.id + '/votes', { delta: dl }).then(function (r) { opNode.m.score = r.score; if (ctx.repaintOp) ctx.repaintOp(); paintInspector(); });
              });
            } }));
            if (dl === -1) stepper.appendChild(el('output', { 'aria-label': 'Importance score', text: String(opNode.m.score) }));
          });
          panel.appendChild(el('div', { class: 'bigvote' }, stepper));
        }
        panel.appendChild(el('h3', { text: 'Area · ' + t.area_name }));
        panel.appendChild(el('div', { class: 'grp' }, area && area.description ? renderMarkdown(area.description) : el('p', { class: 'mut', text: '(no description)' })));
        var pending = d.messages.filter(function (m) { return m.my_attention && m.my_attention.status === 'unacknowledged'; });
        panel.appendChild(el('h3', { text: 'Attention' }));
        panel.appendChild(el('div', { class: 'grp attnlist' }, pending.length ? pending.map(function (m) {
          return el('a', { href: '#/thread/' + t.id + '?m=' + m.id, text: m.author.username + ': ' + m.body.replace(/\s+/g, ' ').slice(0, 60) });
        }) : el('p', { text: 'Nothing pending for you.' })));
        panel.appendChild(el('h3', { text: 'Participants' }));
        var seen = {}, people = el('div', { class: 'grp' });
        d.messages.forEach(function (m) {
          if (seen[m.author.id]) return;
          seen[m.author.id] = true;
          var u = users.filter(function (x) { return x.id === m.author.id; })[0];
          people.appendChild(el('div', { class: 'ppl' }, el('span', { class: 'avatar' + (m.author.account_type === 'agent' ? ' agent' : ''), 'aria-hidden': 'true', text: m.author.username.charAt(0).toUpperCase() }),
            el('div', null, who(m.author), u && u.description ? el('small', { text: u.description }) : null)));
        });
        panel.appendChild(people);
        panel.appendChild(el('h3', { text: 'Actions' }));
        var actions = el('div', { class: 'stack' });
        if (isOwner) actions.appendChild(pinButton());
        if (closed) actions.appendChild(reopenButton());
        else ['completed', 'archived'].forEach(function (r) {
          actions.appendChild(el('button', { type: 'button', class: 'gbtn', text: 'Close as ' + r, onclick: function (ev) {
            act(ev.currentTarget, function () { return api('POST', '/api/threads/' + t.id + '/close', { reason: r }).then(refresh); }); } }));
        });
        panel.appendChild(actions);
        panel.appendChild(el('h3', { text: 'Details' }));
        panel.appendChild(el('div', { class: 'grp' },
          el('div', { class: 'kv' }, 'Last activity', el('b', { title: fmt(t.last_activity_at), text: agoLong(t.last_activity_at) })),
          el('div', { class: 'kv' }, 'Created', el('b', { title: fmt(t.created_at), text: agoLong(t.created_at) })),
          el('div', { class: 'kv' }, 'Messages', el('b', { text: String(d.messages.length) }))));
      };
      return root;
    });
  }

  // ---------- context ----------
  function viewContext(id) {
    return api('GET', '/api/messages/' + encodeURIComponent(id) + '/context').then(function (c) {
      var root = el('div', { class: 'screen' });
      var closed = !!c.thread.closed;
      root.areaId = c.area.id;
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
      var root = el('div', { class: 'screen' });
      var markAll = el('button', { type: 'button', class: 'markall', onclick: function (ev) {
        act(ev.currentTarget, function () {
          return api('GET', '/api/attention' + qs({ status: 'unacknowledged', include_closed: incl ? 'true' : '', limit: 1 })).then(function (c) {
            var n = c.unacknowledged_count;
            if (!n) return route();
            return confirmDialog('Mark all as seen?', n + (n === 1 ? ' item needs' : ' items need') + ' your attention. Mark ' + (n === 1 ? 'it' : 'them all') + ' as seen?', 'Cancel', 'Mark all seen').then(function (ok) {
              if (!ok) return null;
              return api('POST', '/api/attention/acknowledge-all' + qs({ include_closed: incl ? 'true' : '' })).then(function () { return route(); });
            });
          });
        });
      } }, svgIcon(CHECK_PATH), 'Mark all seen');
      root.appendChild(el('div', { class: 'pagehead' }, el('h1', { text: 'Attention' }), markAll));
      var statuses = me.account_type === 'agent' ? ['all', 'unacknowledged', 'processing', 'processed'] : ['all', 'unacknowledged', 'acknowledged'];
      var sel = el('select', { onchange: function () { location.hash = '#/attention' + qs({ status: sel.value, include_closed: incl ? 'true' : '' }); } },
        statuses.map(function (s) { return el('option', { value: s, text: s, selected: s === status }); }));
      var cb = el('input', { type: 'checkbox', checked: incl, onchange: function () { location.hash = '#/attention' + qs({ status: status, include_closed: cb.checked ? 'true' : '' }); } });
      root.appendChild(el('div', { class: 'ctl' }, el('label', { for: 'attn-status', text: 'Status' }), sel, el('label', { class: 'chk' }, cb, 'Include closed threads')));
      sel.id = 'attn-status';
      if (!r.items.length) root.appendChild(el('div', { class: 'empty', text: 'Nothing here.' }));
      var list = el('div', { class: 'list' }); var more = el('div', { class: 'pager' }); var offset = 0;
      root.appendChild(list); root.appendChild(more);
      function showPage(page) {
        page.items.forEach(function (m) {
          var box = el('div', { class: 'card' });
          var inFilter = true;
          var ctx = { closed: false, added: route, markable: true, onAttention: function (nm) {
            refreshAttentionCount();
            var now = nm.my_attention && nm.my_attention.status;
            // Keep the server offset in step when the item leaves or re-enters the filter.
            var nowIn = status === 'all' || now === status;
            if (nowIn !== inFilter) { inFilter = nowIn; offset += nowIn ? 1 : -1; }
            if (status !== 'all' && now !== status && (now === 'acknowledged' || now === 'processed')) {
              box.remove();
              if (!list.firstChild && !more.firstChild) root.insertBefore(el('div', { class: 'empty', text: 'Nothing here.' }), list);
            }
          } };
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
    var root = el('div', { class: 'screen' }); root.appendChild(el('h1', { text: 'Search' }));
    var cb = el('input', { type: 'checkbox', checked: incl, onchange: function () { location.hash = '#/search' + qs({ q: q, include_closed: cb.checked ? 'true' : '' }); } });
    root.appendChild(el('div', { class: 'ctl' }, q ? el('span', { text: 'Results for "' + q + '"' }) : null, el('label', { class: 'chk' }, cb, 'Include closed threads')));
    if (!q) { root.appendChild(el('div', { class: 'empty', text: 'Type a query in the search box.' })); return Promise.resolve(root); }
    var offsets = { areas: 0, threads: 0, messages: 0 };
    // Wrap each case-insensitive match of the query (the API matches it as one substring) in <mark>.
    var termRe = new RegExp(q.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    function mark(node) {
      if (!q.trim()) return node;
      var walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT), texts = [], t;
      while ((t = walker.nextNode())) texts.push(t);
      texts.forEach(function (tn) {
        var s = tn.nodeValue, parts = [], last = 0, m;
        termRe.lastIndex = 0;
        while ((m = termRe.exec(s))) {
          parts.push(document.createTextNode(s.slice(last, m.index)), el('mark', { text: m[0] }));
          last = m.index + m[0].length;
        }
        if (!parts.length) return;
        parts.push(document.createTextNode(s.slice(last)));
        parts.forEach(function (p) { tn.parentNode.insertBefore(p, tn); });
        tn.parentNode.removeChild(tn);
      });
      return node;
    }
    function fetchPage() {
      return api('GET', '/api/search' + qs({ q: q, include_closed: incl ? 'true' : '', limit: SEARCH_PAGE,
        areas_offset: offsets.areas, threads_offset: offsets.threads, messages_offset: offsets.messages }));
    }
    return fetchPage().then(function (r) {
      if (!r.areas.length && !r.threads.length && !r.messages.length) root.appendChild(el('div', { class: 'empty', text: 'No results.' }));
      var cats = {
        areas: { title: 'Areas', draw: function (a) { return el('div', { class: 'card' }, mark(el('a', { href: '#/area/' + areaRef(a), text: a.name })), mark(el('div', { class: 'body mut', text: a.snippet }))); } },
        threads: { title: 'Threads', draw: function (t) { return el('div', { class: 'card' }, mark(el('a', { href: '#/thread/' + t.id }, renderInline(t.title, true))), ' ', modified(t), ' ', el('span', { class: 'mut', text: t.area_name }), t.closed_reason ? el('span', { class: 'badge closed', text: ' closed: ' + t.closed_reason }) : null); } },
        messages: { title: 'Messages', draw: function (m) {
          return el('div', { class: 'card' },
            el('div', { class: 'mut' }, m.area_name + ' › ', mark(el('a', { href: '#/thread/' + m.thread_id }, renderInline(m.thread_title, true))), ' · ', userTag(m.author), ' · ' + fmt(m.created_at), ' ', modified(m),
              m.closed_reason ? el('span', { class: 'badge closed', text: 'closed: ' + m.closed_reason }) : null),
            mark(el('div', { class: 'body', text: m.snippet })),
            el('a', { href: '#/context/' + m.id, text: 'Show context' }));
        } }
      };
      Object.keys(cats).forEach(function (k) {
        var c = cats[k];
        c.list = el('div', { class: 'list' }); c.more = el('div', { class: 'pager hidden' });
        c.box = el('section', { class: 'list' + (r[k].length ? '' : ' hidden') }, el('h2', { text: c.title }), c.list, c.more);
        root.appendChild(c.box);
      });
      function showCat(k, page) {
        var c = cats[k];
        page[k].forEach(function (x) { c.list.appendChild(c.draw(x)); });
        offsets[k] += page[k].length;
        if (offsets[k]) c.box.classList.remove('hidden');
        clear(c.more); c.more.classList.toggle('hidden', !page.has_more[k]);
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
    var root = el('div', { class: 'screen' }); root.appendChild(el('h1', { text: 'Activity' }));
    var list = el('ol', { class: 'timeline' }); var more = el('div', { class: 'pager' }); root.appendChild(list); root.appendChild(more);
    var lastId = null, lastDay = null, thisYear = new Date().getFullYear();
    // left column: the date once per day (month over day), then the time of each event
    function when(iso) {
      var d = new Date(iso), day = d.toDateString(), first = day !== lastDay;
      lastDay = day;
      var mo = d.toLocaleDateString(undefined, { month: 'short' }).toUpperCase() + (d.getFullYear() !== thisYear ? ' ' + d.getFullYear() : '');
      return el('div', { class: 'when' },
        first ? el('span', { class: 'day' }, el('span', { class: 'mo', text: mo }), el('span', { class: 'dy', text: String(d.getDate()) })) : null,
        el('time', { datetime: iso, title: fmt(iso), text: d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }) }));
    }
    function load() {
      clear(more); more.appendChild(el('div', { class: 'loading', text: 'Loading…' }));
      return api('GET', '/api/activity' + qs({ limit: 50, before_id: lastId })).then(function (r) {
        clear(more);
        if (!r.events.length && lastId === null) root.replaceChild(el('div', { class: 'empty', text: 'No activity yet.' }), list);
        r.events.forEach(function (e) {
          lastId = e.id;
          var href = e.message_id ? '#/context/' + e.message_id
            : e.thread_id ? '#/thread/' + e.thread_id : e.area_id ? '#/area/' + areaRef(e) : '#/';
          var w = when(e.created_at);
          list.appendChild(el('li', { class: 'tl k-' + e.kind + (w.querySelector('.day') ? ' newday' : '') }, w,
            el('span', { class: 'dot', 'aria-hidden': 'true' }),
            el('div', { class: 'what' },
              el('div', null, who(e.actor), ' ' + (KIND[e.kind] || e.kind) + ' ', el('a', { href: href, text: e.thread_title || e.area_name || 'item' })),
              el('div', { class: 'where', text: (e.area_name || '') + (e.kind === 'thread_closed' && e.detail ? ' · ' + e.detail : '') }))));
        });
        if (r.events.length >= 50) more.appendChild(el('button', { type: 'button', text: 'Load more', onclick: function (ev) { act(ev.currentTarget, load); } }));
      }).catch(function (e) { clear(more); more.appendChild(errBox(e, function () { load(); })); });
    }
    return load().then(function () { return root; });
  }

  // ---------- users ----------
  function viewUsers() {
    return api('GET', '/api/users').then(function (r) {
      var root = el('div', { class: 'screen' }); root.appendChild(el('h1', { text: 'Users' }));
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
      var root = el('div', { class: 'screen' }); root.appendChild(el('h1', { text: 'Accounts' }));
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
        root.appendChild(el('div', { class: 'card' }, userTag(u), ' ', u.is_superadmin ? el('span', { class: 'badge super', text: 'superadmin' }) : null));
      });
      return root;
    });
  }

  boot();
})();
