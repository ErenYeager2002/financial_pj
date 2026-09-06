'use client';

import { ThemeProvider as NextThemesProvider, useTheme } from 'next-themes';
import { useEffect } from 'react';
import type { ThemeProviderProps } from 'next-themes';

type ThemeColors = {
  light: string;
  dark: string;
};

function ThemeColorSync({ themeColors }: { themeColors: ThemeColors }) {
  const { resolvedTheme } = useTheme();

  useEffect(() => {
    const color = resolvedTheme === 'dark' ? themeColors.dark : themeColors.light;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', color);
  }, [resolvedTheme, themeColors]);

  return null;
}

export default function ThemeProvider({
  children,
  themeColors,
  ...props
}: ThemeProviderProps & { themeColors: ThemeColors }) {
  return (
    <NextThemesProvider {...props}>
      <ThemeColorSync themeColors={themeColors} />
      {children}
    </NextThemesProvider>
  );
}
