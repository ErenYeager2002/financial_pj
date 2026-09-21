/** Shared labels for backend-confirmed business write and publication states. */
export function writeStatusLabel(value: unknown): string {
  if (value === 'not_applicable') return '不涉及业务写入';
  if (value === 'not_started') return '尚未开始写入';
  if (value === 'not_published') return '结果尚未发布';
  if (value === 'verification_pending') return '写入后校验未完成，发布状态待核实';
  if (value === 'published') return '已有发布记录';
  return '待核实';
}

export function publishedMaterialLabel(version: unknown, writeStatus: unknown): string {
  if (writeStatus === 'not_applicable') return '不涉及材料发布';
  if (writeStatus === 'not_started' || writeStatus === 'not_published') return '本次任务尚未发布';
  if (typeof version === 'number' && Number.isFinite(version) && version > 0) return String(version);
  if (typeof version === 'string' && version.trim()) return version.trim();
  return '待核实';
}
