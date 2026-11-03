'use strict';

const $ = (selector) => document.querySelector(selector);
const root = document.documentElement;
const themeButton = $('#theme-toggle');
function setTheme(theme) {
  root.dataset.theme = theme;
  const next = theme === 'dark' ? 'light' : 'dark';
  themeButton.textContent = `${next[0].toUpperCase()}${next.slice(1)} theme`;
  themeButton.setAttribute('aria-label', `Switch to ${next} theme`);
}
let savedTheme;
try { savedTheme = localStorage.getItem('ris-guide-theme'); } catch { /* Local storage may be unavailable. */ }
setTheme(savedTheme === 'dark' || savedTheme === 'light' ? savedTheme :
  window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
themeButton.addEventListener('click', () => {
  const theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
  setTheme(theme);
  try { localStorage.setItem('ris-guide-theme', theme); } catch { /* Theme still works for this visit. */ }
});

const menuButton = $('#menu-toggle');
const sidebar = $('#sidebar');
function closeMenu(restoreFocus = false) {
  sidebar.classList.remove('open');
  menuButton.setAttribute('aria-expanded', 'false');
  if (restoreFocus) menuButton.focus();
}
menuButton.addEventListener('click', () => {
  const open = sidebar.classList.toggle('open');
  menuButton.setAttribute('aria-expanded', String(open));
  if (open) $('#guide-search').focus();
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && sidebar.classList.contains('open')) closeMenu(true);
});
document.addEventListener('click', (event) => {
  if (sidebar.classList.contains('open') && !sidebar.contains(event.target) && !menuButton.contains(event.target)) closeMenu();
});
sidebar.addEventListener('click', (event) => {
  const anchor = event.target.closest('a[href^="#"]');
  if (!anchor) return;
  closeMenu();
  const target = document.getElementById(anchor.hash.slice(1));
  if (target) { target.tabIndex = -1; target.focus({ preventScroll: true }); }
});

let notificationTimer;
function notify(message) {
  const notice = $('#notification');
  notice.textContent = message;
  notice.classList.add('visible');
  clearTimeout(notificationTimer);
  notificationTimer = setTimeout(() => notice.classList.remove('visible'), 3500);
}
document.querySelectorAll('[data-copy]').forEach((button) => button.addEventListener('click', async () => {
  const text = document.getElementById(button.dataset.copy).textContent.trim();
  if (!text) return;
  try {
    if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
    await navigator.clipboard.writeText(text);
    notify('Command copied. Review it before running locally.');
  } catch {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(document.getElementById(button.dataset.copy));
    selection.removeAllRanges();
    selection.addRange(range);
    notify('Command selected. Use your browser’s Copy action.');
  }
}));

const sections = [...document.querySelectorAll('.searchable')];
const results = $('#search-results');
$('#guide-search').addEventListener('input', (event) => {
  const query = event.target.value.trim().toLocaleLowerCase();
  results.replaceChildren();
  if (!query) return;
  const matches = sections.filter((section) => section.textContent.toLocaleLowerCase().includes(query));
  if (!matches.length) { results.textContent = 'No matching sections. Try a different term.'; return; }
  matches.forEach((section) => {
    const link = document.createElement('a');
    link.href = `#${section.id}`;
    link.textContent = section.dataset.title;
    results.append(link);
  });
});

