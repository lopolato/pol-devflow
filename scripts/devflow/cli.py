"""Public support commands and explicit internal Coordinator operations."""
import argparse
import copy
import json
import sys
from pathlib import Path
import uuid
from . import adapters, cleanup, config, gitops, lite, metrics, orca, package, profile, state
from .storage import DevFlowError, FileLock, atomic_write, data_home, digest, json_bytes, now, package_root, read_json, safe_id

HELP = {
    'general': 'pol-devflow: error | feature [--lite|--full] [--review] [--plan-only] <description>; optimize [--plan-only] <description>\n'
               'help [topic] | status [--run ID] | stats [--all] [--since DAYS] | config [show|validate|set] | cleanup [--apply] [--discard BRANCH] [--purge-history]\n'
               'The skill Coordinator executes workflows through native session tools.\n'
               'The Python CLI provides deterministic support; it is not a standalone LLM agent.',
    'error': 'error [--lite|--full] [--review] [--plan-only] <description>: diagnose, fix and verify the reported defect.',
    'feature': 'feature [--lite|--full] [--review] [--plan-only] <description>: implement agreed behavior and verify acceptance criteria.',
    'lite': 'error|feature --lite <description>: small clear task on a new branch in the current checkout, '
            'delegated to the pol-lite worker; escalates to full mode when it stops being small. '
            '--lite --review adds one independent review bound to the committed diff '
            '(_lite review-diff, _lite review, _lite status).',
    'cleanup': 'cleanup [--into REF] [--remote REMOTE] [--apply] [--orca-idle-confirmed] [--discard BRANCH] [--purge-history]: list DevFlow branches, worktrees and closed runs; '
               '--apply removes only merged and clean items after user confirmation; --discard deletes one '
               'unmerged DevFlow branch the user explicitly confirmed. --remote opts into remote deletion; '
               '--orca-idle-confirmed records verified runtime inactivity. History is retained by default; '
               '--purge-history explicitly removes eligible closed-run history after separate confirmation.',
    'optimize': 'optimize [--plan-only] <description>: baseline, change, comparable measurement and functional checks.',
    'status': 'status [--run ID]: read recorded state and contrast Git revision; never resume a worker.',
    'config': 'config [show|validate]\nconfig set --runtime codex|claude --role ROLE '
              '[--model MODEL] [--effort LEVEL] | --inherit\n'
              'Atomic shared config update; generated-file conflicts cause no config write. '
              'Coordinator model belongs to the main session. Changes affect future runs only.',
    'stats': 'stats [--all] [--since DAYS]: recorded tokens/time/models per role and task type for this repository '
             '(or all with --all). Read-only; values that were not recorded are reported as unknown, never estimated.',
    'profile': '_profile show | _profile set --input FILE [--repo-file]: verified project commands (setup, test, '
               'test_affected, lint, typecheck, build, run) reused across runs. Stored outside the repository unless '
               '--repo-file; reports stale when dependency/tooling files change.',
    'help': 'help [error|feature|optimize|lite|status|stats|config|cleanup|profile|orca|help]: no repository reads or writes.',
    'orca': 'Orca backend: Coordinator reads adapters/orca/README.md and the version-matched runtime guide. '
            '_run start --executor orca keeps the clean current checkout; _orca spec/link/settle/account '
            'bridge development evidence. Read-only waves only; writers remain sequential. '
            'Context7 is queried when needed; Engram is not required.',
}


