"""Persistent browser owned by a single Pi environment, never the host browser."""
from __future__ import annotations
import asyncio
import base64
import concurrent.futures
import json
import os
import socket
import sys
import threading
from pathlib import Path
from uuid import uuid4
from playwright.async_api import async_playwright
from pi_jobs import Connection, atomic

ROOT = Path('/workspace/.pi/browser')


class Browser:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.context = None
        self.disconnected = False
        self.playwright = None
        self.pages = {}
        self.references = {}
        self.lock = None

    def call(self, body):
        future = asyncio.run_coroutine_threadsafe(self.dispatch(body), self.loop)
        try:
            return future.result(timeout=40)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise ValueError('Browser observation timed out; inspect state before repeating any action') from None
        except Exception:
            raise ValueError('Browser operation failed; inspect the page before repeating an action') from None

    async def ensure(self):
        if self.context is not None and not self.disconnected:
            return
        if self.context is not None:
            await self.close(save=False)
        ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        profile = ROOT / 'profile'
        lock = profile / 'SingletonLock'
        if lock.is_symlink():
            owner = os.readlink(lock)
            host, _, pid = owner.rpartition('-')
            if host != socket.gethostname() or not pid.isdigit() or not Path('/proc/' + pid).exists():
                # One manager-owned container per workspace; an earlier stopped
                # container may leave Chromium's hostname/PID lock behind.
                for name in ('SingletonLock', 'SingletonCookie', 'SingletonSocket'):
                    target = profile / name
                    if target.is_symlink(): target.unlink()
        self.playwright = await async_playwright().start()
        try:
            self.context = await self.playwright.chromium.launch_persistent_context(
                str(ROOT / 'profile'), headless=True, viewport={'width': 1280, 'height': 800},
                proxy={'server': os.environ.get('HTTP_PROXY', 'http://pi-egress:8080'),
                       'bypass': 'localhost,127.0.0.1,[::1]'},
                args=['--no-sandbox', '--disable-dev-shm-usage'], accept_downloads=True,
                downloads_path='/workspace/outputs/browser-downloads')
        except BaseException:
            await self.close(save=False)
            raise
        self.disconnected = False
        self.context.on('close', lambda *_: setattr(self, 'disconnected', True))
        stored = ROOT / 'storage-state.json'
        if stored.exists():
            saved = json.loads(stored.read_text())
            # Persistent profiles retain localStorage, but Chromium drops
            # session cookies at shutdown. Restore our last explicit snapshot.
            await self.context.add_cookies(saved.get('cookies', []))
        self.context.set_default_timeout(10000)
        self.context.set_default_navigation_timeout(25000)
        self.context.on('page', self.track)
        for page in self.context.pages:
            self.track(page)
        if not self.pages:
            self.track(await self.context.new_page())

    def track(self, page):
        if page not in self.pages.values():
            self.pages[uuid4().hex[:12]] = page

    async def snapshot(self, tab_id, page):
        old = self.references.pop(tab_id, {})
        for handle in old.values():
            try: await handle.dispose()
            except Exception: pass
        refs = {}; elements = []
        handles = await page.locator('a,button,input,textarea,select,[role="button"],[contenteditable="true"]').element_handles()
        for handle in handles[:200]:
            if not await handle.is_visible():
                await handle.dispose(); continue
            details = await handle.evaluate("""e => ({tag:e.tagName.toLowerCase(),role:e.getAttribute('role')||'',type:e.getAttribute('type')||'',name:(e.getAttribute('aria-label')||Array.from(e.labels||[]).map(l=>l.innerText).join(' ')||e.innerText||e.getAttribute('placeholder')||e.getAttribute('name')||'').slice(0,250)})""")
            ref = uuid4().hex[:12]; refs[ref] = handle; elements.append({'ref':ref, **details})
        for handle in handles[200:]:
            await handle.dispose()
        self.references[tab_id] = refs
        text = await page.locator('body').inner_text(timeout=5000)
        return {'tab_id': tab_id, 'url': page.url, 'title': await page.title(),
                'text': text[:24000], 'text_truncated': len(text) > 24000,
                'elements': elements, 'elements_truncated': len(handles) > 200}

    async def save(self):
        if self.context:
            atomic(ROOT / 'storage-state.json', await self.context.storage_state())

    async def close(self, save=True):
        saved = False
        context, driver = self.context, self.playwright
        try:
            if context and save:
                try: await self.save(); saved = True
                except Exception: pass
            if context:
                try: await context.close()
                except Exception: pass
        finally:
            self.context = None; self.playwright = None
            self.pages.clear(); self.references.clear()
            if driver:
                try: await driver.stop()
                except Exception: pass
        return saved

    async def dispatch(self, body):
        if self.lock is None:
            self.lock = asyncio.Lock()
        async with self.lock:
            action = body.get('action')
            if action not in {'navigate','snapshot','click','fill','press','screenshot','tabs','new_tab','close_tab','close'}:
                raise ValueError('Invalid browser action')
            if action == 'close':
                return {'closed': True, 'state_saved': await self.close()}
            await self.ensure()
            self.pages = {key:page for key,page in self.pages.items() if not page.is_closed()}
            if action == 'new_tab' or not self.pages:
                page = await self.context.new_page(); self.track(page)
                tab_id = next(key for key,value in self.pages.items() if value is page)
            else:
                tab_id = body.get('tab_id') or next(iter(self.pages))
                if tab_id not in self.pages:
                    raise ValueError('Unknown browser tab')
                page = self.pages[tab_id]
            if action == 'tabs':
                return {'tabs':[{'tab_id':key,'url':value.url,'title':await value.title()} for key,value in self.pages.items()]}
            if action == 'close_tab':
                await page.close(); self.pages.pop(tab_id, None)
                for handle in self.references.pop(tab_id, {}).values():
                    try: await handle.dispose()
                    except Exception: pass
                return {'closed_tab': tab_id}
            if action == 'navigate':
                url = body.get('url')
                if not isinstance(url,str) or not url.startswith(('http://','https://','file:///workspace/','about:blank','data:text/html')):
                    raise ValueError('Unsupported browser URL')
                await page.goto(url, wait_until='domcontentloaded')
            if action in {'click','fill','press'}:
                ref = body.get('ref'); selector = body.get('selector')
                if ref:
                    target = self.references.get(tab_id, {}).get(ref)
                    if target is None: raise ValueError('Reference expired; take a new snapshot')
                elif isinstance(selector, str) and selector:
                    target = page.locator(selector)
                else:
                    raise ValueError('Use a current element ref or an explicit selector')
                if action == 'click': await target.click()
                elif action == 'fill': await target.fill(body.get('text', ''))
                else: await target.press(body.get('key', 'Enter'))
            if action == 'screenshot':
                output = Path('/workspace/outputs'); output.mkdir(parents=True, exist_ok=True)
                if not output.resolve().is_relative_to('/workspace'):
                    raise ValueError('Screenshot output path is outside workspace')
                path = output / ('browser-' + uuid4().hex + '.png')
                data = await page.screenshot(path=str(path), type='png')
                return {'tab_id':tab_id,'path':str(path),'url':page.url,
                        'image_base64':base64.b64encode(data).decode(),'mime_type':'image/png'}
            result = await self.snapshot(tab_id, page)
            await self.save()
            return result


BROWSER = None
GUARD = threading.Lock()


def operate(body):
    global BROWSER
    with GUARD:
        if BROWSER is None: BROWSER = Browser()
    return BROWSER.call(body)


if __name__ == '__main__':
    raw = sys.stdin.buffer.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024: raise ValueError('Browser request too large')
    connection = Connection('pi'); connection.timeout = 45
    connection.request('POST', '/browser', raw, {'Content-Type': 'application/json'})
    response = connection.getresponse(); data = response.read(); connection.close()
    if response.status != 200:
        print(json.dumps({'error':'Browser request failed; inspect page state before retrying an action'})); sys.exit(1)
    print(data.decode())
