import type { PlatformSession } from '@/features/platform-api/types';

export function platformAvatarUrl(session: PlatformSession): string | undefined {
  return session.avatar_updated_at
    ? `/api/platform/profile/avatar?v=${encodeURIComponent(session.avatar_updated_at)}`
    : undefined;
}

export function platformAvatarUser(session: PlatformSession) {
  return {
    imageUrl: platformAvatarUrl(session),
    fullName: session.display_name,
    emailAddresses: [{ emailAddress: session.username }]
  };
}
