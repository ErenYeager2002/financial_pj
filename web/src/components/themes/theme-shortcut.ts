interface ThemeShortcutEvent {
  key?: unknown;
  shiftKey?: boolean;
  metaKey?: boolean;
  ctrlKey?: boolean;
}

export function isThemeToggleShortcut(event: ThemeShortcutEvent): boolean {
  if (typeof event.key !== 'string') return false;
  return (
    event.key.toLowerCase() === 'd' &&
    event.shiftKey === true &&
    (event.metaKey === true || event.ctrlKey === true)
  );
}