const mode = $('#build-mode');
const session = $('#session-id');
const executable = $('#executable-path');
const processArguments = $('#process-arguments');
const sourceSession = $('#source-session-id');
const grantAccess = $('#grant-access');
const waiting = $('#wait-process');
const timeout = $('#timeout-value');
const output = $('#generated-command code');
const builderStatus = $('#builder-status');
const quotePowerShell = (value) => `'${value.replaceAll("'", "''")}'`;
function buildCommand() {
  const system = mode.value === 'system';
  $('#program-field').hidden = !system;
  for (const id of ['executable-field', 'arguments-field', 'wait-field', 'source-field']) $(`#${id}`).hidden = system;
  $('#timeout-field').hidden = system || !waiting.checked;
  const crossSession = !system && sourceSession.value !== '' && Number(sourceSession.value) !== Number(session.value);
  $('#grant-field').hidden = !crossSession;
  let error = '';
  if (!system && sourceSession.value !== '' && (!/^\d+$/.test(sourceSession.value) || Number(sourceSession.value) < 1 || Number(sourceSession.value) > 4294967294)) error = 'Enter a positive source session ID or leave it empty.';
  if (crossSession && mode.value === 'launch' && !grantAccess.checked) error = 'Cross-session launch requires explicit desktop access consent.';
  const sessionId = Number(session.value);
  if (!/^\d+$/.test(session.value) || !Number.isSafeInteger(sessionId) || sessionId < 1 || sessionId > 4294967294) error = 'Enter a valid positive Windows session ID.';
  const path = executable.value;
  if (!system && (!/^(?:[a-z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+[\\/])/i.test(path) || /["\r\n\0]/.test(path))) error = 'Enter an absolute executable path without surrounding quotes or line breaks.';
  if (!system && /[\r\n\0]/.test(processArguments.value)) error = 'Use a single line for process arguments.';
  if (!system && waiting.checked && (timeout.value.trim() === '' || !Number.isFinite(Number(timeout.value)) || Number(timeout.value) < 0 || Number(timeout.value) >= 4294967.295)) error = 'Enter a timeout from 0 to less than 4294967.295 seconds.';
  $('#builder-copy').disabled = Boolean(error);
  builderStatus.classList.toggle('invalid', Boolean(error));
  if (error) { output.textContent = '# Complete the fields above to generate a command.'; builderStatus.textContent = error; return; }
  const file = system ? 'launch_as_system.py' : 'run_in_session.py';
  const parts = [`python .\\${file}`];
  if (system) parts.push('--program', $('#program-name').value);
  parts.push('--session', String(sessionId));
  if (!system) {
    parts.push('--exe', quotePowerShell(path));
    if (sourceSession.value) parts.push('--source-session', String(Number(sourceSession.value)));
    if (crossSession && grantAccess.checked) parts.push('--grant-desktop-access');
    if (processArguments.value) parts.push(`--args=${quotePowerShell(processArguments.value)}`);
    if (waiting.checked) parts.push('--wait', '--timeout', String(Number(timeout.value)));
    if (mode.value === 'simulate') parts.push('--dry-run');
  }
  output.textContent = parts.join(' ');
  builderStatus.textContent = system ? 'Run from administrator PowerShell. Requests a SYSTEM GUI in the selected session.' :
    mode.value === 'simulate' ? 'Simulation only. No target process will be launched.' :
      'Actual launch. The launcher must run as SYSTEM; the target uses the source account token. Cross-session grants require the launcher in the destination session.';
}
$('#command-form').addEventListener('input', (event) => { if (event.target === sourceSession || event.target === session) grantAccess.checked = false; buildCommand(); });
$('#command-form').addEventListener('change', buildCommand);
$('#command-form').addEventListener('submit', (event) => event.preventDefault());
buildCommand();

const navigation = [...document.querySelectorAll('.nav-link')];
let scrollQueued = false;
function updateReading() {
  const available = root.scrollHeight - window.innerHeight;
  $('.reading-progress').style.width = `${available > 0 ? Math.min(100, Math.max(0, window.scrollY / available * 100)) : 0}%`;
  let current = sections[0].id;
  sections.forEach((section) => { if (section.getBoundingClientRect().top <= 150) current = section.id; });
  navigation.forEach((link) => {
    const active = link.hash === `#${current}`;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'location');
    else link.removeAttribute('aria-current');
  });
  scrollQueued = false;
}
window.addEventListener('scroll', () => { if (!scrollQueued) { scrollQueued = true; requestAnimationFrame(updateReading); } }, { passive: true });
window.addEventListener('resize', () => { if (window.innerWidth > 800) closeMenu(); updateReading(); });
updateReading();
$('#print-guide').addEventListener('click', () => window.print());
let closedForPrint = [];
window.addEventListener('beforeprint', () => { closedForPrint = [...document.querySelectorAll('details:not([open])')]; closedForPrint.forEach((item) => { item.open = true; }); });
window.addEventListener('afterprint', () => closedForPrint.forEach((item) => { item.open = false; }));
