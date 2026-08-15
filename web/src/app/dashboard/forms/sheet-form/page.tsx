import PageContainer from '@/components/layout/page-container';
import SheetFormDemo from '@/features/forms/components/sheet-form-demo';

export const metadata = {
  title: '侧边面板与对话框表单'
};

export default function Page() {
  return (
    <PageContainer
      pageTitle='侧边面板与对话框表单'
      pageDescription='演示在侧边面板和对话框中使用表单及外部提交按钮'
    >
      <SheetFormDemo />
    </PageContainer>
  );
}
