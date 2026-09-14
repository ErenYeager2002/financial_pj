/** Copy an identifier, keeping a selectable fallback on restricted origins. */
export async function copyNumber(value: string, target: HTMLElement): Promise<boolean> {
  const doc = target.ownerDocument;
  const view = doc.defaultView;
  if (view?.isSecureContext && view.navigator.clipboard?.writeText) {
    try {
      await view.navigator.clipboard.writeText(value);
      return true;
    } catch {
      // Permission can be denied even when the modern API is available.
    }
  }

  const input = doc.createElement('textarea');
  input.value = value;
  input.readOnly = true;
  input.tabIndex = -1;
  input.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;font-size:16px;';
  // Stay inside the current dialog so its focus trap does not steal selection.
  (target.parentElement ?? doc.body).appendChild(input);
  let copied = false;
  try {
    input.focus({ preventScroll: true });
    input.select();
    input.setSelectionRange(0, value.length);
    copied = doc.execCommand('copy');
  } catch {
    copied = false;
  } finally {
    input.remove();
    target.focus({ preventScroll: true });
  }

  if (!copied) {
    const selection = view?.getSelection();
    const range = doc.createRange();
    range.selectNodeContents(target);
    selection?.removeAllRanges();
    selection?.addRange(range);
  }
  return copied;
}
