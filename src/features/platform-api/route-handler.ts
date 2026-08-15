import { NextResponse } from 'next/server';
import { PlatformApiError } from './errors';

export function platformRouteError(error: unknown, fallback: string) {
  if (error instanceof PlatformApiError) {
    return NextResponse.json({ detail: error.message }, { status: error.status });
  }
  return NextResponse.json({ detail: fallback }, { status: 502 });
}
