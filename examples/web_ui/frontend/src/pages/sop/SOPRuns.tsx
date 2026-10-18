import {
	Check,
	ChevronDown,
	Clock3,
	ExternalLink,
	History,
	Loader2,
	Pause,
	Play,
	RefreshCw,
	RotateCcw,
	Trash2,
} from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { SOPGraph } from './SOPGraph';
import { SOPStatus } from './SOPStatus';
import { sopApi } from '@/api';
import type { SOPRunRecord } from '@/api';
import { Button } from '@/components/ui/button';
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useTranslation } from '@/i18n/useI18n';
import { cn } from '@/lib/utils';

export function SOPRuns({
	runs,
	selectedId,
	onSelect,
	loading,
	refreshing,
	error,
	onRefresh,
	onStart,
	onDelete,
}: {
	runs: SOPRunRecord[];
	selectedId: string | null;
	onSelect: (id: string) => void;
	loading: boolean;
	refreshing: boolean;
	error: boolean;
	onRefresh: () => Promise<unknown>;
	onStart: () => void;
	onDelete: (id: string) => void;
}) {
	const { t, i18n } = useTranslation();
	const selected = runs.find((run) => run.id === selectedId) ?? runs[0];
	const date = (value: string) =>
		new Date(value).toLocaleString(i18n.language, {
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit',
		});
	if (loading)
		return (
			<div role="status" className="flex justify-center py-24">
				<Loader2 className="size-5 animate-spin text-muted-foreground" />
				<span className="sr-only">{t('sop.loading')}</span>
			</div>
		);
	if (error)
		return (
			<div className="flex flex-col items-center gap-3 py-20 text-sm text-muted-foreground">
				<p>{t('sop.loadFailed')}</p>
				<Button variant="outline" onClick={() => void onRefresh()}>
					<RefreshCw />
					{t('sop.tryAgain')}
				</Button>
			</div>
		);
	if (!selected)
		return (
			<div className="flex flex-col items-center py-20 text-center">
				<div className="mb-4 flex size-12 items-center justify-center rounded-2xl bg-muted">
					<History className="size-5 text-muted-foreground" />
				</div>
				<h3 className="text-sm font-medium">{t('sop.noRuns')}</h3>
				<p className="mt-2 max-w-sm text-xs leading-relaxed text-muted-foreground">
					{t('sop.noRunsHint')}
				</p>
				<Button className="mt-5" onClick={onStart}>
					<Play className="size-3.5" />
					{t('sop.startRun')}
				</Button>
			</div>
		);
	return (
		<div className="space-y-6">
			<div className="flex flex-wrap items-center justify-between gap-3">
				<div className="flex items-center gap-2 text-xs text-muted-foreground">
					<History className="size-3.5" />
					{t('sop.runCount', { count: runs.length })}
				</div>
				<div className="flex min-w-0 items-center gap-2">
					<Select value={selected.id} onValueChange={onSelect}>
						<SelectTrigger
							aria-label={t('sop.selectRun')}
							className="w-full min-w-0 sm:w-72"
						>
							<SelectValue />
						</SelectTrigger>
						<SelectContent>
							{runs.map((run) => (
								<SelectItem key={run.id} value={run.id}>
									{date(run.created_at)} · {t(`sop.phase.${run.state.phase}`)}
								</SelectItem>
							))}
						</SelectContent>
					</Select>
					<Button
						variant="ghost"
						size="icon"
						disabled={refreshing}
						onClick={() => void onRefresh()}
						aria-label={t('sop.refresh')}
						tooltip={t('sop.refresh')}
					>
						<RefreshCw className={cn('size-3.5', refreshing && 'animate-spin')} />
					</Button>
				</div>
			</div>
			<RunDetail
				key={selected.id}
				run={selected}
				onRefresh={onRefresh}
				onDelete={() => onDelete(selected.id)}
			/>
		</div>
	);
}

