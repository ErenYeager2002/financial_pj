"""Describe this task's failure without confusing input and published material."""
from .ar_execution_contract import CONTRACT_VERSION, next_phase

PHASE_ERROR = 'WORKFLOW_AR_PHASE_FAILED'

def published_version(workflow,context):
    material=getattr(workflow,'material_set',None)
    if material is None or getattr(material,'source_workflow_id',None)!=workflow.id:return ''
    state=context.get('ar_execution') or {}
    if state.get('schema_version')==CONTRACT_VERSION:
        published=(state.get('steps') or {}).get('publish_reconciliation') or {}
        if (state.get('publication')!='verified' or published.get('material_set_id')!=material.id
                or published.get('material_version')!=material.version):return ''
    return str(material.version)

def phase_detail(workflow,context):
    state=context.get('ar_execution') or {}
    if state.get('schema_version')!=CONTRACT_VERSION:return None
    try:phase=next_phase(state.get('completed') or [])
    except (ValueError,TypeError):return None
    if not phase or phase.name!=context.get('current_step'):return None
    if phase.name not in {'verify_reconciliation','rescan_holds','build_final_report','review_final_report','publish_reconciliation','complete_reconciliation'}:return None
    if phase.name=='complete_reconciliation':
        if not published_version(workflow,context):return None
        return dict(reason='本日材料已发布，正式辅助台账登记未完成；保留已发布结果，核查后仅恢复未完成步骤。',write_status='published')
    if state.get('publication')!='not_published':return None
    return dict(reason='本日结果尚未发布，已完成阶段保留；核查失败原因后仅恢复未完成步骤。',write_status='not_published')

def normalize_detail(workflow,context,detail):
    if not detail:return detail
    result={**detail,'published_material_version':published_version(workflow,context)}
    phase=phase_detail(workflow,context)
    if result.get('error_code')=='WORKFLOW_WRITE_STATUS_UNKNOWN' and phase:
        result.update(**phase,error_code=PHASE_ERROR,category='unknown',error_type='ar_phase_failed',recovery_allowed=False)
    return result

def public_message(workflow,detail):
    return f"{workflow.reconciliation_date or '当前日期'} {detail.get('step') or '当前步骤'}未完成：{detail.get('reason') or '请查看处理详情。'}"
