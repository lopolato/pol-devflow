# Resultado del agente
schema_version: 1
run_id / task_id / worker_id / role:
status: done | partial | blocked | cancelled
summary:
observed_revision / result_revision / workspace_dirty:
criteria_results: [{criterion, status: passed|failed|not_run, revision, evidence}]
findings (nuevos, sin resolver):
files_inspected / files_changed (confirmados y pendientes) / commits:
decisions / validation: [{name, procedure, status: passed|failed|not_run|not_applicable, revision, evidence}]
review (solo reviewer): {verdict: passed|changes_required|incomplete}
risks / out_of_scope / questions / next_action (listas vacías y next_action omitibles):
usage (opcional, solo del runtime): model, tokens, duration_ms, tool_uses, source
