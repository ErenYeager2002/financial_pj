import { buttonVariants } from '@/components/ui/button';
import type { PlatformSession } from '@/features/platform-api/types';
import Link from 'next/link';
import { AvatarUpload } from './avatar-upload';

export default function ProfileViewPage({ session }: { session: PlatformSession }) {
  return (
    <div className='flex w-full flex-col gap-4 p-4'>
      <div className='max-w-xl rounded-xl border bg-card p-6 shadow-sm'>
        <AvatarUpload session={session} />
        <dl className='mt-4 grid grid-cols-[7rem_1fr] gap-2 text-sm'>
          <dt className='text-muted-foreground'>用户名</dt>
          <dd>{session.username}</dd>
          <dt className='text-muted-foreground'>部门</dt>
          <dd>{session.department_id}</dd>
          <dt className='text-muted-foreground'>角色</dt>
          <dd>{session.role === 'skill_admin' ? 'Skill 管理员' : '财务员工'}</dd>
        </dl>
        <Link
          className={`${buttonVariants({ variant: 'outline' })} mt-6`}
          href='/auth/change-password'
        >
          修改密码
        </Link>
      </div>
    </div>
  );
}
