import PageContainer from '@/components/layout/page-container';
import FormsShowcasePage from '@/features/forms/components/forms-showcase-page';

export const metadata = {
  title: '分步表单'
};

export default function Page() {
  return (
    <PageContainer pageTitle='分步表单' pageDescription='分步骤填写和提交表单的示例'>
      <FormsShowcasePage />
    </PageContainer>
  );
}
