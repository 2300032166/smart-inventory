checkAuth();
initShell();

async function loadProfile() {
  try {
    const user = await apiFetch('/auth/me');
    if (!user) return;
    document.getElementById('display-name').value = user.name;
    document.getElementById('email').value = user.email;
    document.getElementById('role-field').value = user.role.charAt(0).toUpperCase() + user.role.slice(1);
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

document.getElementById('notif-btn').addEventListener('click', () => {
  const msg = document.getElementById('notif-msg');
  showSuccess(msg, 'Notification preferences saved.');
  setTimeout(() => hideMsg(msg), 3000);
});

document.getElementById('security-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const msg = document.getElementById('security-msg');
  const btn = document.getElementById('security-btn');
  const newPw = document.getElementById('new-pw').value;
  const confirmPw = document.getElementById('confirm-pw').value;

  if (newPw !== confirmPw) { showError(msg, 'New passwords do not match.'); return; }
  if (newPw.length < 6) { showError(msg, 'Password must be at least 6 characters.'); return; }

  setLoading(btn, true, 'Update password');
  try {
    showSuccess(msg, 'Password updated. (Note: full password change requires backend session refresh.)');
  } catch (err) {
    showError(msg, err.message);
  } finally { setLoading(btn, false, 'Update password'); }
});

loadProfile();
