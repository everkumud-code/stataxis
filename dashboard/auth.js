(() => {
  const panel = document.querySelector('#auth-panel');
  const form = document.querySelector('#auth-form');
  const open = document.querySelector('#auth-open');
  const close = document.querySelector('#auth-close');
  const mode = document.querySelector('#auth-mode');
  const title = document.querySelector('#auth-title');
  const message = document.querySelector('#auth-message');
  const plan = document.querySelector('#auth-plan');
  const email = document.querySelector('#auth-email');
  const tokenKey = 'stataxis_access_token';
  const accountKey = 'stataxis_account';
  let registerMode = false;
  const readAccount = () => { try { return JSON.parse(localStorage.getItem(accountKey) || 'null'); } catch (_) { return null; } };
  const setText = (selector, value) => { const node = document.querySelector(selector); if (node) node.textContent = value; };
  const isApproved = () => { const account = readAccount(); return !!(localStorage.getItem(tokenKey) && account && (account.is_admin || account.approval_status === 'approved')); };

  // Client-side UX lock complements the server-side authorization boundary.
  const realFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    if (url && url.startsWith('/api/') && !url.includes('/api/v1/auth/') && !isApproved()) {
      return Promise.reject(new Error('StatAxis access requires an approved profile'));
    }
    return realFetch(input, init);
  };

  const refresh = () => {
    const account = readAccount();
    const approved = isApproved();
    plan.textContent = approved ? (account.plan_name || account.plan || 'SX') : (account?.approval_status === 'pending' ? 'PENDING APPROVAL' : 'DEMO');
    email.textContent = account?.email || 'Not signed in';
    open.textContent = approved ? 'Sign out' : 'Open Profile'; open.dataset.action = approved ? 'logout' : 'signin';
    setText('#evaluate-status', approved ? 'Approved profile. Ready to use StatAxis.' : account?.approval_status === 'pending' ? 'Profile submitted. Waiting for admin approval.' : 'Create a profile and submit it for admin approval.');
    setText('#aud-status', approved ? 'Approved profile. Live audience intelligence is available.' : 'Demo data only. Create a profile and wait for admin approval to use live intelligence.');
    if (approved) {
      document.querySelectorAll('.preview-locked').forEach((node) => node.classList.remove('preview-locked'));
      ['#evaluate-submit', '#aud-start-monitor', '#aud-load-window'].forEach((selector) => document.querySelector(selector)?.removeAttribute('disabled'));
    }
  };
  const showPanel = () => { panel.hidden = false; document.querySelector('#auth-email-input')?.focus(); };
  const profileFields = `<label><span>Name</span><input name="name" type="text" required maxlength="255" autocomplete="name" placeholder="Your full name"></label><label><span>Organization email</span><input id="auth-email-input" name="email" type="email" required autocomplete="email" placeholder="you@organization.com"></label><label><span>Mobile number</span><input name="mobile" type="tel" required maxlength="32" autocomplete="tel" placeholder="+91 …"></label><label><span>Organization</span><input name="organization" type="text" required maxlength="255" placeholder="Company / newsroom / institution"></label><label><span>Purpose of use</span><textarea name="purpose_of_use" required maxlength="2000" rows="3" placeholder="Tell us how you intend to use StatAxis"></textarea></label><label><span>Select package</span><select name="requested_plan" required><option value="sx_idea">SX Idea</option><option value="sx_intelligence">SX Intelligence</option><option value="sx_analyst">SX Analyst</option><option value="sx_pro">SX Pro</option><option value="sx_corporate">SX Corporate</option><option value="sx_enterprise">SX Enterprise</option></select></label><label><span>Create password</span><input name="password" type="password" required minlength="12" autocomplete="new-password" placeholder="Minimum 12 characters"></label><button type="submit">Submit for Approval</button>`;
  const setMode = (register) => {
    registerMode = register; title.textContent = register ? 'Request a StatAxis Profile' : 'Sign in to StatAxis'; mode.textContent = register ? 'Already approved? Sign in' : 'Create a profile'; message.textContent = '';
    form.innerHTML = register ? profileFields : `<label><span>Organization email</span><input id="auth-email-input" name="email" type="email" required autocomplete="email" placeholder="you@organization.com"></label><label><span>Password</span><input name="password" type="password" required minlength="12" autocomplete="current-password"></label><button type="submit">Sign in</button>`;
  };
  open?.addEventListener('click', () => { if (open.dataset.action === 'logout') { localStorage.removeItem(tokenKey); localStorage.removeItem(accountKey); refresh(); window.dispatchEvent(new Event('stataxis-auth-changed')); return; } setMode(false); showPanel(); });
  close?.addEventListener('click', () => { panel.hidden = true; });
  mode?.addEventListener('click', () => { setMode(!registerMode); });
  form?.addEventListener('submit', async (event) => {
    event.preventDefault(); const currentSubmit = form.querySelector('button[type="submit"]'); currentSubmit.disabled = true; message.textContent = '';
    const payload = Object.fromEntries(new FormData(form).entries());
    try {
      const response = await realFetch(registerMode ? '/api/v1/auth/register' : '/api/v1/auth/login', { method: 'POST', headers: {'Content-Type': 'application/json', Accept: 'application/json'}, body: JSON.stringify(payload) });
      const data = await response.json(); if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
      if (registerMode) { localStorage.removeItem(tokenKey); localStorage.setItem(accountKey, JSON.stringify(data.account)); message.textContent = 'Application submitted. Your StatAxis workspace will remain locked until admin approval.'; refresh(); }
      else { localStorage.setItem(tokenKey, data.access_token); localStorage.setItem(accountKey, JSON.stringify(data.account || data.user)); form.reset(); panel.hidden = true; refresh(); window.dispatchEvent(new Event('stataxis-auth-changed')); }
    } catch (error) { message.textContent = error.message || 'Request failed'; } finally { currentSubmit.disabled = false; }
  });
  const cta = document.querySelector('.public-cta');
  if (cta) { const badge = document.createElement('div'); badge.className = 'demo-banner'; badge.textContent = 'DEMO DATA — This dashboard is a preview. Live StatAxis data requires admin-approved access.'; cta.prepend(badge); const how = document.createElement('button'); how.type = 'button'; how.className = 'ghost-button'; how.textContent = 'How to Use'; how.addEventListener('click', () => { window.location.href = '/guide.html'; }); cta.querySelector('div')?.appendChild(how); }
  refresh();
})();
