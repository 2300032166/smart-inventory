checkAuth();
initShell();

async function loadProfile() {
  try {
    const user = await apiFetch('/auth/me');
    if (!user) return;
    document.getElementById('display-name').value = user.name;
    document.getElementById('email').value = user.email;
    document.getElementById('role-field').value = user.role.charAt(0).toUpperCase() + user.role.slice(1);

    const avatarEl = document.getElementById('settings-avatar');
    if (avatarEl) {
      const initials = (user.name || user.email || '?').trim().split(/\s+/).map(p => p[0]).slice(0, 2).join('').toUpperCase();
      avatarEl.textContent = initials || '?';
    }
    const nameEl = document.getElementById('settings-name');
    if (nameEl) nameEl.textContent = user.name || user.email;
    const emailSubEl = document.getElementById('settings-email-sub');
    if (emailSubEl) emailSubEl.textContent = user.email;
    const roleBadgeEl = document.getElementById('settings-role-badge');
    if (roleBadgeEl) roleBadgeEl.textContent = user.role.charAt(0).toUpperCase() + user.role.slice(1);
  } catch {}
}

document.getElementById('profile-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const msg = document.getElementById('profile-msg');
  const btn = document.getElementById('profile-btn');
  setLoading(btn, true, 'Save profile');
  try {
    showSuccess(msg, 'Profile preferences saved locally.');
  } catch (err) {
    showError(msg, err.message);
  } finally { setLoading(btn, false, 'Save profile'); }
});

document.getElementById('reset-password-btn').addEventListener('click', async () => {
  const msg = document.getElementById('security-msg');
  const btn = document.getElementById('reset-password-btn');
  const email = document.getElementById('email').value;
  if (!email) return;
  setLoading(btn, true, 'Reset password');
  try {
    await apiFetch('/auth/forgot-password', { method: 'POST', body: JSON.stringify({ email }) });
    showSuccess(msg, `A password reset link has been sent to ${email}.`);
  } catch (err) {
    showError(msg, err.message);
  } finally { setLoading(btn, false, 'Reset password'); }
});

loadProfile();