def parser():
    result = argparse.ArgumentParser(prog='pol-devflow', description=HELP['general'], allow_abbrev=False)
    commands = result.add_subparsers(dest='command', required=True)
    help_parser = commands.add_parser('help')
    help_parser.add_argument('topic', nargs='?', default='general', choices=tuple(HELP))
    for mode in state.MODES:
        p = commands.add_parser(mode)
        p.add_argument('--plan-only', action='store_true')
        if mode != 'optimize':
            level = p.add_mutually_exclusive_group()
            level.add_argument('--lite', action='store_true')
            level.add_argument('--full', action='store_true')
        p.add_argument('--review', action='store_true')
        p.add_argument('description', nargs='+')
    p = commands.add_parser('_workspace')
    p.add_argument('action', choices=('register',))
    p.add_argument('--input', required=True)
    p = commands.add_parser('cleanup')
    p.add_argument('--apply', action='store_true')
    p.add_argument('--discard', action='append', default=[])
    p.add_argument('--into')
    p.add_argument('--purge-history', action='store_true')
    p.add_argument('--remote')
    p.add_argument('--orca-idle-confirmed', action='store_true')
    p = commands.add_parser('_lite')
    p.add_argument('action', choices=('start', 'link', 'settle', 'account', 'review-diff', 'review', 'status'))
    p.add_argument('--mode', choices=('error', 'feature'))
    p.add_argument('--request')
    p.add_argument('--executor', choices=('native', 'orca'), default='native')
    p.add_argument('--owner')
    p.add_argument('--lite')
    p.add_argument('--input')
    p.add_argument('--base')
    p.add_argument('--review', action='store_true')
    p.add_argument('--author-id')
    p = commands.add_parser('status')
    p.add_argument('--run')
    p = commands.add_parser('stats')
    p.add_argument('--all', action='store_true')
    p.add_argument('--since', type=int)
    p = commands.add_parser('_profile')
    p.add_argument('action', choices=('show', 'set'))
    p.add_argument('--input')
    p.add_argument('--repo-file', action='store_true')
    p = commands.add_parser('_metrics')
    p.add_argument('action', choices=('add',))
    p.add_argument('--run')
    p.add_argument('--lite')
    p.add_argument('--owner')
    p.add_argument('--role', required=True, choices=config.ROLES)
    p.add_argument('--model')
    p.add_argument('--tokens', type=int)
    p.add_argument('--duration-ms', type=int)
    p.add_argument('--tool-uses', type=int)
    p.add_argument('--source', choices=metrics.SOURCES)
    p.add_argument('--task-id')
    p.add_argument('--worker-id')
    p.add_argument('--phase')
    p = commands.add_parser('config')
    p.add_argument('action', nargs='?', default='show', choices=('show', 'validate', 'set'))
    p.add_argument('--runtime', choices=config.RUNTIMES)
    p.add_argument('--role', choices=config.ROLES)
    p.add_argument('--model')
    p.add_argument('--effort', choices=config.EFFORTS)
    p.add_argument('--inherit', action='store_true')
    p = commands.add_parser('_validate')
    p.add_argument('--runtime', choices=config.RUNTIMES)
    p = commands.add_parser('_capabilities')
    p.add_argument('--runtime', required=True, choices=config.RUNTIMES)
    p = commands.add_parser('_generate')
    p.add_argument('--runtime', required=True, choices=config.RUNTIMES)
    p.add_argument('--destination', required=True)
    for command in ('_install', '_uninstall'):
        p = commands.add_parser(command)
        p.add_argument('--runtime', required=True, choices=(*config.RUNTIMES, 'all'))
        p.add_argument('--codex-home', default=str(Path.home() / '.codex'))
        p.add_argument('--claude-home', default=str(Path.home() / '.claude'))
    p = commands.add_parser('_run')
    p.add_argument('--executor', choices=('native', 'orca'), default='native')
    p.add_argument('action', choices=('start', 'show', 'refresh', 'checkpoint', 'task', 'record', 'update', 'resolve',
                                      'attempt', 'close', 'claim', 'template', 'validate-result', 'check-close'))
    p.add_argument('--run')
    p.add_argument('--owner')
    p.add_argument('--mode', choices=state.MODES)
    p.add_argument('--runtime', choices=config.RUNTIMES)
    p.add_argument('--request')
    p.add_argument('--criterion', action='append', default=[])
    p.add_argument('--base')
    p.add_argument('--reuse-branch')
    p.add_argument('--role', choices=config.TASK_ROLES)
    p.add_argument('--objective')
    p.add_argument('--write-scope', action='append', default=[])
    p.add_argument('--read-scope', action='append', default=[])
    p.add_argument('--depends', action='append', default=[])
    p.add_argument('--task-id')
    p.add_argument('--replaces')
    p.add_argument('--correction-key')
    p.add_argument('--input')
    p.add_argument('--status', choices=state.FINAL_STATES)
    p.add_argument('--failure')
    p.add_argument('--evidence')
    p.add_argument('--workers-confirmed-stopped', action='store_true')
    p.add_argument('--path', action='append', default=[])
    p.add_argument('--message')
    p.add_argument('--budget-minutes', type=int)
    p.add_argument('--context-from', action='append', default=[])
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--author-name')
    p.add_argument('--author-email')
    p = commands.add_parser('_orca')
    p.add_argument('action', choices=('spec', 'link', 'settle', 'account'))
    p.add_argument('--run', required=True)
    p.add_argument('--owner', required=True)
    p.add_argument('--task-id', required=True)
    p.add_argument('--runtime', choices=config.RUNTIMES)
    p.add_argument('--input')
    p = commands.add_parser('_git')
    p.add_argument('action', choices=('inspect', 'identity', 'commit', 'child', 'integrate', 'remove-child'))
    p.add_argument('--workspace', required=True)
    p.add_argument('--path', action='append', default=[])
    p.add_argument('--message')
    p.add_argument('--expected-branch')
    p.add_argument('--child-branch')
    p.add_argument('--child-workspace')
    p.add_argument('--name')
    p.add_argument('--workers-confirmed-stopped', action='store_true')
    p.add_argument('--author-name')
    p.add_argument('--author-email')
    return result


