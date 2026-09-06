import Providers from '@/components/layout/providers';
import { Toaster } from '@/components/ui/sonner';
import { fontVariables } from '@/components/themes/font.config';
import { DEFAULT_THEME, THEMES } from '@/components/themes/theme.config';
import ThemeProvider from '@/components/themes/theme-provider';
import { cn } from '@/lib/utils';
import type { Metadata, Viewport } from 'next';
import { cookies } from 'next/headers';
import NextTopLoader from 'nextjs-toploader';
import { NuqsAdapter } from 'nuqs/adapters/next/app';
import '../styles/globals.css';
import { authMode } from '@/features/auth/auth-mode';

const META_THEME_COLORS = {
  light: '#ffffff',
  dark: '#09090b'
};

export const metadata: Metadata = {
  ...(process.env.NEXT_PUBLIC_APP_URL
    ? { metadataBase: new URL(process.env.NEXT_PUBLIC_APP_URL) }
    : {}),
  title: {
    default: '企业管理后台',
    template: '%s | 企业管理后台'
  },
  description: '基于 Next.js、shadcn/ui 和 TypeScript 构建的企业管理后台。',
  openGraph: {
    title: '企业管理后台',
    description: '基于 Next.js、shadcn/ui 和 TypeScript 构建的企业管理后台。',
    siteName: '企业管理后台',
    type: 'website',
    images: [
      {
        url: '/shadcn-dashboard.png',
        width: 3200,
        height: 1600,
        alt: '企业管理后台概览页'
      }
    ]
  },
  twitter: {
    card: 'summary_large_image',
    title: '企业管理后台',
    description: '基于 Next.js、shadcn/ui 和 TypeScript 构建的企业管理后台。',
    images: ['/shadcn-dashboard.png']
  }
};

export const viewport: Viewport = {
  themeColor: META_THEME_COLORS.light
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies();
  const activeThemeValue = cookieStore.get('active_theme')?.value;
  const isValidTheme = THEMES.some((t) => t.value === activeThemeValue);
  const themeToApply = isValidTheme ? activeThemeValue! : DEFAULT_THEME;

  return (
    <html
      lang='zh-CN'
      translate='no'
      className='notranslate'
      suppressHydrationWarning
      data-theme={themeToApply}
    >
      <head>
        <meta name='google' content='notranslate' />
      </head>
      <body
        className={cn(
          'bg-background overflow-x-hidden overscroll-none font-sans antialiased',
          fontVariables
        )}
      >
        <NextTopLoader color='var(--primary)' showSpinner={false} />
        <NuqsAdapter>
          <ThemeProvider
            themeColors={META_THEME_COLORS}
            attribute='class'
            defaultTheme='system'
            enableSystem
            disableTransitionOnChange
            enableColorScheme
          >
            <Providers activeThemeValue={themeToApply} authMode={authMode()}>
              <Toaster />
              {children}
            </Providers>
          </ThemeProvider>
        </NuqsAdapter>
      </body>
    </html>
  );
}
