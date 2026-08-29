(() => {
  const sidebar = document.getElementById('sidebar');
  const scrim = document.getElementById('sidebar-scrim');
  const trigger = document.getElementById('mobile-menu');
  const search = document.getElementById('global-search');
  const jobFilter = document.getElementById('job-filter');
  const jobFilterCount = document.getElementById('job-filter-count');
  const jobRows = Array.from(document.querySelectorAll('.job-row'));

  const setMenu = (open) => {
    document.body.classList.toggle('nav-open', open);
    trigger?.setAttribute('aria-expanded', String(open));
  };

  trigger?.addEventListener('click', () => setMenu(!document.body.classList.contains('nav-open')));
  scrim?.addEventListener('click', () => setMenu(false));
  sidebar?.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => setMenu(false)));

  jobFilter?.addEventListener('input', () => {
    const query = jobFilter.value.trim().toLocaleLowerCase();
    let visible = 0;
    jobRows.forEach((row) => {
      const matches = !query || row.textContent.toLocaleLowerCase().includes(query);
      row.hidden = !matches;
      if (matches) visible += 1;
    });
    if (jobFilterCount) jobFilterCount.textContent = `${visible} shown`;
  });

  document.addEventListener('keydown', (event) => {
    const target = event.target;
    const editing = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target?.isContentEditable;
    if (event.key === '/' && !editing) {
      event.preventDefault();
      search?.focus();
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      search?.focus();
    }
    if (event.key === 'Escape') {
      setMenu(false);
      search?.blur();
    }
  });
})();