def require(*values):
    if any(v is None or v == '' for v in values):
        raise DevFlowError('Required arguments are missing; consult command --help')


def close_blockers(run):
    """Read-only completion gate shared by close and check-close."""
    live = gitops.inspect(run['workspace'])
    blockers = []
    if live['branch'] != run['branch'] or live['revision'] != run['current_revision']:
        blockers.append('Candidate changed since last handoff; refresh and revalidate')
    return blockers + state.completion_blockers(run | {'workspace_dirty': live['dirty']})


def run_command(args, ctx):
    data, root, repo = Path(ctx.data_dir), Path(ctx.root), Path(ctx.repo)
    if args.dry_run and args.action != 'record':
        raise DevFlowError('--dry-run only applies to record')
    if args.budget_minutes is not None and args.action != 'task':
        raise DevFlowError('--budget-minutes only applies to task')
    if getattr(args, 'context_from', None) and args.action != 'task':
        raise DevFlowError('--context-from only applies to task')
    if args.action == 'start':
        require(args.mode, args.request, args.owner, args.runtime)
        if not args.criterion:
            raise DevFlowError('Supply acceptance --criterion before starting implementation')
        selected = config.load(config.active_path(data, root))
        if args.executor == 'orca':
            if not (data / 'config/models.yaml').exists():
                selected = config.defaults()
            selected = orca.snapshot_settings(data, selected)
        preflight = gitops.inspect(repo)
        # State/worktrees must not be mixed into the user's versioned checkout.
        if data.resolve().is_relative_to(Path(preflight['workspace']).resolve()):
            raise DevFlowError('--data-dir must be outside the source repository')
        if args.reuse_branch and preflight['dirty']:
            raise DevFlowError('Reusing a dirty branch requires resolving ownership of preexisting changes first')
        if args.executor == 'orca' and not args.reuse_branch:
            info = gitops.task_branch(repo, args.mode, args.request, args.base)
        else:
            info = gitops.prepare(repo, args.mode, args.request, data / 'worktrees', args.base, args.reuse_branch)
        run = state.create(data, preflight['workspace'], args.mode, args.request, selected,
                            branch=info['branch'], revision=info['base_revision'], criteria=args.criterion,
                            workspace=info['workspace'], runtime=args.runtime, owner=args.owner,
                            capabilities=adapters.capabilities(args.runtime))
        run['executor'] = args.executor
        if args.executor == 'orca':
            run['capabilities'].update(executor='orca', parallel_dispatch=True, parallel_writes=False,
                                       runtime_authority='Orca active Dispatch')
        state.save(data, run, 'execution backend selected')
        return run | {'identity': gitops.identity(run['workspace'])}
    require(args.run)
    if args.action == 'show':
        return state.status(data, run_id=args.run)
    if args.action == 'validate-result':
        # Worker preflight: schema/assignment only, before Orca settlement. No locks or writes.
        require(args.input)
        run = state.load(data, args.run)
        result = read_json(args.input)
        task = next((t for t in run['tasks'] if t['task_id'] == result.get('task_id')), None) if isinstance(result, dict) else None
        if not task:
            raise DevFlowError('Result task_id must match a recorded assignment')
        state.validate_result(task, result)
        if task['role'] == 'reviewer' and (not isinstance(result.get('review'), dict)
                or result['review'].get('verdict') not in ('passed', 'changes_required', 'incomplete')):
            raise DevFlowError('review.verdict must be passed, changes_required or incomplete')
        if result.get('usage') is not None:
            metrics.entry({**result['usage'], 'role': task['role'], 'task_id': task['task_id'],
                           'worker_id': result['worker_id']})
        return {'valid': True, 'scope': 'schema_and_assignment', 'state_changed': False,
                'task_id': task['task_id'], 'note': 'Not accepted or recorded. Coordinator record --dry-run '
                'still checks settlement, identity, live Git, reviewer artifact and duplicate findings.'}
    require(args.owner)
    if args.action in ('template', 'check-close'):
        # Read-only helpers: no lock, no state write.
        run = state.load(data, args.run)
        state.require_owner(run, args.owner)
        if args.action == 'check-close':
            blockers = close_blockers(run)
            return {'can_complete': not blockers, 'blockers': blockers}
        require(args.task_id)
        task = next((t for t in run['tasks'] if t['task_id'] == args.task_id), None)
        if not task:
            raise DevFlowError('No matching assignment for --task-id')
        template = state.empty_result(task, task.get('orca', {}).get('worker_id', ''))
        if task['role'] == 'reviewer':
            template['review'] = {'verdict': ''}
        template['usage'] = {'model': None, 'tokens': None, 'duration_ms': None}
        return template
    with state.RunLock(data, args.run, args.owner):
        run = state.load(data, args.run)
        if args.action == 'claim':
            if not args.workers_confirmed_stopped:
                raise DevFlowError('Verify live workers are stopped before claiming a run')
            live = gitops.inspect(run['workspace'])
            if live['branch'] != run['branch']:
                raise DevFlowError('Run branch changed; reconcile before claiming')
            run['coordinator_id'] = args.owner
            if args.owner not in run['authors']:
                run['authors'].append(args.owner)
            for worker in run['workers']:
                if worker.get('status') not in ('done', 'cancelled_confirmed'):
                    worker['previous_status'] = worker.get('status')
                    worker['status'] = 'cancelled_confirmed'
                    worker['cancellation_evidence'] = 'Explicit Coordinator confirmation after live worker verification'
            run['current_revision'] = live['revision']
            run['workspace_dirty'] = live['dirty']
            run['status'] = 'active'
            state.save(data, run, 'coordinator claimed after worker verification')
            return run
        state.require_owner(run, args.owner)
        if run['status'] != 'active' and args.action != 'close':
            raise DevFlowError('Run is closed; inspect and claim before resuming')
        if args.action == 'checkpoint':
            require(args.message)
            revision = gitops.commit(run['workspace'], args.path, args.message, run['branch'],
                                     args.author_name, args.author_email)
            live = gitops.inspect(run['workspace'])
            run['current_revision'], run['workspace_dirty'] = live['revision'], live['dirty']
            state.save(data, run, 'checkpoint')
            return {'revision': revision, 'workspace_dirty': live['dirty'], 'branch': run['branch']}
        if args.action == 'refresh':
            live = gitops.inspect(run['workspace'])
            if live['branch'] != run['branch']:
                raise DevFlowError('Workspace branch differs from run')
            run['current_revision'], run['workspace_dirty'] = live['revision'], live['dirty']
        elif args.action == 'task':
            require(args.role, args.objective)
            live = gitops.inspect(run['workspace'])
            if live['branch'] != run['branch'] or live['revision'] != run['current_revision']:
                raise DevFlowError('Refresh/reconcile the candidate before assignment')
            if live['dirty']:
                raise DevFlowError('Assignments require a clean checkpoint; preserve and reconcile pending changes first')
            orca.check_assignment(run, args.role, args.write_scope)
            known = {t['task_id']: t for t in run['tasks']}
            if any(d not in known or known[d]['status'] != 'done' for d in args.depends):
                raise DevFlowError('Task dependencies are not finished')
            if args.task_id and args.task_id in known:
                raise DevFlowError('Task identity already exists')
            if args.replaces and (args.replaces not in known or known[args.replaces]['status'] == 'done'):
                raise DevFlowError('Replacement must reference an unfinished recorded assignment')
            if args.replaces and args.correction_key and args.correction_key != known[args.replaces].get('correction_key'):
                raise DevFlowError('Replacement cannot change its inherited correction key')
            sources = list(dict.fromkeys(args.context_from))
            for source in sources:
                if source not in known or known[source].get('result') is None:
                    raise DevFlowError(f'--context-from needs a task with a recorded result: {source}')
            task = state.make_task(run, args.role, args.objective, args.write_scope,
                                   args.read_scope, args.depends, args.task_id,
                                   args.correction_key or (known[args.replaces].get('correction_key') if args.replaces else None),
                                   args.budget_minutes)
            if args.input:
                context = read_json(args.input)
                if (not isinstance(context, dict)
                        or set(context) - {'shared_contracts', 'relevant_context', 'constraints'}
                        or any(not isinstance(v, list) for v in context.values())):
                    raise DevFlowError('Task context accepts only shared_contracts/relevant_context/constraints lists')
                for name, items in context.items():
                    task[name].extend(items)
            for source in sources:
                # Hand over the earlier worker's map so the next worker does not rediscover the code.
                result = known[source]['result']
                task['relevant_context'].append({'from_task': source, 'role': known[source]['role'],
                                                 'summary': result.get('summary', ''),
                                                 'code_map': result.get('code_map') or []})
            safe_id(task['task_id'])
            if args.role == 'reviewer':
                diff = gitops.git(run['workspace'], 'diff', '--no-ext-diff', '--no-textconv',
                                  '--binary', '--full-index', run['base_revision'], run['current_revision'], '--')
                content = (diff + '\n').encode('utf-8')
                path = state.run_dir(data, args.run) / 'review-inputs' / (task['task_id'] + '.diff')
                atomic_write(path, content)
                task['review_diff'] = {'path': str(path.resolve()), 'sha256': digest(content),
                                       'base_revision': run['base_revision'], 'revision': run['current_revision']}
            if args.replaces:
                task['replaces'] = args.replaces
                task['relevant_context'].append({'previous_assignment': args.replaces,
                                                'result': known[args.replaces]['result']})
            run['tasks'].append(task)
            state.save(data, run, 'task assigned')
            return task
        elif args.action == 'record':
            require(args.input)
            result = read_json(args.input)
            task = next((t for t in run['tasks'] if t['task_id'] == result.get('task_id')), None)
            if not task:
                raise DevFlowError('Result has no matching assignment')
            if args.role and args.role != task['role']:
                raise DevFlowError('Record role differs from the assigned role')
            if task.get('result') is not None:
                raise DevFlowError('Result already recorded; do not replay an assignment')
            # Every validation runs before any mutation, so --dry-run and a real record accept the same results.
            state.validate_result(task, result)
            usage = None
            if result.get('usage') is not None:
                # Optional usage saves a separate _metrics call; it never affects acceptance.
                usage = metrics.entry({**result['usage'], 'role': task['role'], 'task_id': task['task_id'],
                                       'worker_id': result['worker_id']})
            if run.get('executor') == 'orca':
                orca.validate_result(task, result)
            live = gitops.inspect(task['workspace'])
            if live['branch'] != task['branch']:
                raise DevFlowError('Result workspace no longer has the assigned branch')
            candidate = result['result_revision'] or result['observed_revision']
            if live['revision'] != candidate or live['dirty'] != result['workspace_dirty']:
                raise DevFlowError('Result revision/dirty flag does not match actual workspace')
            if candidate != task['candidate_revision']:
                gitops.git(task['workspace'], 'merge-base', '--is-ancestor', task['candidate_revision'], candidate)
            actual = gitops.changed_paths(task['workspace'], task['candidate_revision'])
            if actual != set(result['files_changed']):
                raise DevFlowError('Result changed-file list does not match actual committed/uncommitted changes')
            review = result.get('review')
            if task['role'] == 'reviewer':
                artifact = task.get('review_diff')
                if not artifact or digest(Path(artifact['path']).read_bytes()) != artifact['sha256']:
                    raise DevFlowError('Reviewer diff artifact missing/modified; reassign review')
                if not isinstance(review, dict) or review.get('verdict') not in ('passed', 'changes_required', 'incomplete'):
                    raise DevFlowError('Reviewer result must include review.verdict (passed, changes_required or incomplete)')
            state.append_findings({'findings': copy.deepcopy(run['findings'])}, result['findings'])
            if args.dry_run:
                return {'valid': True, 'dry_run': True, 'task_id': task['task_id'], 'role': task['role'],
                        'status': result['status'], 'candidate_revision': candidate,
                        'workspace_dirty': live['dirty'], 'files_changed': sorted(actual),
                        'review_verdict': review.get('verdict') if task['role'] == 'reviewer' else None,
                        'usage_recorded': usage is not None, 'state_changed': False}
            task['status'], task['result'] = result['status'], result
            task['result_recorded_at'] = now()
            if result['status'] == 'done' and task.get('replaces'):
                previous = next(t for t in run['tasks'] if t['task_id'] == task['replaces'])
                previous['status'] = 'done'
                previous['superseded_by'] = task['task_id']
            run['current_revision'], run['workspace_dirty'] = candidate, live['dirty']
            if usage:
                run.setdefault('metrics', []).append(usage)
            run['validations'].extend(result['validation'])
            run['criteria_results'].extend(result['criteria_results'])
            state.append_findings(run, result['findings'])
            if result['files_changed'] and result['worker_id'] not in run['authors']:
                run['authors'].append(result['worker_id'])
            if task['role'] == 'reviewer':
                run['review'] = {'verdict': review['verdict'], 'revision': candidate, 'worker_id': result['worker_id']}
            atomic_write(state.run_dir(data, args.run) / 'results' / (safe_id(result['task_id']) + '.json'), json_bytes(result))
        elif args.action == 'update':
            require(args.input)
            update = read_json(args.input)
            allowed = {'phase', 'criteria_results', 'validations', 'required_checks', 'review_required',
                       'findings', 'measurement', 'decisions', 'questions', 'next_action', 'workers', 'incident'}
            if not isinstance(update, dict) or set(update) - allowed:
                raise DevFlowError('Update contains unsupported fields; snapshots/identity/review cannot be overridden')
            if run.get('executor') == 'orca' and update.get('workers'):
                raise DevFlowError('Orca owns worker activity; use Dispatch evidence instead of native worker records')
            if 'incident' in update:
                state.validate_incident(update['incident'])
            for check in update.get('validations', []):
                state.validate_check(check)
            for criterion in update.get('criteria_results', []):
                state.validate_criterion(criterion)
                if criterion['criterion'] not in run['acceptance_criteria']:
                    raise DevFlowError('Unknown acceptance criterion in update')
            if 'review_required' in update and not isinstance(update['review_required'], bool):
                raise DevFlowError('review_required must be boolean')
            if run['review_required'] and update.get('review_required') is False:
                raise DevFlowError('Cannot remove an established independent review requirement')
            for key in ('criteria_results', 'validations', 'required_checks', 'findings', 'decisions', 'questions', 'workers'):
                if key in update and not isinstance(update[key], list):
                    raise DevFlowError(f'{key} must be a list')
            for key in ('validations', 'criteria_results'):
                if key in update and update[key][:len(run[key])] != run[key]:
                    raise DevFlowError(f'Cannot remove/modify {key} history; append new evidence')
            if 'required_checks' in update:
                checks = update['required_checks']
                if (not all(isinstance(c, str) and c.strip() for c in checks)
                        or len(set(checks)) != len(checks) or not set(run['required_checks']).issubset(checks)):
                    raise DevFlowError('Cannot remove required checks; names must be nonempty and unique')
            if 'findings' in update:
                findings = update.pop('findings')
                previous = run['findings']
                if findings[:len(previous)] != previous:
                    raise DevFlowError('Cannot remove/modify findings; use resolve with current validation evidence')
                state.append_findings(run, findings[len(previous):])
            if 'incident' in update:
                state.record_incident(run, update.pop('incident'))
            run.update(update)
        elif args.action == 'resolve':
            require(args.input)
            live = gitops.inspect(run['workspace'])
            if live['dirty'] or live['branch'] != run['branch'] or live['revision'] != run['current_revision']:
                raise DevFlowError('Resolution requires the clean current Git candidate')
            state.resolve_finding(run, read_json(args.input))
        elif args.action == 'attempt':
            require(args.task_id, args.failure, args.evidence)
            state.record_attempt(run, args.task_id, args.failure, args.evidence)
        elif args.action == 'close':
            require(args.status)
            if args.status == 'completed':
                blockers = close_blockers(run)
                if blockers:
                    raise DevFlowError('Cannot complete: ' + '; '.join(blockers))
                run['workspace_dirty'] = False
            run['status'] = args.status
            if args.status == 'cancelled':
                run['next_action'] = 'Confirm native worker cancellation; preserve all changes and worktrees'
        state.save(data, run, args.action)
        return run


