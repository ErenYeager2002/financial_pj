export function draftCompletionMessage(current: string, skillName: string): string {
  return current || `任务草稿已生成：${skillName}。请在右侧核对后打开任务。`;
}
