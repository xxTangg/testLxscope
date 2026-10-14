import { ArrowDown, ArrowUp, ExternalLink, Loader2, Pencil, Play, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { sopApi } from '@/api';
import type { SOPData, SOPRecord, SOPRunRecord, SOPSessionSettings, SOPStep } from '@/api';
import { AgentSelect } from '@/components/select/AgentSelect';
import { LlmSelect } from '@/components/select/LlmSelect';
import { PermissionModeSelect } from '@/components/select/PermissionModeSelect';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { useAgents } from '@/hooks/useAgents';
import { useTranslation } from '@/i18n/useI18n';
import { createUuid } from '@/utils/uuid';

type EditorData = Omit<SOPData, 'session_settings'> & {
	session_settings: Record<string, Partial<SOPSessionSettings>>;
};

function newStep(): SOPStep {
	return {
		version: 'v1',
		subject: '',
		description: '',
		executor: { agent_id: '', session_key: `executor-${createUuid().slice(0, 8)}` },
		verifier: null,
		max_attempts: 3,
	};
}

function emptyEditor(): EditorData {
	return {
		name: '',
		description: '',
		steps: [newStep()],
		workspace_grain: 'run',
		session_settings: {},
	};
}

function sessionRefs(steps: SOPStep[]) {
	const refs = new Map<string, string>();
	for (const step of steps) {
		refs.set(step.executor.session_key, step.executor.agent_id);
		if (step.verifier?.type === 'agent') {
			refs.set(step.verifier.agent.session_key, step.verifier.agent.agent_id);
		}
	}
	return [...refs];
}

function submissionText(submission: SOPRunRecord['state']['steps'][number]['submission']) {
	if (!submission) return '';
	return submission.map((block) => block.type === 'text' ? block.text ?? '' : JSON.stringify(block)).join('\n');
}

export function SOPPage() {
	const { t } = useTranslation();
	const navigate = useNavigate();
	const { agents } = useAgents();
	const [sops, setSops] = useState<SOPRecord[]>([]);
	const [selectedId, setSelectedId] = useState<string | null>(null);
	const [runs, setRuns] = useState<SOPRunRecord[]>([]);
	const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
	const [loading, setLoading] = useState(true);
	const [busy, setBusy] = useState(false);
	const [editor, setEditor] = useState<EditorData | null>(null);
	const [editingId, setEditingId] = useState<string | null>(null);
	const [runInput, setRunInput] = useState('');
	const [verdictMessage, setVerdictMessage] = useState('');
	const [deleteTarget, setDeleteTarget] = useState<{ type: 'sop' | 'run'; id: string } | null>(null);

	const selected = sops.find((sop) => sop.id === selectedId) ?? null;
	const selectedRun = runs.find((run) => run.id === selectedRunId) ?? null;
	const refs = useMemo(() => editor ? sessionRefs(editor.steps) : [], [editor]);

	const refreshSops = useCallback(async () => {
		const result = await sopApi.list();
		setSops(result.sops);
		setSelectedId((current) => current && result.sops.some((sop) => sop.id === current)
			? current : result.sops[0]?.id ?? null);
	}, []);

	const refreshRuns = useCallback(async (sopId: string) => {
		const result = await sopApi.listRuns(sopId);
		setRuns(result.runs);
		setSelectedRunId((current) => current && result.runs.some((run) => run.id === current)
			? current : result.runs[0]?.id ?? null);
	}, []);

	useEffect(() => {
		void refreshSops().finally(() => setLoading(false));
	}, [refreshSops]);

	useEffect(() => {
		if (!selectedId) {
			setRuns([]);
			setSelectedRunId(null);
			return;
		}
		void refreshRuns(selectedId);
		const timer = window.setInterval(() => void refreshRuns(selectedId), 4000);
		return () => window.clearInterval(timer);
	}, [selectedId, refreshRuns]);

	const updateStep = (index: number, next: SOPStep) => {
		setEditor((current) => current && {
			...current,
			steps: current.steps.map((step, i) => i === index ? next : step),
		});
	};

	const moveStep = (index: number, direction: number) => {
		setEditor((current) => {
			if (!current) return current;
			const steps = [...current.steps];
			const next = index + direction;
			if (next < 0 || next >= steps.length) return current;
			[steps[index], steps[next]] = [steps[next], steps[index]];
			return { ...current, steps };
		});
	};

	const openEditor = (sop?: SOPRecord) => {
		setEditingId(sop?.id ?? null);
		setEditor(sop ? structuredClone(sop.data) : emptyEditor());
	};

	const save = async () => {
		if (!editor) return;
		if (!editor.name.trim() || editor.steps.some((step) =>
			!step.subject.trim() || !step.description.trim() || !step.executor.agent_id ||
			(step.verifier?.type === 'agent' && !step.verifier.agent.agent_id))) {
			toast.error(t('sop.required'));
			return;
		}
		if (refs.some(([key]) => !editor.session_settings[key]?.chat_model_config)) {
			toast.error(t('sop.modelRequired'));
			return;
		}
		const settings = Object.fromEntries(refs.map(([key]) => [key, editor.session_settings[key]])) as SOPData['session_settings'];
		const data: SOPData = {
			...editor,
			name: editor.name.trim(),
			steps: editor.steps.map((step) => ({ ...step, subject: step.subject.trim(), description: step.description.trim() })),
			session_settings: settings,
		};
		setBusy(true);
		try {
			const id = editingId
				? (await sopApi.update(editingId, data)).id
				: (await sopApi.create(data)).sop_id;
			await refreshSops();
			setSelectedId(id);
			setEditor(null);
			toast.success(t('sop.saved'));
		} finally {
			setBusy(false);
		}
	};

	const startRun = async () => {
		if (!selected) return;
		setBusy(true);
		try {
			const run = await sopApi.startRun(selected.id, runInput);
			setRunInput('');
			await refreshRuns(selected.id);
			setSelectedRunId(run.id);
			toast.success(t('sop.started'));
		} finally {
			setBusy(false);
		}
	};

	const submitVerdict = async (index: number, passed: boolean) => {
		if (!selectedRun) return;
		if (!passed && !verdictMessage.trim()) {
			toast.error(t('sop.rejectReasonRequired'));
			return;
		}
		setBusy(true);
		try {
			await sopApi.verdict(selectedRun.id, index, passed, verdictMessage.trim());
			setVerdictMessage('');
			await refreshRuns(selectedRun.sop_id);
			toast.success(t('sop.verdictSaved'));
		} finally {
			setBusy(false);
		}
	};

	const confirmDelete = async () => {
		if (!deleteTarget) return;
		setBusy(true);
		try {
			if (deleteTarget.type === 'sop') {
				await sopApi.delete(deleteTarget.id);
				await refreshSops();
			} else {
				await sopApi.deleteRun(deleteTarget.id);
				if (selectedId) await refreshRuns(selectedId);
			}
			setDeleteTarget(null);
			toast.success(t('sop.deleted'));
		} finally {
			setBusy(false);
		}
	};

	const phaseBadge = (phase: string) => (
		<Badge variant={phase === 'failed' ? 'destructive' : phase === 'completed' ? 'default' : 'secondary'}>
			{t(`sop.phase.${phase}`)}
		</Badge>
	);

	return (
		<div className="flex size-full p-2">
			<main className="flex h-full min-w-0 flex-1 flex-col overflow-hidden rounded-[22px] bg-card shadow-panel">
				<header className="flex items-center justify-between gap-3 border-b px-6 py-5">
					<div>
						<h1 className="text-2xl font-semibold">{t('common.sop')}</h1>
						<p className="mt-1 text-sm text-muted-foreground">{t('sop.subtitle')}</p>
					</div>
					<Button onClick={() => openEditor()}><Plus className="size-4" />{t('sop.new')}</Button>
				</header>
				<div className="grid min-h-0 flex-1 grid-cols-1 overflow-auto lg:grid-cols-[260px_minmax(0,1fr)]">
					<aside className="border-b p-4 lg:border-r lg:border-b-0">
						<div className="mb-3 text-xs font-medium uppercase text-muted-foreground">{t('sop.procedures')}</div>
						{loading && <Loader2 className="size-4 animate-spin" />}
						{!loading && sops.length === 0 && <p className="text-sm text-muted-foreground">{t('sop.empty')}</p>}
						<div className="space-y-1">
							{sops.map((sop) => (
								<button key={sop.id} type="button" onClick={() => setSelectedId(sop.id)}
									className={`w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-muted ${selectedId === sop.id ? 'bg-muted font-medium' : ''}`}>
									<div className="truncate">{sop.data.name}</div>
									<div className="text-xs text-muted-foreground">{t('sop.stepCount', { count: sop.data.steps.length })}</div>
								</button>
							))}
						</div>
					</aside>
					{selected ? (
						<div className="min-w-0 space-y-6 overflow-y-auto p-5 lg:p-6">
							<div className="flex flex-wrap items-start justify-between gap-3">
								<div><h2 className="text-xl font-semibold">{selected.data.name}</h2><p className="mt-1 text-sm text-muted-foreground">{selected.data.description || t('sop.noDescription')}</p></div>
								<div className="flex gap-2">
									<Button variant="outline" size="sm" onClick={() => openEditor(selected)}><Pencil className="size-4" />{t('common.edit')}</Button>
									<Button variant="outline" size="sm" onClick={() => setDeleteTarget({ type: 'sop', id: selected.id })}><Trash2 className="size-4" />{t('common.delete')}</Button>
								</div>
							</div>
							<div className="space-y-2">
								<h3 className="text-sm font-semibold">{t('sop.steps')}</h3>
								{selected.data.steps.map((step, index) => (
									<div key={index} className="rounded-xl border p-3 text-sm">
										<div className="font-medium">{index + 1}. {step.subject}</div>
										<div className="mt-1 text-muted-foreground">{step.description}</div>
										<div className="mt-2 text-xs text-muted-foreground">{t('sop.executor')}: {agents.find((agent) => agent.id === step.executor.agent_id)?.data.name ?? step.executor.agent_id} · {t(`sop.verifier.${step.verifier?.type ?? 'none'}`)}</div>
									</div>
								))}
							</div>
							<section className="space-y-3 rounded-xl border p-4">
								<h3 className="font-semibold">{t('sop.startRun')}</h3>
								<Textarea value={runInput} onChange={(event) => setRunInput(event.target.value)} placeholder={t('sop.inputPlaceholder')} />
								<Button disabled={busy} onClick={() => void startRun()}><Play className="size-4" />{t('sop.startRun')}</Button>
							</section>
							<section className="space-y-3">
								<div className="flex items-center justify-between"><h3 className="font-semibold">{t('sop.runs')}</h3><Button variant="ghost" size="icon-sm" onClick={() => void refreshRuns(selected.id)} aria-label={t('sop.refresh')}><RefreshCw className="size-4" /></Button></div>
								{runs.length === 0 && <p className="text-sm text-muted-foreground">{t('sop.noRuns')}</p>}
								<div className="flex flex-wrap gap-2">{runs.map((run) => (
									<button key={run.id} type="button" onClick={() => { setSelectedRunId(run.id); setVerdictMessage(''); }} className={`rounded-lg border px-3 py-2 text-left text-xs ${selectedRunId === run.id ? 'border-primary bg-muted' : ''}`}>
										<div>{new Date(run.created_at).toLocaleString()}</div><div className="mt-1">{phaseBadge(run.state.phase)}</div>
									</button>
								))}</div>
								{selectedRun && <div className="space-y-3 rounded-xl border p-4">
									<div className="flex items-center justify-between"><div className="text-sm font-medium">{t('sop.runDetail')} · {phaseBadge(selectedRun.state.phase)}</div><Button variant="ghost" size="icon-sm" onClick={() => setDeleteTarget({ type: 'run', id: selectedRun.id })} aria-label={t('common.delete')}><Trash2 className="size-4" /></Button></div>
									{selectedRun.definition.steps.map((step, index) => {
										const state = selectedRun.state.steps[index];
										const awaitingHuman = state?.phase === 'awaiting' && state.submission !== null && step.verifier?.type === 'human';
										const sessionId = selectedRun.sessions[step.executor.session_key];
										return <div key={index} className="rounded-lg bg-muted/50 p-3 text-sm">
											<div className="flex flex-wrap items-center gap-2"><span className="font-medium">{index + 1}. {step.subject}</span>{phaseBadge(state?.phase ?? 'pending')}
												{sessionId && <Button variant="link" size="sm" onClick={() => navigate(`/chat/${step.executor.agent_id}/${sessionId}`)}><ExternalLink className="size-3" />{t('sop.openChat')}</Button>}
											</div>
											{state?.submission && <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap rounded bg-background p-2 text-xs">{submissionText(state.submission)}</pre>}
											{state?.verifications.map((result, attempt) => <p key={attempt} className="mt-2 text-xs text-muted-foreground">{t('sop.attempt', { count: attempt + 1 })}: {result.passed ? t('sop.approved') : t('sop.rejected')} {result.message}</p>)}
											{awaitingHuman && <div className="mt-3 space-y-2"><p className="font-medium">{step.verifier?.type === 'human' ? step.verifier.question : ''}</p><Textarea value={verdictMessage} onChange={(event) => setVerdictMessage(event.target.value)} placeholder={t('sop.verdictMessage')} /><div className="flex gap-2"><Button disabled={busy} size="sm" onClick={() => void submitVerdict(index, true)}>{t('sop.approve')}</Button><Button disabled={busy} variant="outline" size="sm" onClick={() => void submitVerdict(index, false)}>{t('sop.reject')}</Button></div></div>}
										</div>;
									})}
								</div>}
							</section>
						</div>
					) : <div className="p-6 text-sm text-muted-foreground">{t('sop.empty')}</div>}
				</div>
			</main>

			<Dialog open={!!editor} onOpenChange={(open) => { if (!open && !busy) setEditor(null); }}>
				<DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
					<DialogHeader><DialogTitle>{editingId ? t('sop.edit') : t('sop.new')}</DialogTitle><DialogDescription>{t('sop.editorHint')}</DialogDescription></DialogHeader>
					{editor && <div className="space-y-5">
						<div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-sm"><span>{t('common.name')}</span><Input value={editor.name} onChange={(event) => setEditor({ ...editor, name: event.target.value })} /></label><label className="space-y-1 text-sm"><span>{t('sop.workspace')}</span><select className="h-9 w-full rounded-lg border bg-background px-2" value={editor.workspace_grain} onChange={(event) => setEditor({ ...editor, workspace_grain: event.target.value as SOPData['workspace_grain'] })}><option value="run">{t('sop.sharedWorkspace')}</option><option value="per_session_key">{t('sop.separateWorkspaces')}</option></select></label></div>
						<label className="block space-y-1 text-sm"><span>{t('sop.description')}</span><Textarea value={editor.description} onChange={(event) => setEditor({ ...editor, description: event.target.value })} /></label>
						<div className="flex items-center justify-between"><h3 className="font-semibold">{t('sop.steps')}</h3><Button variant="outline" size="sm" onClick={() => setEditor({ ...editor, steps: [...editor.steps, newStep()] })}><Plus className="size-4" />{t('sop.addStep')}</Button></div>
						{editor.steps.map((step, index) => <div key={step.executor.session_key} className="space-y-3 rounded-xl border p-4">
							<div className="flex items-center justify-between"><span className="font-medium">{t('sop.stepNumber', { count: index + 1 })}</span><div className="flex gap-1"><Button variant="ghost" size="icon-sm" disabled={index === 0} onClick={() => moveStep(index, -1)} aria-label={t('sop.moveUp')}><ArrowUp className="size-4" /></Button><Button variant="ghost" size="icon-sm" disabled={index === editor.steps.length - 1} onClick={() => moveStep(index, 1)} aria-label={t('sop.moveDown')}><ArrowDown className="size-4" /></Button><Button variant="ghost" size="icon-sm" disabled={editor.steps.length === 1} onClick={() => setEditor({ ...editor, steps: editor.steps.filter((_, i) => i !== index) })} aria-label={t('common.delete')}><Trash2 className="size-4" /></Button></div></div>
							<Input value={step.subject} onChange={(event) => updateStep(index, { ...step, subject: event.target.value })} placeholder={t('sop.subjectPlaceholder')} />
							<Textarea value={step.description} onChange={(event) => updateStep(index, { ...step, description: event.target.value })} placeholder={t('sop.stepDescriptionPlaceholder')} />
							<div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-sm"><span>{t('sop.executor')}</span><AgentSelect agents={agents} value={step.executor.agent_id} onChange={(agent_id) => updateStep(index, { ...step, executor: { ...step.executor, agent_id } })} className="w-full" /></label><label className="space-y-1 text-sm"><span>{t('sop.verifierLabel')}</span><select className="h-8 w-full rounded-lg border bg-background px-2" value={step.verifier?.type ?? 'none'} onChange={(event) => { const value = event.target.value; updateStep(index, { ...step, verifier: value === 'human' ? { type: 'human', question: t('sop.defaultQuestion') } : value === 'agent' ? { type: 'agent', agent: { agent_id: '', session_key: `verifier-${createUuid().slice(0, 8)}` }, criteria: '' } : null }); }}><option value="none">{t('sop.verifier.none')}</option><option value="human">{t('sop.verifier.human')}</option><option value="agent">{t('sop.verifier.agent')}</option></select></label></div>
							{step.verifier?.type === 'human' && <label className="block space-y-1 text-sm"><span>{t('sop.question')}</span><Textarea value={step.verifier.question} onChange={(event) => updateStep(index, { ...step, verifier: { type: 'human', question: event.target.value } })} /></label>}
							{step.verifier?.type === 'agent' && <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-sm"><span>{t('sop.verifierAgent')}</span><AgentSelect agents={agents} value={step.verifier.agent.agent_id} onChange={(agent_id) => { if (step.verifier?.type === 'agent') updateStep(index, { ...step, verifier: { ...step.verifier, agent: { ...step.verifier.agent, agent_id } } }); }} className="w-full" /></label><label className="space-y-1 text-sm"><span>{t('sop.criteria')}</span><Input value={step.verifier.criteria} onChange={(event) => { if (step.verifier?.type === 'agent') updateStep(index, { ...step, verifier: { ...step.verifier, criteria: event.target.value } }); }} /></label></div>}
							<label className="block space-y-1 text-sm"><span>{t('sop.maxAttempts')}</span><Input type="number" min={1} value={step.max_attempts} onChange={(event) => updateStep(index, { ...step, max_attempts: Math.max(1, Number(event.target.value) || 1) })} className="w-24" /></label>
						</div>)}
						<div className="space-y-3"><h3 className="font-semibold">{t('sop.sessions')}</h3><p className="text-xs text-muted-foreground">{t('sop.sessionsHint')}</p>{refs.map(([key, agentId]) => <div key={key} className="grid gap-2 rounded-lg border p-3 sm:grid-cols-2"><div className="text-sm font-medium sm:col-span-2">{agents.find((agent) => agent.id === agentId)?.data.name ?? (agentId || t('common.selectAgent'))} · {key}</div><label className="space-y-1 text-sm"><span>{t('common.model')}</span><LlmSelect value={editor.session_settings[key]?.chat_model_config ?? null} onChange={(chat_model_config) => setEditor({ ...editor, session_settings: { ...editor.session_settings, [key]: { ...editor.session_settings[key], ...(chat_model_config ? { chat_model_config } : {}) } } })} onAddCredential={() => navigate('/credential')} className="w-full" /></label><label className="space-y-1 text-sm"><span>{t('sop.permission')}</span><PermissionModeSelect value={editor.session_settings[key]?.permission_mode ?? 'default'} onChange={(permission_mode) => setEditor({ ...editor, session_settings: { ...editor.session_settings, [key]: { ...editor.session_settings[key], permission_mode } } })} className="w-full" /></label></div>)}</div>
					</div>}
					<DialogFooter><Button variant="outline" disabled={busy} onClick={() => setEditor(null)}>{t('common.cancel')}</Button><Button disabled={busy} onClick={() => void save()}>{busy ? t('common.saving') : t('common.save')}</Button></DialogFooter>
				</DialogContent>
			</Dialog>

			<Dialog open={!!deleteTarget} onOpenChange={(open) => { if (!open && !busy) setDeleteTarget(null); }}>
				<DialogContent><DialogHeader><DialogTitle>{t('sop.deleteTitle')}</DialogTitle><DialogDescription>{deleteTarget?.type === 'sop' ? t('sop.deleteSopWarning') : t('sop.deleteRunWarning')}</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" disabled={busy} onClick={() => setDeleteTarget(null)}>{t('common.cancel')}</Button><Button variant="destructive" disabled={busy} onClick={() => void confirmDelete()}>{t('common.delete')}</Button></DialogFooter></DialogContent>
			</Dialog>
		</div>
	);
}