function RunDetail({
	run,
	onRefresh,
	onDelete,
}: {
	run: SOPRunRecord;
	onRefresh: () => Promise<unknown>;
	onDelete: () => void;
}) {
	const { t, i18n } = useTranslation();
	const navigate = useNavigate();
	const [busy, setBusy] = useState(false);
	const [messages, setMessages] = useState<Record<string, string>>({});
	const [openNode, setOpenNode] = useState<string | null>(
		() =>
			run.state.steps.find((step) => ['awaiting', 'failed', 'running'].includes(step.phase))
				?.node_id ??
			run.definition.steps[0]?.id ??
			null,
	);
	const completed = run.state.steps.filter((step) => step.phase === 'completed').length;
	const action = async (callback: () => Promise<unknown>, success?: string) => {
		setBusy(true);
		try {
			await callback();
			await onRefresh();
			if (success) toast.success(success);
		} catch {
			/* The API client reports the error; keep this run and its draft visible. */
		} finally {
			setBusy(false);
		}
	};
	const verdict = async (index: number, passed: boolean) => {
		const state = run.state.steps[index];
		const nodeId = state.node_id || run.definition.steps[index].id;
		const message = messages[nodeId] ?? '';
		if (!passed && !message.trim()) {
			toast.error(t('sop.rejectReasonRequired'));
			return;
		}
		await action(async () => {
			await sopApi.verdict(run.id, index, passed, message.trim(), state.attempt_id);
			setMessages((current) => ({ ...current, [nodeId]: '' }));
		}, t('sop.verdictSaved'));
	};
	return (
		<>
			<div className="rounded-xl border p-4 sm:p-5">
				<div className="flex flex-wrap items-start justify-between gap-3">
					<div className="space-y-2">
						<div className="flex flex-wrap items-center gap-2.5">
							<h3 className="text-sm font-medium">{t('sop.runDetail')}</h3>
							<SOPStatus phase={run.state.phase} />
						</div>
						<p className="flex items-center gap-1.5 text-xs text-muted-foreground">
							<Clock3 className="size-3" />
							{new Date(run.created_at).toLocaleString(i18n.language)}
						</p>
					</div>
					<div className="flex items-center gap-1.5">
						{!['completed', 'cancelled'].includes(run.state.phase) && (
							<>
								<Button
									variant="outline"
									size="sm"
									disabled={busy}
									onClick={() => void action(() => sopApi.resume(run.id))}
								>
									{busy ? <Loader2 className="animate-spin" /> : <Play />}
									{t('sop.resume')}
								</Button>
								<Button
									variant="ghost"
									size="sm"
									disabled={busy}
									onClick={() => void action(() => sopApi.cancel(run.id))}
								>
									<Pause />
									{t('sop.cancelRun')}
								</Button>
							</>
						)}
						<Button
							variant="ghost"
							size="icon-sm"
							disabled={busy}
							onClick={onDelete}
							aria-label={t('common.delete')}
							tooltip={t('common.delete')}
							className="text-muted-foreground hover:text-destructive"
						>
							<Trash2 />
						</Button>
					</div>
				</div>
				<div className="mt-5 flex items-center gap-3">
					<div
						role="progressbar"
						aria-label={t('sop.runProgress')}
						aria-valuenow={completed}
						aria-valuemin={0}
						aria-valuemax={run.definition.steps.length}
						className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted"
					>
						<div
							className="h-full rounded-full bg-foreground/70 transition-[width] motion-reduce:transition-none"
							style={{
								width: `${(completed / Math.max(1, run.definition.steps.length)) * 100}%`,
							}}
						/>
					</div>
					<span className="shrink-0 font-mono text-[11px] text-muted-foreground">
						{completed} / {run.definition.steps.length}
					</span>
				</div>
			</div>
			<SOPGraph
				data={run.definition}
				run={run}
				selectedId={openNode}
				onSelect={(id) => {
					setOpenNode(id);
					window.requestAnimationFrame(() =>
						document.getElementById(`sop-run-node-${id}`)?.scrollIntoView({
							behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
								? 'instant'
								: 'smooth',
							block: 'nearest',
						}),
					);
				}}
			/>
			<div className="divide-y rounded-xl border">
				{run.definition.steps.map((step, index) => {
					const stateIndex = run.state.steps.findIndex(
						(state) => state.node_id === step.id,
					);
					const state = run.state.steps[stateIndex >= 0 ? stateIndex : index];
					const awaitingHuman =
						run.state.phase !== 'cancelled' &&
						state?.phase === 'awaiting' &&
						state.submission !== null &&
						(!state.wait_reason || state.wait_reason === 'human') &&
						step.verifier?.type === 'human';
					const activeRef =
						state?.wait_reason === 'tool' &&
						(state.waiting_on === 'verifier' ||
							(!state.waiting_on && state.submission !== null)) &&
						step.verifier?.type === 'agent'
							? step.verifier.agent
							: step.executor;
					const sessionKey =
						run.definition.execution_mode === 'dag'
							? `${step.id}/${activeRef.session_key}`
							: activeRef.session_key;
					const sessionId = run.sessions[sessionKey];
					const open = openNode === step.id;
					return (
						<section
							key={step.id}
							id={`sop-run-node-${step.id}`}
							className="scroll-mt-4"
						>
							<button
								type="button"
								aria-expanded={open}
								aria-controls={`sop-run-content-${step.id}`}
								onClick={() => setOpenNode(open ? null : step.id)}
								className="flex w-full items-center gap-3 p-4 text-left transition-colors hover:bg-row-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
							>
								<span className="w-5 shrink-0 font-mono text-xs text-text-tertiary">
									{String(index + 1).padStart(2, '0')}
								</span>
								<span className="min-w-0 flex-1 truncate text-sm font-medium">
									{step.subject}
								</span>
								<SOPStatus phase={state?.phase} />
								<ChevronDown
									className={cn(
										'size-3.5 shrink-0 text-muted-foreground transition-transform',
										open && 'rotate-180',
									)}
								/>
							</button>
							{open && (
								<div
									id={`sop-run-content-${step.id}`}
									className="space-y-4 px-4 pb-5 sm:pl-12"
								>
									<p className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
										{step.description}
									</p>
									{state?.error && (
										<p
											role="alert"
											className="rounded-lg bg-destructive/5 p-3 text-xs leading-relaxed text-destructive"
										>
											{state.error}
										</p>
									)}
									{state?.submission && (
										<div className="space-y-2">
											<h4 className="text-xs font-medium text-text-secondary">
												{t('sop.submission')}
											</h4>
											<pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted/60 p-3 font-sans text-xs leading-6">
												{state.submission
													.map((block) =>
														block.type === 'text'
															? (block.text ?? '')
															: JSON.stringify(block),
													)
													.join('\n')}
											</pre>
										</div>
									)}
									{awaitingHuman && (
										<div className="space-y-3 rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
											<div>
												<p className="text-xs font-medium text-amber-700 dark:text-amber-400">
													{t('sop.reviewNeeded')}
												</p>
												<p className="mt-1.5 text-sm">
													{step.verifier?.type === 'human'
														? step.verifier.question
														: ''}
												</p>
											</div>
											<Textarea
												aria-label={t('sop.verdictMessage')}
												value={messages[step.id] ?? ''}
												onChange={(event) =>
													setMessages((current) => ({
														...current,
														[step.id]: event.target.value,
													}))
												}
												placeholder={t('sop.verdictMessage')}
												className="bg-background"
											/>
											<div className="flex flex-wrap gap-2">
												<Button
													disabled={busy}
													size="sm"
													onClick={() =>
														void verdict(
															stateIndex >= 0 ? stateIndex : index,
															true,
														)
													}
												>
													{busy ? (
														<Loader2 className="animate-spin" />
													) : (
														<Check />
													)}
													{t('sop.approve')}
												</Button>
												<Button
													disabled={busy}
													variant="outline"
													size="sm"
													onClick={() =>
														void verdict(
															stateIndex >= 0 ? stateIndex : index,
															false,
														)
													}
												>
													<RotateCcw />
													{t('sop.reject')}
												</Button>
											</div>
										</div>
									)}
									<div className="flex flex-wrap gap-2">
										{sessionId && (
											<Button
												variant="outline"
												size="sm"
												onClick={() =>
													navigate(
														`/chat/${activeRef.agent_id}/${sessionId}`,
													)
												}
											>
												<ExternalLink />
												{state?.wait_reason === 'tool'
													? t('sop.handleTool')
													: t('sop.openChat')}
											</Button>
										)}
										{state &&
											![
												'cancelled',
												'running',
												'pending',
												'blocked',
												'retry_wait',
											].includes(state.phase) &&
											run.state.phase !== 'cancelled' && (
												<>
													{state.phase === 'failed' && (
														<Button
															size="sm"
															variant="outline"
															disabled={busy}
															onClick={() =>
																void action(() =>
																	sopApi.retryNode(
																		run.id,
																		step.id,
																		state.generation,
																	),
																)
															}
														>
															<RotateCcw />
															{t('sop.retryNode')}
														</Button>
													)}
													<Button
														size="sm"
														variant="ghost"
														disabled={busy}
														onClick={() =>
															void action(() =>
																sopApi.retryNode(
																	run.id,
																	step.id,
																	state.generation,
																	true,
																),
															)
														}
													>
														{t('sop.rerunDownstream')}
													</Button>
												</>
											)}
									</div>
									{state?.outputs && Object.keys(state.outputs).length > 0 && (
										<details className="text-xs">
											<summary className="cursor-pointer text-muted-foreground">
												{t('sop.outputs')}
											</summary>
											<pre className="mt-2 max-h-60 overflow-auto rounded-lg bg-muted/50 p-3">
												{JSON.stringify(state.outputs, null, 2)}
											</pre>
										</details>
									)}
									{!!state?.artifacts?.length && (
										<details className="text-xs">
											<summary className="cursor-pointer text-muted-foreground">
												{t('sop.artifacts')} · {state.artifacts.length}
											</summary>
											<div className="mt-2 space-y-2">
												{state.artifacts.map((artifact) => (
													<p
														key={artifact.sha256}
														className="break-all text-muted-foreground"
													>
														{artifact.name} · {artifact.size} bytes ·{' '}
														{artifact.sha256.slice(0, 12)}
													</p>
												))}
											</div>
										</details>
									)}
									{!!state?.attempts?.length && (
										<details className="text-xs">
											<summary className="cursor-pointer text-muted-foreground">
												{t('sop.attemptHistory')} · {state.attempts.length}
											</summary>
											{state.attempts.map((attempt) => (
												<div
													key={attempt.id}
													className="mt-3 space-y-1.5 border-l-2 pl-3 text-muted-foreground"
												>
													<p>
														#{attempt.number} ·{' '}
														{t(`sop.attemptStatus.${attempt.status}`)} ·{' '}
														{new Date(
															attempt.started_at,
														).toLocaleString(i18n.language)}
													</p>
													{attempt.error && (
														<p className="text-destructive">
															{attempt.error}
														</p>
													)}
													{Object.keys(attempt.outputs).length > 0 && (
														<pre className="max-h-40 overflow-auto">
															{JSON.stringify(
																attempt.outputs,
																null,
																2,
															)}
														</pre>
													)}
												</div>
											))}
										</details>
									)}
									{state?.verifications.map((result, attempt) => (
										<p key={attempt} className="text-xs text-muted-foreground">
											{t('sop.attempt', { count: attempt + 1 })} ·{' '}
											{result.passed ? t('sop.approved') : t('sop.rejected')}{' '}
											{result.message}
										</p>
									))}
								</div>
							)}
						</section>
					);
				})}
			</div>
		</>
	);
}
