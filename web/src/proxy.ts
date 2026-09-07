import { NextRequest, NextResponse } from 'next/server';

export default async function proxy(req: NextRequest) {
  const cookieName = process.env.FINANCIAL_SESSION_COOKIE?.trim() || 'financial_session';
  const path = req.nextUrl.pathname;
  if (!(path === '/dashboard' || path.startsWith('/dashboard/') || path === '/api/platform' || path.startsWith('/api/platform/'))) return NextResponse.next();
  const sessionToken = req.cookies.get(cookieName)?.value;
  if (!sessionToken) {
    if (req.nextUrl.pathname.startsWith('/api/')) {
      return NextResponse.json({ detail: '请先登录。' }, { status: 401 });
    }
    return NextResponse.redirect(new URL('/auth/sign-in', req.url));
  }
  if (req.nextUrl.pathname.startsWith('/api/')) return NextResponse.next();

  const apiBase = process.env.FINANCIAL_PLATFORM_API_URL?.replace(/\/$/, '');
  if (!apiBase) {
    return NextResponse.json({ detail: '财务平台 API 地址尚未配置。' }, { status: 503 });
  }
  let sessionResponse: Response;
  try {
    sessionResponse = await fetch(`${apiBase}/api/auth/session`, {
      headers: { Cookie: `${cookieName}=${sessionToken}` },
      cache: 'no-store'
    });
  } catch {
    return NextResponse.json({ detail: '财务平台暂时不可用。' }, { status: 503 });
  }
  if (sessionResponse.status === 401) {
    return NextResponse.redirect(new URL('/auth/sign-in', req.url));
  }
  if (!sessionResponse.ok) {
    return NextResponse.json({ detail: '财务平台会话校验失败。' }, { status: 503 });
  }
  const session = (await sessionResponse.json()) as { must_change_password?: boolean };
  if (session.must_change_password) {
    return NextResponse.redirect(new URL('/auth/change-password', req.url));
  }
  return NextResponse.next();
}
export const config = {
  matcher: [
    // Skip Next.js internals and all static files, unless found in search params
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    // Always run for API routes
    '/(api|trpc)(.*)'
  ]
};
