import PageContainer from '@/components/layout/page-container';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { listAllFiles } from '@/features/files/api/server';
import { FileList } from '@/features/files/components/file-list';

export const metadata = {
  title: '文件中心'
};

type PageProps = {
  searchParams: Promise<{ kind?: string; query?: string }>;
};

export default async function Page({ searchParams }: PageProps) {
  const params = await searchParams;
  const kind = ['input', 'output'].includes(params.kind ?? '') ? (params.kind ?? '') : '';
  const query = (params.query ?? '').slice(0, 100);
  const files = await listAllFiles(kind, query);

  return (
    <PageContainer pageTitle='文件中心' pageDescription='旧结果仍保留在任务审计记录中'>
      <form className='mb-4 flex flex-wrap items-end gap-2' method='get'>
        <label htmlFor='file-query' className='grid min-w-64 gap-1 text-sm'>
          <span className='text-muted-foreground'>文件名</span>
          <Input id='file-query' name='query' defaultValue={query} placeholder='搜索文件名' />
        </label>
        <label className='grid gap-1 text-sm'>
          <span className='text-muted-foreground'>文件类型</span>
          <select
            name='kind'
            defaultValue={kind}
            className='h-9 rounded-md border bg-background px-3'
          >
            <option value=''>全部文件</option>
            <option value='input'>上传文件</option>
            <option value='output'>结果文件</option>
          </select>
        </label>
        <Button type='submit' variant='outline'>
          查询
        </Button>
      </form>
      <FileList files={files} />
    </PageContainer>
  );
}
