(() => {
  const button = document.getElementById('accountLogout');
  const error = document.getElementById('logoutError');
  button?.addEventListener('click', async () => {
    button.disabled = true;
    error.hidden = true;
    try {
      const response = await fetch('/api/access/logout', {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'}, body: '{}'
      });
      if (!response.ok) throw new Error('退出失败，请重试。');
      location.replace('/login');
    } catch (e) {
      error.textContent = e.message;
      error.hidden = false;
      button.disabled = false;
    }
  });
})();