def dispatch(args, ctx):
    data, root = Path(ctx.data_dir), Path(ctx.root)
    if args.command == 'help':
        return HELP[args.topic]
    if args.command in state.MODES:
        level = 'lite' if getattr(args, 'lite', False) else 'full' if getattr(args, 'full', False) else 'auto'
        if args.command == 'optimize':
            if args.review:
                raise DevFlowError('--review applies to error and feature only; optimize always runs the full workflow')
            level = 'full'
        if level == 'lite' and args.review:
            level = 'lite+review'
        return {'mode': args.command, 'request': ' '.join(args.description), 'plan_only': args.plan_only,
                'level': level, 'review_requested': args.review,
                'workflow': str(root / 'core/workflows' / ((args.command if level == 'full' else 'lite') + '.md')),
                'next_action': 'Coordinator reads workflow, inspects project and resolves material ambiguity; '
                               'plan-only must stop before any state/Git write',
                'implementation_started': False}
    if args.command == 'status':
        return state.status(data, run_id=args.run, repository=ctx.repo)
    if args.command == 'stats':
        return metrics.stats(data, ctx.repo, args.all, args.since)
    if args.command == '_profile':
        if args.action == 'show':
            if args.input or args.repo_file:
                raise DevFlowError('_profile show takes no input')
            return profile.show(data, ctx.repo)
        require(args.input)
        return profile.save(data, ctx.repo, read_json(args.input), args.repo_file)
    if args.command == '_metrics':
        if bool(args.run) == bool(args.lite):
            raise DevFlowError('Use exactly one of --run or --lite')
        value = {'role': args.role, 'model': args.model, 'tokens': args.tokens, 'duration_ms': args.duration_ms,
                 'tool_uses': args.tool_uses, 'source': args.source, 'task_id': args.task_id,
                 'worker_id': args.worker_id, 'phase': args.phase}
        if args.run:
            require(args.owner)
            with state.RunLock(data, args.run, args.owner):
                run = state.load(data, args.run)
                state.require_owner(run, args.owner)
                item = metrics.add(run, value)
                state.save(data, run, 'usage recorded')
                return item
        path = data / 'lite' / (safe_id(args.lite) + '.json')
        with FileLock(path.with_suffix('.lock'), args.owner or 'metrics'):
            record = read_json(path)
            if record.get('kind') != 'lite' or (record.get('coordinator_id') and record['coordinator_id'] != args.owner):
                raise DevFlowError('Lite ownership mismatch; pass the Coordinator --owner used at start')
            item = metrics.add(record, value)
            atomic_write(path, json_bytes(record))
            return item
    if args.command == 'cleanup':
        if args.discard and not args.apply:
            raise DevFlowError('--discard only applies together with --apply')
        return cleanup.cleanup(data, ctx.repo, args.apply, args.discard, args.into, args.purge_history,
                               args.remote, args.orca_idle_confirmed)
    if args.command == '_workspace':
        return cleanup.register_workspace(data, ctx.repo, read_json(args.input))
    if args.command == '_lite':
        if args.review and args.action != 'start':
            raise DevFlowError('--review only applies to _lite start')
        if args.author_id is not None and args.action != 'review-diff':
            raise DevFlowError('--author-id only applies to _lite review-diff')
        if args.action == 'status':
            require(args.lite)
            return lite.status(read_json(data / 'lite' / (safe_id(args.lite) + '.json')))
        if args.action in ('review-diff', 'review'):
            require(args.lite)
            if args.action == 'review':
                require(args.input)
            path = data / 'lite' / (safe_id(args.lite) + '.json')
            with FileLock(path.with_suffix('.lock'), args.owner or 'lite'):
                record = read_json(path)
                if record.get('kind') != 'lite' or (record.get('coordinator_id') and record['coordinator_id'] != args.owner):
                    raise DevFlowError('Lite ownership mismatch; pass the Coordinator --owner used at start')
                result = (lite.review_diff(data, record, args.author_id) if args.action == 'review-diff'
                          else lite.record_review(record, read_json(args.input)))
                atomic_write(path, json_bytes(record))
                return result
        if args.action != 'start':
            require(args.lite, args.owner, args.input)
            path = data / 'lite' / (safe_id(args.lite) + '.json')
            with FileLock(path.with_suffix('.lock'), args.owner):
                record = read_json(path)
                if record.get('kind') != 'lite' or record.get('executor') != 'orca' or record.get('coordinator_id') != args.owner:
                    raise DevFlowError('Lite Orca ownership mismatch')
                value = read_json(args.input)
                run = {'tasks': [record], 'orca_run_id': record.get('orca_run_id')}
                result = (orca.link(run, record, value) if args.action == 'link' else
                          orca.settle(record, value) if args.action == 'settle' else orca.account(run, record, value))
                record['orca_run_id'] = run.get('orca_run_id')
                if args.action == 'account':
                    record['status'] = 'settled'
                atomic_write(path, json_bytes(record))
                return result
        require(args.mode, args.request)
        if args.executor == 'orca':
            require(args.owner)
        if data.resolve().is_relative_to(Path(gitops.inspect(ctx.repo)['workspace']).resolve()):
            raise DevFlowError('--data-dir must be outside the source repository')
        if not args.request.strip():
            raise DevFlowError('Lite needs a nonempty request')
        info = gitops.lite_branch(ctx.repo, args.mode, args.request, args.base)
        lite_id = 'lite-' + uuid.uuid4().hex[:12]
        record = {'schema_version': 1, 'kind': 'lite', 'id': lite_id, 'repository': info['workspace'],
                  'git_common_dir': gitops.common_dir(info['workspace']),
                  'branch': info['branch'], 'base_revision': info['base_revision'],
                  'previous_branch': info['previous_branch'], 'mode': args.mode, 'request': args.request,
                  'created_at': now()}
        record.update(executor=args.executor, coordinator_id=args.owner, task_id=lite_id,
                      workspace=info['workspace'], status='pending', review_required=args.review,
                      untracked_preserved=info.get('untracked_preserved', []))
        # Minimal ownership record so cleanup only ever touches branches DevFlow created.
        atomic_write(data / 'lite' / (lite_id + '.json'), json_bytes(record))
        next_action = 'Delegate to pol-lite with this branch; never commit to the previous branch'
        if args.review:
            next_action += ('; after its commits run _lite review-diff and record an independent review '
                            'with _lite review before reporting')
        return record | {'workspace': info['workspace'], 'identity': gitops.identity(info['workspace']),
                         'session_model_hint': lite.SESSION_MODEL_HINT, 'next_action': next_action}
    if args.command == 'config':
        if args.action != 'set' and any((args.runtime, args.role, args.model, args.effort, args.inherit)):
            raise DevFlowError('Model selection flags require config set')
        if args.action == 'set':
            require(args.runtime, args.role)
            return package.config_set(data, args.runtime, args.role, args.model, args.effort, args.inherit, root)
        path = config.active_path(data, root)
        selected = config.load(path)
        if args.action == 'validate':
            return {'config_path': str(path), 'status': 'valid', 'model_availability': 'not_verified',
                    'adapters': {rt: len(adapters.render_all(rt, selected, root)) for rt in config.RUNTIMES}}
        return {'config_path': str(path), 'profiles': selected['profiles'], 'model_availability': 'not_verified',
                'coordinator': 'main session; not changed by this command'}
    if args.command == '_validate':
        return package.validate_context(data, root, args.runtime)
    if args.command == '_capabilities':
        return adapters.capabilities(args.runtime)
    if args.command == '_generate':
        from .storage import transaction
        rendered = adapters.render_all(args.runtime, config.load(config.active_path(data, root)), root)
        changes = {Path(args.destination) / name: text.encode('utf-8') for name, text in rendered.items()}
        if any(p.exists() for p in changes):
            raise DevFlowError('Generation destination contains existing profiles; use a new destination')
        backup = transaction(changes, data / 'backups')
        return {'generated': [str(p) for p in changes], 'backup': backup}
    if args.command in ('_install', '_uninstall'):
        runtimes = config.RUNTIMES if args.runtime == 'all' else (args.runtime,)
        return {rt: package.install(data, rt, getattr(args, rt + '_home'), root)
                if args.command == '_install' else package.uninstall(data, rt) for rt in runtimes}
    if args.command == '_run':
        return run_command(args, ctx)
    if args.command == '_orca':
        run = state.load(data, args.run)
        state.require_owner(run, args.owner)
        if run.get('executor') != 'orca':
            raise DevFlowError('Run does not use Orca')
        task = next((t for t in run['tasks'] if t['task_id'] == args.task_id), None)
        if not task:
            raise DevFlowError('No matching DevFlow assignment')
        if args.action == 'spec':
            return orca.spec(run, task, root, args.runtime)
        require(args.input)
        with state.RunLock(data, args.run, args.owner):
            run = state.load(data, args.run)
            state.require_owner(run, args.owner)
            if run['status'] != 'active' and (args.action == 'link' or run['status'] == 'completed'):
                raise DevFlowError('Run is closed; reconcile before changing Orca evidence')
            task = next(t for t in run['tasks'] if t['task_id'] == args.task_id)
            value = read_json(args.input)
            result = (orca.link(run, task, value) if args.action == 'link' else
                      orca.settle(task, value) if args.action == 'settle' else orca.account(run, task, value))
            state.save(data, run, 'Orca evidence ' + args.action)
            return result
    if args.command == '_git':
        if args.action == 'inspect':
            return gitops.inspect(args.workspace)
        if args.action == 'identity':
            return gitops.identity(gitops.inspect(args.workspace)['workspace'])
        if args.action == 'commit':
            require(args.message)
            return {'revision': gitops.commit(args.workspace, args.path, args.message, args.expected_branch,
                                              args.author_name, args.author_email)}
        if args.action == 'child':
            require(args.name)
            return gitops.child(args.workspace, args.name, data / 'worktrees')
        if args.action == 'integrate':
            require(args.child_branch)
            return gitops.integrate(args.workspace, args.child_branch, args.expected_branch)
        require(args.child_workspace)
        if not args.workers_confirmed_stopped:
            raise DevFlowError('Verify workers are stopped before removing a child worktree')
        return gitops.remove_integrated_child(args.workspace, args.child_workspace)
    raise DevFlowError('Unknown command')


def main(argv=None):
    # Console/redirect encoding must not depend on Windows' legacy codepage or PYTHONIOENCODING.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    context = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    context.add_argument('--data-dir', default=str(data_home()))
    context.add_argument('--repo', default=str(Path.cwd()))
    context.add_argument('--root', default=str(package_root()))
    ctx, remaining = context.parse_known_args(argv)
    args = parser().parse_args(remaining)
    try:
        output = dispatch(args, ctx)
        if isinstance(output, str):
            print(output)
        else:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        return 2 if args.command == 'cleanup' and args.apply and isinstance(output, dict) and output.get('errors') else 0
    except (DevFlowError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
