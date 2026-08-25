'use client';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { UserAvatarProfile } from '@/components/user-avatar-profile';
import type { PlatformSession } from '@/features/platform-api/types';
import { platformAvatarUser } from '@/features/profile/avatar';
import { useClerk } from '@clerk/nextjs';
import { useRouter } from 'next/navigation';

function ClerkSignOutItem() {
  const { signOut } = useClerk();
  return (
    <DropdownMenuItem onClick={() => signOut({ redirectUrl: '/auth/sign-in' })}>
      退出登录
    </DropdownMenuItem>
  );
}

export function UserNav({ session }: { session: PlatformSession }) {
  const router = useRouter();
  const user = platformAvatarUser(session);
  async function localSignOut() {
    await fetch('/api/auth/logout', { method: 'POST' });
    router.replace('/auth/sign-in');
    router.refresh();
  }
  if (session) {
    return (
      <DropdownMenu>
        <DropdownMenuTrigger
          render={<Button variant='ghost' className='relative h-8 w-8 rounded-full' />}
        >
          <UserAvatarProfile user={user} />
        </DropdownMenuTrigger>
        <DropdownMenuContent className='w-56' align='end' sideOffset={10}>
          <DropdownMenuGroup>
            <DropdownMenuLabel className='font-normal'>
              <div className='flex flex-col space-y-1'>
                <p className='text-sm leading-none font-medium'>{session.display_name}</p>
                <p className='text-muted-foreground text-xs leading-none'>{session.username}</p>
              </div>
            </DropdownMenuLabel>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuItem onClick={() => router.push('/dashboard/profile')}>
              个人资料
            </DropdownMenuItem>
            <DropdownMenuItem>账单管理</DropdownMenuItem>
            <DropdownMenuItem>账号设置</DropdownMenuItem>
            <DropdownMenuItem>新建团队</DropdownMenuItem>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            {session.auth_provider === 'clerk' ? (
              <ClerkSignOutItem />
            ) : (
              <DropdownMenuItem onClick={() => void localSignOut()}>退出登录</DropdownMenuItem>
            )}
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    );
  }
}
