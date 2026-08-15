import PageContainer from '@/components/layout/page-container';
import DemoForm from '@/components/forms/demo-form';

export const metadata = {
  title: '基础表单'
};

export default function Page() {
  return (
    <PageContainer pageTitle='基础表单' pageDescription='常用表单字段和验证方式的完整演示'>
      <DemoForm />
    </PageContainer>
  );
}
