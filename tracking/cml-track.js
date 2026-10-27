/* Camaleão first-party event adapter. Contact fields never enter the analytics queue. */
(function (root) {
  'use strict';
  const VERSION = '1.0.0';
  const KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'];
  function safeLabel(value) {
    const s = String(value || '').trim().slice(0, 100);
    if (!/^[\p{L}\p{N}_. /:-]*$/u.test(s) || /\d{8,}/.test(s)) return '';
    return s;
  }
  function safePath(value) {
    try {
      const path = new URL(value, 'https://example.com').pathname;
      return /^\/(?:[a-z0-9_-]+\/)*[a-z0-9_.-]*$/i.test(path) && !/\d{8,}|@/i.test(path) ? path.slice(0, 300) : '/';
    } catch (_) { return '/'; }
  }
  function touch(url, referrer) {
    const u = new URL(url);
    let ref;
    try { ref = new URL(referrer); } catch (_) { ref = null; }
    const campaign = Object.fromEntries(KEYS.map(k => [k, safeLabel(u.searchParams.get(k))]));
    const external = ref && ref.hostname !== u.hostname;
    let source = campaign.utm_source;
    if (!source && external) {
      if (/(^|\.)(google\.[a-z.]+|bing\.com|duckduckgo\.com)$/.test(ref.hostname)) source = 'organic-search';
      else if (/(^|\.)(instagram\.com|l\.instagram\.com)$/.test(ref.hostname)) source = 'instagram';
      else source = 'referral';
    }
    return {...campaign, source: source || 'direct', landing_path: safePath(u.href),
      referrer_host: external ? ref.hostname.slice(0, 100) : '', external: !!external};
  }
  if (typeof module !== 'undefined' && module.exports) { module.exports = {safeLabel, safePath, touch}; return; }
  if (!root || root.CMLTracking) return;
  const doc = root.document, script = doc.currentScript;
  const gtm = script && script.dataset.gtm, measurement = script && script.dataset.ga4;
  if (!/^GTM-[A-Z0-9]+$/.test(gtm || '') || !/^G-[A-Z0-9]+$/.test(measurement || '')) return;
  const STORE = 'cml-analytics-v1', TTL = 180 * 86400000;
  let consent = false, loaded = false, pageSent = false, first = null, last = null;
  const current = touch(root.location.href, doc.referrer);
  const article = root.location.pathname.match(/-(\d+)\/$/);
  const pageType = root.location.pathname.startsWith('/blog/') ? (article ? 'article' : 'blog') : 'lp';
  function read() { try { return JSON.parse(root.localStorage.getItem(STORE) || 'null'); } catch (_) { return null; } }
  function save(state) { try { root.localStorage.setItem(STORE, JSON.stringify(state)); } catch (_) {} }
  root.dataLayer = root.dataLayer || [];
  function gtag() { root.dataLayer.push(arguments); }
  gtag('consent', 'default', {analytics_storage: 'denied', ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied'});
  gtag('set', {page_location: root.location.origin + safePath(root.location.href),
    page_referrer: current.referrer_host ? 'https://' + current.referrer_host + '/' : '',
    page_title: pageType === 'lp' ? 'Site — Página principal' : 'Blog — ' + safePath(root.location.href),
    allow_google_signals: false, allow_ad_personalization_signals: false});
  // Explicitly override automatic URL campaign extraction with sanitized values.
  // Internal article links assist conversion without replacing acquisition.
  const internalCampaign = current.utm_source === 'blog';
  gtag('set', {campaign_id: '',
    campaign_source: internalCampaign ? '' : current.utm_source,
    campaign_medium: internalCampaign ? '' : current.utm_medium,
    campaign_name: internalCampaign ? '' : current.utm_campaign,
    campaign_content: internalCampaign ? '' : current.utm_content,
    campaign_term: internalCampaign ? '' : current.utm_term});
  function event(name, params) {
    if (!consent) return;
    // Deliberately build a fresh allowlisted object, never serialize a form.
    const data = {send_to: measurement, page_location: root.location.origin + safePath(root.location.href),
      page_referrer: current.referrer_host ? 'https://' + current.referrer_host + '/' : '',
      page_title: pageType === 'lp' ? 'Site — Página principal' : 'Blog — ' + safePath(root.location.href),
      page_type: pageType, tracking_version: VERSION};
    for (const key of ['form_id', 'event_id', 'content_id', 'cta_id', 'percent_scrolled', 'engagement_time_msec', 'error_type']) {
      if (params && params[key] !== undefined) data[key] = typeof params[key] === 'number' ? params[key] : safeLabel(params[key]);
    }
    if (article) data.content_id = article[1];
    gtag('event', name, data);
  }
  function enable() {
    const saved = read();
    const previous = saved && saved.choice === 'accepted' && Date.now() - saved.at < TTL ? saved : null;
    consent = true;
    first = previous && previous.first || current;
    // Internal blog-to-LP campaigns assist a journey, but do not replace acquisition.
    last = current.external || (current.utm_source && current.utm_source !== 'blog') ? current : previous && previous.last || current;
    save({choice: 'accepted', at: Date.now(), first, last});
    gtag('consent', 'update', {analytics_storage: 'granted', ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied'});
    if (!loaded) {
      loaded = true;
      root.dataLayer.push({'gtm.start': Date.now(), event: 'gtm.js'});
      const tag = doc.createElement('script'); tag.async = true;
      tag.src = 'https://www.googletagmanager.com/gtm.js?id=' + gtm;
      doc.head.appendChild(tag);
    }
    if (!pageSent) { pageSent = true; event('page_view'); }
  }
  function deny() {
    consent = false;
    first = last = null;
    save({choice: 'rejected', at: Date.now()});
    gtag('consent', 'update', {analytics_storage: 'denied', ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied'});
    doc.cookie.split(';').forEach(part => {
      const name = part.split('=')[0].trim();
      if (!/^_ga(?:_|$)/.test(name)) return;
      for (const domain of ['', ';domain=' + root.location.hostname, ';domain=.' + root.location.hostname])
        doc.cookie = name + '=;path=/;max-age=0;SameSite=Lax;Secure' + domain;
    });
  }
  function banner() {
    let box = doc.getElementById('cml-consent');
    if (box) { box.hidden = false; return; }
    box = doc.createElement('section'); box.id = 'cml-consent'; box.setAttribute('aria-label', 'Preferências de privacidade');
    box.innerHTML = '<strong>Podemos medir sua visita?</strong><p>Com sua permissão, usamos o Google Analytics para entender a navegação e melhorar o site. O formulário funciona mesmo se você recusar. Não enviamos seus dados de contato ao Analytics.</p><div><button type="button" data-choice="rejected">Recusar</button><button type="button" data-choice="accepted">Aceitar medição</button></div>';
    const style = doc.createElement('style');
    style.textContent = '#cml-consent{position:fixed;z-index:10000;bottom:16px;left:16px;max-width:440px;padding:20px;background:white;color:#291025;border:1px solid #e7dde3;border-radius:16px;box-shadow:0 8px 32px #18041422;font:15px/1.5 Arial,sans-serif}#cml-consent p{margin:8px 0 16px}#cml-consent div{display:flex;gap:10px;flex-wrap:wrap}#cml-consent button,#cml-privacy{font:inherit;border:1px solid #6c3a59;border-radius:8px;padding:9px 14px;background:white;color:#3a0927;cursor:pointer}#cml-consent button[data-choice="accepted"]{background:#3a0927;color:white}#cml-consent[hidden]{display:none}#cml-privacy{font:12px Arial,sans-serif;margin:12px}@media(max-width:500px){#cml-consent{right:12px;left:12px;bottom:12px}}';
    doc.head.appendChild(style); doc.body.appendChild(box);
    box.addEventListener('click', e => {
      const button = e.target.closest('[data-choice]');
      if (!button) return;
      if (button.dataset.choice === 'accepted') enable(); else deny();
      box.hidden = true;
    });
  }
  function id() { return root.crypto.randomUUID(); }
  const forms = new WeakMap();
  function state(form) {
    if (!forms.has(form)) forms.set(form, {id: id(), started: false, sent: false});
    return forms.get(form);
  }
  root.CMLTracking = {
    version: VERSION,
    payload(form) {
      const s = state(form);
      const payload = {lead_ref: s.id, form_id: form.id, landing_path: safePath(root.location.href), analytics_consent: consent ? 'accepted' : 'rejected', tracking_version: VERSION};
      if (consent) {
        payload.attribution_first = first;
        payload.attribution_last = last;
        payload.assisted_content = safeLabel(new URL(root.location.href).searchParams.get('utm_content'));
      }
      return payload;
    },
    submitted(form) {
      const s = state(form);
      if (!s.sent) { s.sent = true; event('generate_lead', {form_id: form.id, event_id: s.id}); }
    },
    failed(form, type) { event('form_error', {form_id: form.id, error_type: type}); },
    preferences: banner
  };
  doc.addEventListener('focusin', e => {
    const form = e.target.closest('form');
    if (!form || !['hero-lead-form', 'lead-form'].includes(form.id)) return;
    const s = state(form);
    if (!s.started) { s.started = true; event('form_start', {form_id: form.id}); }
  });
  doc.addEventListener('click', e => {
    const link = e.target.closest('a[href]'); if (!link) return;
    let url; try { url = new URL(link.href, root.location.href); } catch (_) { return; }
    if (url.protocol === 'tel:') event('phone_click', {cta_id: 'phone'});
    else if (/(^|\.)(wa\.me|whatsapp\.com)$/.test(url.hostname)) event('whatsapp_click', {cta_id: 'whatsapp'});
    else if (url.hostname === root.location.hostname && (url.hash === '#form-section' || (pageType !== 'lp' && url.pathname === '/')))
      event('cta_click', {cta_id: pageType === 'lp' ? 'lp-form' : 'blog-to-lp'});
  });
  const seen = new Set();
  root.addEventListener('scroll', () => {
    if (!consent) return;
    const height = doc.documentElement.scrollHeight - root.innerHeight;
    const percent = height > 0 ? Math.min(100, Math.floor(root.scrollY / height * 100)) : 100;
    for (const n of [25, 50, 75, 90]) if (percent >= n && !seen.has(n)) { seen.add(n); event('scroll_depth', {percent_scrolled: n}); }
  }, {passive: true});
  let active = 0;
  root.setInterval(() => {
    if (!consent || doc.visibilityState !== 'visible') return;
    active += 5;
    if ([30, 60, 120].includes(active)) event('engaged_read', {engagement_time_msec: 5000});
  }, 5000);
  const privacy = doc.createElement('button'); privacy.type = 'button'; privacy.id = 'cml-privacy'; privacy.textContent = 'Preferências de privacidade'; privacy.addEventListener('click', banner);
  (doc.querySelector('footer') || doc.body).appendChild(privacy);
  const stored = read();
  if (stored && Date.now() - stored.at < TTL) { if (stored.choice === 'accepted') enable(); }
  else banner();
})(typeof window === 'undefined' ? null : window);
