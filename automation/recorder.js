(() => {
  if (window.top !== window || window.__testboxRecorder) return;
  const prefix = __TESTBOX_PREFIX__, initialMode = __TESTBOX_MODE__;
  let mode = initialMode, outlined = null, suppressClickUntil = 0;
  const pending = new Map();
  const emit = data => console.info(prefix + JSON.stringify(data));
  function clearOutline() {
    if (outlined) { outlined.element.style.outline = outlined.old; outlined = null; }
  }
  function candidates(element) {
    if (!(element instanceof Element) || element.getRootNode() !== document) return [];
    const result = [], esc = CSS.escape;
    const unique = selector => { try { return document.querySelectorAll(selector).length === 1; } catch { return false; } };
    if (element.id && unique('#' + esc(element.id))) result.push('id=' + element.id);
    for (const attr of ['data-testid', 'data-test', 'name', 'aria-label']) {
      const value = element.getAttribute(attr);
      const selector = element.tagName.toLowerCase() + '[' + attr + '="' + esc(value || '') + '"]';
      if (value && unique(selector)) result.push('css=' + selector);
    }
    let node = element, path = [];
    while (node && node.nodeType === 1) {
      const tag = node.tagName.toLowerCase();
      if (node.id && unique('#' + esc(node.id))) { path.unshift('#' + esc(node.id)); break; }
      const siblings = node.parentElement ? [...node.parentElement.children].filter(e => e.tagName === node.tagName) : [node];
      path.unshift(tag + (siblings.length > 1 ? ':nth-of-type(' + (siblings.indexOf(node) + 1) + ')' : ''));
      node = node.parentElement;
    }
    if (path.length && unique(path.join(' > '))) result.push('css=' + path.join(' > '));
    return [...new Set(result)];
  }
  function elementOf(event) { return event.composedPath ? event.composedPath()[0] : event.target; }
  function info(element) {
    const targets = candidates(element), password = element.type === 'password';
    return {targets, tag: element.tagName.toLowerCase(), text: (element.innerText || element.textContent || '').slice(0, 2000),
      value: password ? '${password}' : String(element.value || '').slice(0, 2000), checked: !!element.checked, password};
  }
  function step(command, element, value = '') {
    const targets = candidates(element);
    if (!targets.length) { emit({event: 'warning', message: 'No top-document locator: review this action manually (shadow DOM is not recorded).'}); return; }
    emit({event: 'step', command, target: targets[0], value, sensitive: element.type === 'password'});
  }
  function recordField(element) {
    if (mode !== 'record' || !element || !element.matches('input,textarea,select')) return;
    const timer = pending.get(element); if (timer) clearTimeout(timer); pending.delete(element);
    if (element.matches('select')) {
      if (element.multiple) { emit({event: 'warning', message: 'Multiple selection needs manual steps.'}); return; }
      step('select_value', element, element.value); return;
    }
    if (element.type === 'checkbox' || element.type === 'radio') { step('check', element, String(element.checked)); return; }
    if (element.type === 'file') { step('upload', element, '${upload_file}'); return; }
    const value = element.type === 'password' ? '${password}' : element.value;
    if (value.length > 100000) { emit({event: 'warning', message: 'Input exceeds recorder limit (100000 characters); supply it through a dataset.'}); return; }
    step('type', element, value);
  }
  function flush() { for (const element of [...pending.keys()]) recordField(element); }
  window.__testboxRecorder = {
    setMode(next) { flush(); clearOutline(); mode = next; return mode; },
    flush, candidates
  };
  window.addEventListener('input', event => {
    if (mode !== 'record') return;
    const element = elementOf(event);
    if (!element || !element.matches('input,textarea')) return;
    const timer = pending.get(element); if (timer) clearTimeout(timer);
    pending.set(element, setTimeout(() => recordField(element), 350));
  }, true);
  window.addEventListener('change', event => { if (mode === 'record') recordField(elementOf(event)); }, true);
  window.addEventListener('keydown', event => {
    if (mode === 'record' && ['Enter', 'Tab', 'Escape'].includes(event.key)) {
      flush();
      step('press_key', elementOf(event), {Enter:'ENTER',Tab:'TAB',Escape:'ESCAPE'}[event.key]);
      if (event.key === 'Enter') suppressClickUntil = Date.now() + 300;
    }
  }, true);
  window.addEventListener('click', event => {
    const element = elementOf(event);
    if (!(element instanceof Element)) return;
    if (mode === 'pick') {
      event.preventDefault(); event.stopImmediatePropagation(); clearOutline(); mode = 'idle';
      emit({event: 'picked', ...info(element)}); return;
    }
    if (mode !== 'record') return;
    flush();
    if (event.detail === 0 && Date.now() < suppressClickUntil) return;
    const interactive = element.closest('button,a,input[type=submit],input[type=button],[role=button]');
    if (interactive) step('click', interactive);
  }, true);
  window.addEventListener('mousemove', event => {
    if (mode !== 'pick') return;
    const element = elementOf(event);
    if (!(element instanceof Element) || outlined && outlined.element === element) return;
    clearOutline(); outlined = {element, old: element.style.outline}; element.style.outline = '3px solid #ea8a23';
  }, true);
  window.addEventListener('pagehide', flush, true);
  emit({event: 'document', url: location.href, title: document.title});
})();
