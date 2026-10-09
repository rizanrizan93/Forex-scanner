"""Free-tier visibility; critical execution is never throttled by estimates."""
from datetime import datetime, timezone

LIMITS = {'rows_read':500_000_000, 'rows_written':10_000_000, 'storage_bytes':5_000_000_000, 'sync_bytes':3_000_000_000}
WORKER = 'turso_free_tier_budget_v1'

def report_budget(client):
    now=datetime.now(timezone.utc)
    month=now.strftime('%Y-%m')
    usage=client.execute('SELECT coalesce(sum(requests),0) requests, coalesce(sum(statements),0) statements, coalesce(sum(rows_read),0) rows_read, coalesce(sum(rows_written),0) rows_written, coalesce(sum(unmetered_statements),0) unmetered_statements FROM turso_usage_daily WHERE day >= ?',[month+'-01']).data[0]
    pages=client.execute('PRAGMA page_count').data[0]['page_count']
    size=client.execute('PRAGMA page_size').data[0]['page_size']
    details={'month_utc':month,'limits':LIMITS,'observed_usage':usage,'database_allocated_bytes':pages*size,'scope':'INSTRUMENTED_SCANNER_PROCESSES_ONLY','provider_dashboard_authoritative':True,'tracking_overhead_not_included':True,'sync_mode':'DIRECT_HTTP_NO_EMBEDDED_REPLICA'}
    details['read_percent']=round(100*usage['rows_read']/LIMITS['rows_read'],3)
    details['write_percent']=round(100*usage['rows_written']/LIMITS['rows_written'],3)
    details['storage_percent']=round(100*pages*size/LIMITS['storage_bytes'],3)
    details['metering_complete']=usage['unmetered_statements']==0
    details['status']='REVIEW_80_PERCENT' if max(details['read_percent'],details['write_percent'],details['storage_percent'])>=80 else 'WITHIN_OBSERVED_BUDGET'
    client.table('runtime_heartbeats').upsert({'worker_name':WORKER,'observed_at':now.isoformat(),'healthy':True,'lag_seconds':0.,'details':details},on_conflict='worker_name',returning='minimal').execute()
    return details
