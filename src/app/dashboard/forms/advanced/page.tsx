import PageContainer from '@/components/layout/page-container';
import AdvancedFormPatterns from '@/features/forms/components/advanced-form-patterns';

export const metadata = {
  title: '高级表单模式'
};

export default function Page() {
  return (
    <PageContainer
      pageTitle='高级表单模式'
      pageDescription='关联字段、异步验证、动态行、嵌套对象和跨字段验证演示'
    >
      <AdvancedFormPatterns />
    </PageContainer>
  );
}
