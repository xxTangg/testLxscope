import {
	ArrowDown,
	ArrowRight,
	ArrowUp,
	Check,
	ChevronDown,
	GitBranch,
	Layers3,
	ListOrdered,
	Loader2,
	Plus,
	Settings2,
	Trash2,
	X,
} from 'lucide-react';
import { useState } from 'react';
import type { ReactNode } from 'react';
import { toast } from 'sonner';

import { SOPGraph } from './SOPGraph';
import { SOPJsonField } from './SOPJsonField';
import { sopApi } from '@/api';
import type { AgentView, SOPData, SOPRecord, SOPSessionSettings, SOPStep } from '@/api';
import type { SOPAgentRef } from '@/api/sop';
import { CreateCredentialDialog } from '@/components/dialog/CreateCredentialDialog';
import { AgentSelect } from '@/components/select/AgentSelect';
import { LlmSelect } from '@/components/select/LlmSelect';
import { PermissionModeSelect } from '@/components/select/PermissionModeSelect';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
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
import { createUuid } from '@/utils/uuid';

type EditorData = Omit<SOPData, 'session_settings'> & {
	session_settings: Record<string, Partial<SOPSessionSettings>>;
};

function newStep(): SOPStep {
	return {
		version: 'v1',
		id: `node-${createUuid().slice(0, 8)}`,
		depends_on: [],
		input_bindings: {},
		timeout_seconds: 600,
		retry_delay_seconds: 2,
		subject: '',
		description: '',
		executor: { agent_id: '', session_key: `executor-${createUuid().slice(0, 8)}` },
		verifier: null,
		max_attempts: 3,
	};
}

function Field({
	label,
	children,
	optional = false,
}: {
	label: string;
	children: ReactNode;
	optional?: boolean;
}) {
	const { t } = useTranslation();
	return (
		<div className="space-y-2">
			<div className="text-xs font-medium text-text-secondary">
				{label}
				{optional && (
					<span className="ml-2 font-normal text-text-tertiary">{t('sop.optional')}</span>
				)}
			</div>
			{children}
		</div>
	);
}

function sessionRefs(steps: SOPStep[]) {
	return [
		...new Map(
			steps
				.flatMap((step) => [
					step.executor,
					...(step.verifier?.type === 'agent' ? [step.verifier.agent] : []),
				])
				.map((ref) => [ref.session_key, ref.agent_id]),
		),
	];
}

/** Prevent adding an edge to a descendant, which would create a cycle. */
function dependsOn(
	steps: SOPStep[],
	from: string,
	target: string,
	visited = new Set<string>(),
): boolean {
	if (from === target) return true;
	if (visited.has(from)) return false;
	visited.add(from);
	return (steps.find((step) => step.id === from)?.depends_on ?? []).some((id) =>
		dependsOn(steps, id, target, visited),
	);
}

export function SOPEditor({
	sop,
	agents,
	onClose,
	onSaved,
}: {
	sop: SOPRecord | null;
	agents: AgentView[];
	onClose: () => void;
	onSaved: (id: string) => void;
}) {
	const { t } = useTranslation();
	const [editor, setEditor] = useState<EditorData>(() =>
		sop
			? structuredClone(sop.data)
			: {
					name: '',
					description: '',
					execution_mode: 'dag',
					max_concurrency: 3,
					steps: [newStep()],
					workspace_grain: 'per_node',
					session_settings: {},
				},
	);
	const [initial] = useState(() => JSON.stringify(editor));
	const [active, setActive] = useState('overview');
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState('');
	const [jsonErrors, setJsonErrors] = useState<Record<string, boolean>>({});
	const [discardOpen, setDiscardOpen] = useState(false);
	const [credentialOpen, setCredentialOpen] = useState(false);
	const [modelRevision, setModelRevision] = useState(0);
	const hasJsonErrors = Object.values(jsonErrors).some(Boolean);
	const dirty = JSON.stringify(editor) !== initial || hasJsonErrors;

	const requestClose = () => {
		if (busy) return;
		if (dirty) setDiscardOpen(true);
		else onClose();
	};
	const updateStep = (index: number, next: SOPStep) =>
		setEditor((current) => ({
			...current,
			steps: current.steps.map((step, i) => (i === index ? next : step)),
		}));
	const updateSettings = (key: string, patch: Partial<SOPSessionSettings>) =>
		setEditor((current) => ({
			...current,
			session_settings: {
				...current.session_settings,
				[key]: { ...current.session_settings[key], ...patch },
			},
		}));
	const addStep = () => {
		const step = newStep();
		step.depends_on = editor.steps.length ? [editor.steps[editor.steps.length - 1].id] : [];
		setEditor({ ...editor, steps: [...editor.steps, step] });
		setActive(step.id);
		setError('');
	};
	const setExecutionMode = (mode: SOPData['execution_mode']) => {
		if (mode === editor.execution_mode) return;
		if (mode === 'sequential') setJsonErrors({});
		setEditor({
			...editor,
			execution_mode: mode,
			workspace_grain: mode === 'dag' ? 'per_node' : editor.workspace_grain,
			steps: editor.steps.map((step, index) => ({
				...step,
				depends_on:
					editor.execution_mode === 'sequential' && index
						? [editor.steps[index - 1].id]
						: step.depends_on,
			})),
		});
	};
	const moveStep = (index: number, direction: number) => {
		const steps = [...editor.steps];
		[steps[index], steps[index + direction]] = [steps[index + direction], steps[index]];
		setEditor({ ...editor, steps });
	};
	const removeStep = (id: string) => {
		const index = editor.steps.findIndex((step) => step.id === id);
		const steps = editor.steps
			.filter((step) => step.id !== id)
			.map((step) => ({
				...step,
				depends_on: step.depends_on.filter((parent) => parent !== id),
				input_bindings: Object.fromEntries(
					Object.entries(step.input_bindings ?? {}).filter(
						([, source]) => typeof source === 'string' && !source.startsWith(`${id}.`),
					),
				),
			}));
		setEditor({ ...editor, steps });
		setJsonErrors((current) =>
			Object.fromEntries(
				Object.entries(current).filter(([key]) => !key.startsWith(`${id}/`)),
			),
		);
		setActive(steps[Math.min(index, steps.length - 1)]?.id ?? 'overview');
	};
	const stepReady = (step: SOPStep) =>
		!Object.entries(jsonErrors).some(
			([key, invalid]) => key.startsWith(`${step.id}/`) && invalid,
		) &&
		Boolean(
			step.subject.trim() &&
			step.description.trim() &&
			step.executor.agent_id &&
			editor.session_settings[step.executor.session_key]?.chat_model_config &&
			(step.verifier?.type !== 'agent' ||
				(step.verifier.agent.agent_id &&
					editor.session_settings[step.verifier.agent.session_key]?.chat_model_config)),
		);
	const showError = (message: string, panel: string) => {
		setError(message);
		setActive(panel);
	};

	const save = async () => {
		setError('');
		if (!editor.name.trim()) {
			showError(t('sop.nameRequired'), 'overview');
			return;
		}
		const invalid = editor.steps.find(
			(step) =>
				!step.subject.trim() ||
				!step.description.trim() ||
				!step.executor.agent_id ||
				(step.verifier?.type === 'agent' && !step.verifier.agent.agent_id),
		);
		if (invalid) {
			showError(t('sop.required'), invalid.id);
			return;
		}
		const invalidJson = Object.entries(jsonErrors).find(([, invalid]) => invalid);
		if (invalidJson) {
			showError(t('sop.invalidJson'), invalidJson[0].split('/')[0]);
			return;
		}
		const missingModel = editor.steps.find(
			(step) =>
				!editor.session_settings[step.executor.session_key]?.chat_model_config ||
				(step.verifier?.type === 'agent' &&
					!editor.session_settings[step.verifier.agent.session_key]?.chat_model_config),
		);
		if (missingModel) {
			showError(t('sop.modelRequired'), missingModel.id);
			return;
		}
		if (
			editor.execution_mode === 'dag' &&
			editor.steps.some((step) =>
				step.depends_on.some((parent) => dependsOn(editor.steps, parent, step.id)),
			)
		) {
			showError(t('sop.cycleError'), 'overview');
			return;
		}
		const data: SOPData = {
			...editor,
			name: editor.name.trim(),
			description: editor.description.trim(),
			steps: editor.steps.map((step) => ({
				...step,
				subject: step.subject.trim(),
				description: step.description.trim(),
			})),
			session_settings: Object.fromEntries(
				sessionRefs(editor.steps).map(([key]) => [key, editor.session_settings[key]]),
			) as SOPData['session_settings'],
		};
		setBusy(true);
		try {
			const id = sop
				? (await sopApi.update(sop.id, data)).id
				: (await sopApi.create(data)).sop_id;
			toast.success(t('sop.saved'));
			onSaved(id);
		} catch (cause) {
			setError(cause instanceof Error ? cause.message : t('sop.saveFailed'));
		} finally {
			setBusy(false);
		}
	};

	const sessionFields = (ref: SOPAgentRef, onAgentChange: (agent_id: string) => void) => (
		<div className="space-y-4 rounded-xl bg-muted/60 p-4">
			<div className="grid gap-4 sm:grid-cols-2">
				<Field label={t('common.agent')}>
					<AgentSelect
						aria-label={t('common.agent')}
						agents={agents}
						value={ref.agent_id}
						onChange={onAgentChange}
						className="h-9 w-full bg-background"
					/>
				</Field>
				<Field label={t('common.model')}>
					<LlmSelect
						key={`${ref.session_key}-${modelRevision}`}
						aria-label={t('common.model')}
						value={editor.session_settings[ref.session_key]?.chat_model_config ?? null}
						onChange={(config) => {
							if (config)
								updateSettings(ref.session_key, { chat_model_config: config });
						}}
						onAddCredential={() => setCredentialOpen(true)}
						className="h-9 w-full bg-background"
					/>
				</Field>
			</div>
			<details className="group/permission">
				<summary className="flex w-fit cursor-pointer list-none items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
					<ChevronDown className="size-3 transition-transform group-open/permission:rotate-180" />
					{t('sop.permission')}
				</summary>
				<div className="mt-3">
					<PermissionModeSelect
						aria-label={t('sop.permission')}
						value={
							editor.session_settings[ref.session_key]?.permission_mode ?? 'default'
						}
						onChange={(permission_mode) =>
							updateSettings(ref.session_key, { permission_mode })
						}
						className="w-full sm:w-56"
					/>
				</div>
			</details>
		</div>
	);

	return (
		<>
			<Dialog
				open
				onOpenChange={(open) => {
					if (!open) requestClose();
				}}
			>
				<DialogContent
					showCloseButton={false}
					className="flex h-[min(84dvh,780px)] max-h-[calc(100dvh-2rem)] flex-col gap-0 overflow-hidden p-0 sm:max-w-[960px]"
					onEscapeKeyDown={(event) => {
						if (busy) event.preventDefault();
					}}
				>
					<DialogHeader className="shrink-0 flex-row items-center justify-between border-b px-5 py-4">
						<div className="space-y-1.5">
							<DialogTitle>{sop ? t('sop.edit') : t('sop.new')}</DialogTitle>
							<DialogDescription className="text-xs">
								{t('sop.editorHint')}
							</DialogDescription>
						</div>
						<Button
							variant="ghost"
							size="icon-sm"
							disabled={busy}
							onClick={requestClose}
							aria-label={t('common.close')}
						>
							<X />
						</Button>
					</DialogHeader>
					<div className="flex min-h-0 flex-1 flex-col sm:flex-row">
						<nav
							aria-label={t('sop.editorNavigation')}
							className="flex shrink-0 gap-1 overflow-x-auto border-b bg-muted/40 p-3 sm:w-56 sm:flex-col sm:gap-1.5 sm:overflow-x-hidden sm:overflow-y-auto sm:border-r sm:border-b-0"
						>
							<button
								type="button"
								onClick={() => setActive('overview')}
								aria-current={active === 'overview' ? 'step' : undefined}
								className={cn(
									'flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
									active === 'overview' && 'bg-background shadow-xs',
								)}
							>
								<Settings2 className="size-4 text-muted-foreground" />
								{t('sop.basics')}
							</button>
							<div className="hidden px-3 pt-5 pb-1 text-[11px] font-medium text-text-tertiary sm:block">
								{t('sop.steps')}{' '}
								<span className="ml-1 font-mono">{editor.steps.length}</span>
							</div>
							{editor.steps.map((step, index) => (
								<button
									key={step.id}
									type="button"
									aria-current={active === step.id ? 'step' : undefined}
									onClick={() => {
										setActive(step.id);
										setError('');
									}}
									className={cn(
										'flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
										active === step.id && 'bg-background shadow-xs',
									)}
								>
									<span className="flex size-5 shrink-0 items-center justify-center rounded-md bg-surface-muted font-mono text-[10px] text-muted-foreground">
										{index + 1}
									</span>
									<span className="max-w-40 truncate sm:max-w-none sm:flex-1">
										{step.subject || t('sop.untitledStep')}
									</span>
									{stepReady(step) && (
										<Check className="size-3 shrink-0 text-text-tertiary" />
									)}
								</button>
							))}
							<Button
								variant="ghost"
								size="sm"
								className="my-1 shrink-0 justify-start text-muted-foreground sm:mx-1"
								disabled={busy}
								onClick={addStep}
							>
								<Plus />
								{t('sop.addStep')}
							</Button>
						</nav>
						<div className="min-h-0 min-w-0 flex-1 overflow-y-auto overscroll-contain p-5 sm:p-7">
							<fieldset
								disabled={busy}
								className="min-w-0 space-y-6 disabled:opacity-70"
							>
								{error && (
									<p
										role="alert"
										className="rounded-lg bg-destructive/5 px-3 py-2.5 text-xs text-destructive"
									>
										{error}
									</p>
								)}
								<div hidden={active !== 'overview'} className="space-y-6">
									<div>
										<h3 className="font-medium">{t('sop.basics')}</h3>
										<p className="mt-1 text-xs text-muted-foreground">
											{t('sop.basicsHint')}
										</p>
									</div>
									<Field label={t('common.name')}>
										<Input
											aria-label={t('common.name')}
											autoFocus
											value={editor.name}
											onChange={(event) =>
												setEditor({ ...editor, name: event.target.value })
											}
											placeholder={t('sop.namePlaceholder')}
											className="h-9"
										/>
									</Field>
									<Field label={t('sop.description')} optional>
										<Textarea
											aria-label={t('sop.description')}
											value={editor.description}
											onChange={(event) =>
												setEditor({
													...editor,
													description: event.target.value,
												})
											}
											placeholder={t('sop.descriptionPlaceholder')}
											className="min-h-20 resize-y"
										/>
									</Field>
									<Field label={t('sop.executionMode')}>
										<div
											className="grid gap-3 sm:grid-cols-2"
											role="radiogroup"
											aria-label={t('sop.executionMode')}
										>
											{(['dag', 'sequential'] as const).map((mode) => {
												const Icon =
													mode === 'dag' ? GitBranch : ListOrdered;
												return (
													<button
														key={mode}
														type="button"
														role="radio"
														aria-checked={
															editor.execution_mode === mode
														}
														tabIndex={
															editor.execution_mode === mode ? 0 : -1
														}
														onClick={() => setExecutionMode(mode)}
														onKeyDown={(event) => {
															if (
																![
																	'ArrowLeft',
																	'ArrowRight',
																	'ArrowUp',
																	'ArrowDown',
																	'Home',
																	'End',
																].includes(event.key)
															)
																return;
															event.preventDefault();
															const next =
																event.key === 'Home'
																	? 'dag'
																	: event.key === 'End'
																		? 'sequential'
																		: mode === 'dag'
																			? 'sequential'
																			: 'dag';
															setExecutionMode(next);
															const buttons =
																event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
																	'[role="radio"]',
																);
															buttons?.[
																next === 'dag' ? 0 : 1
															]?.focus();
														}}
														className={cn(
															'flex items-start gap-3 rounded-xl border p-3.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
															editor.execution_mode === mode
																? 'border-foreground/40 bg-muted/50'
																: 'hover:bg-muted/40',
														)}
													>
														<Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
														<span className="flex-1">
															<span className="block text-sm font-medium">
																{t(`sop.${mode}`)}
															</span>
															<span className="mt-1 block text-xs leading-relaxed text-muted-foreground">
																{t(`sop.${mode}Hint`)}
															</span>
														</span>
														{editor.execution_mode === mode && (
															<Check className="mt-0.5 size-3.5 shrink-0" />
														)}
													</button>
												);
											})}
										</div>
									</Field>
									<details className="group rounded-xl border">
										<summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-xs font-medium text-text-secondary">
											<span className="flex items-center gap-2">
												<Layers3 className="size-3.5" />
												{t('sop.executionSettings')}
											</span>
											<ChevronDown className="size-3.5 transition-transform group-open:rotate-180" />
										</summary>
										<div className="grid gap-4 border-t p-4 sm:grid-cols-2">
											<Field label={t('sop.workspace')}>
												<Select
													value={editor.workspace_grain}
													onValueChange={(value) =>
														setEditor({
															...editor,
															workspace_grain:
																value as SOPData['workspace_grain'],
														})
													}
												>
													<SelectTrigger
														aria-label={t('sop.workspace')}
														className="h-9 w-full"
													>
														<SelectValue />
													</SelectTrigger>
													<SelectContent>
														<SelectItem value="per_node">
															{t('sop.nodeWorkspace')}
														</SelectItem>
														<SelectItem value="run">
															{t('sop.sharedWorkspace')}
														</SelectItem>
														<SelectItem value="per_session_key">
															{t('sop.separateWorkspaces')}
														</SelectItem>
													</SelectContent>
												</Select>
											</Field>
											{editor.execution_mode === 'dag' && (
												<Field label={t('sop.concurrency')}>
													<Input
														aria-label={t('sop.concurrency')}
														type="number"
														min={1}
														max={32}
														value={editor.max_concurrency}
														onChange={(event) =>
															setEditor({
																...editor,
																max_concurrency: Math.max(
																	1,
																	Math.min(
																		32,
																		Number(
																			event.target.value,
																		) || 1,
																	),
																),
															})
														}
													/>
												</Field>
											)}
										</div>
									</details>
									<div className="space-y-2.5">
										<div className="text-xs font-medium text-text-secondary">
											{t('sop.flowPreview')}
										</div>
										<SOPGraph data={editor} onSelect={setActive} />
									</div>
								</div>
								{editor.steps.map((step, index) => (
									<div
										key={step.id}
										hidden={active !== step.id}
										className="space-y-6"
									>
										<div className="flex items-center justify-between gap-3">
											<div>
												<h3 className="font-medium">
													{t('sop.stepNumber', { count: index + 1 })}
												</h3>
												<p className="mt-1 text-xs text-muted-foreground">
													{t('sop.stepHint')}
												</p>
											</div>
											<div className="flex items-center gap-1">
												<Button
													variant="ghost"
													size="icon-sm"
													disabled={index === 0}
													onClick={() => moveStep(index, -1)}
													aria-label={t('sop.moveUp')}
													tooltip={t('sop.moveUp')}
												>
													<ArrowUp />
												</Button>
												<Button
													variant="ghost"
													size="icon-sm"
													disabled={index === editor.steps.length - 1}
													onClick={() => moveStep(index, 1)}
													aria-label={t('sop.moveDown')}
													tooltip={t('sop.moveDown')}
												>
													<ArrowDown />
												</Button>
												<Button
													variant="ghost"
													size="icon-sm"
													className="text-muted-foreground hover:text-destructive"
													disabled={editor.steps.length === 1}
													onClick={() => removeStep(step.id)}
													aria-label={t('common.delete')}
													tooltip={t('common.delete')}
												>
													<Trash2 />
												</Button>
											</div>
										</div>
										<Field label={t('sop.subjectPlaceholder')}>
											<Input
												aria-label={t('sop.subjectPlaceholder')}
												value={step.subject}
												onChange={(event) =>
													updateStep(index, {
														...step,
														subject: event.target.value,
													})
												}
												placeholder={t('sop.subjectPlaceholder')}
												className="h-9"
											/>
										</Field>
										<Field label={t('sop.taskDescription')}>
											<Textarea
												aria-label={t('sop.taskDescription')}
												value={step.description}
												onChange={(event) =>
													updateStep(index, {
														...step,
														description: event.target.value,
													})
												}
												placeholder={t('sop.stepDescriptionPlaceholder')}
												className="min-h-24 resize-y leading-relaxed"
											/>
										</Field>
										<Field label={t('sop.executor')}>
											{sessionFields(step.executor, (agent_id) =>
												updateStep(index, {
													...step,
													executor: { ...step.executor, agent_id },
												}),
											)}
										</Field>
										<Field label={t('sop.verifierLabel')}>
											<Select
												value={step.verifier?.type ?? 'none'}
												onValueChange={(value) =>
													updateStep(index, {
														...step,
														verifier:
															value === 'human'
																? {
																		type: 'human',
																		question:
																			t(
																				'sop.defaultQuestion',
																			),
																	}
																: value === 'agent'
																	? {
																			type: 'agent',
																			agent: {
																				agent_id: '',
																				session_key: `verifier-${createUuid().slice(0, 8)}`,
																			},
																			criteria: '',
																		}
																	: null,
													})
												}
											>
												<SelectTrigger
													aria-label={t('sop.verifierLabel')}
													className="h-9 w-full"
												>
													<SelectValue />
												</SelectTrigger>
												<SelectContent>
													{['none', 'human', 'agent'].map((type) => (
														<SelectItem key={type} value={type}>
															{t(`sop.verifier.${type}`)}
														</SelectItem>
													))}
												</SelectContent>
											</Select>
										</Field>
										{step.verifier?.type === 'human' && (
											<Field label={t('sop.question')}>
												<Textarea
													aria-label={t('sop.question')}
													value={step.verifier.question}
													onChange={(event) =>
														updateStep(index, {
															...step,
															verifier: {
																type: 'human',
																question: event.target.value,
															},
														})
													}
												/>
											</Field>
										)}
										{step.verifier?.type === 'agent' && (
											<div className="space-y-4">
												{sessionFields(step.verifier.agent, (agent_id) => {
													if (step.verifier?.type === 'agent')
														updateStep(index, {
															...step,
															verifier: {
																...step.verifier,
																agent: {
																	...step.verifier.agent,
																	agent_id,
																},
															},
														});
												})}
												<Field label={t('sop.criteria')}>
													<Textarea
														aria-label={t('sop.criteria')}
														value={step.verifier.criteria}
														onChange={(event) => {
															if (step.verifier?.type === 'agent')
																updateStep(index, {
																	...step,
																	verifier: {
																		...step.verifier,
																		criteria:
																			event.target.value,
																	},
																});
														}}
													/>
												</Field>
											</div>
										)}
										{editor.execution_mode === 'dag' && (
											<Field label={t('sop.dependencies')}>
												<div className="flex flex-wrap gap-2">
													{editor.steps
														.filter((parent) => parent.id !== step.id)
														.map((parent) => {
															const checked =
																step.depends_on.includes(parent.id);
															return (
																<label
																	key={parent.id}
																	className={cn(
																		'flex max-w-full cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-xs transition-colors',
																		checked
																			? 'border-foreground/25 bg-muted'
																			: 'hover:bg-muted/50',
																		!checked &&
																			dependsOn(
																				editor.steps,
																				parent.id,
																				step.id,
																			) &&
																			'cursor-not-allowed opacity-40',
																	)}
																>
																	<Checkbox
																		checked={checked}
																		disabled={
																			!checked &&
																			dependsOn(
																				editor.steps,
																				parent.id,
																				step.id,
																			)
																		}
																		onCheckedChange={(value) =>
																			updateStep(index, {
																				...step,
																				depends_on:
																					value === true
																						? [
																								...step.depends_on,
																								parent.id,
																							]
																						: step.depends_on.filter(
																								(
																									id,
																								) =>
																									id !==
																									parent.id,
																							),
																			})
																		}
																	/>
																	<span className="truncate">
																		{parent.subject ||
																			t('sop.stepNumber', {
																				count:
																					editor.steps.indexOf(
																						parent,
																					) + 1,
																			})}
																	</span>
																</label>
															);
														})}
												</div>
												<p className="text-xs leading-relaxed text-muted-foreground">
													{t('sop.dependenciesHint')}
												</p>
											</Field>
										)}
										<details
											className="group rounded-xl border"
											open={
												Object.entries(jsonErrors).some(
													([key, invalid]) =>
														key.startsWith(`${step.id}/`) && invalid,
												) || undefined
											}
										>
											<summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-xs font-medium text-text-secondary">
												<span className="flex items-center gap-2">
													<Settings2 className="size-3.5" />
													{t('sop.advanced')}
												</span>
												<ChevronDown className="size-3.5 transition-transform group-open:rotate-180" />
											</summary>
											<div className="space-y-4 border-t p-4">
												<div className="grid gap-4 sm:grid-cols-3">
													<Field label={t('sop.maxAttempts')}>
														<Input
															aria-label={t('sop.maxAttempts')}
															type="number"
															min={1}
															value={step.max_attempts}
															onChange={(event) =>
																updateStep(index, {
																	...step,
																	max_attempts: Math.max(
																		1,
																		Number(
																			event.target.value,
																		) || 1,
																	),
																})
															}
														/>
													</Field>
													{editor.execution_mode === 'dag' && (
														<>
															<Field label={t('sop.timeout')}>
																<Input
																	aria-label={t('sop.timeout')}
																	type="number"
																	min={1}
																	max={86400}
																	value={
																		step.timeout_seconds ?? 600
																	}
																	onChange={(event) =>
																		updateStep(index, {
																			...step,
																			timeout_seconds:
																				Math.max(
																					1,
																					Math.min(
																						86400,
																						Number(
																							event
																								.target
																								.value,
																						) || 600,
																					),
																				),
																		})
																	}
																/>
															</Field>
															<Field label={t('sop.retryDelay')}>
																<Input
																	aria-label={t('sop.retryDelay')}
																	type="number"
																	min={0}
																	max={3600}
																	value={
																		step.retry_delay_seconds ??
																		2
																	}
																	onChange={(event) =>
																		updateStep(index, {
																			...step,
																			retry_delay_seconds:
																				Math.max(
																					0,
																					Math.min(
																						3600,
																						Number(
																							event
																								.target
																								.value,
																						) || 0,
																					),
																				),
																		})
																	}
																/>
															</Field>
														</>
													)}
												</div>
												{editor.execution_mode === 'dag' && (
													<>
														<p className="text-xs text-muted-foreground">
															{t('sop.nodeId')}:{' '}
															<code className="select-all">
																{step.id}
															</code>
														</p>
														<SOPJsonField
															stringValues
															label={t('sop.bindings')}
															value={step.input_bindings}
															onChange={(input_bindings) =>
																updateStep(index, {
																	...step,
																	input_bindings:
																		input_bindings as Record<
																			string,
																			string
																		>,
																})
															}
															onValidity={(valid) =>
																setJsonErrors((current) => ({
																	...current,
																	[`${step.id}/bindings`]: !valid,
																}))
															}
														/>
														<SOPJsonField
															label={t('sop.outputSchema')}
															value={step.output_schema}
															onChange={(output_schema) =>
																updateStep(index, {
																	...step,
																	output_schema,
																})
															}
															onValidity={(valid) =>
																setJsonErrors((current) => ({
																	...current,
																	[`${step.id}/schema`]: !valid,
																}))
															}
														/>
													</>
												)}
											</div>
										</details>
										{index < editor.steps.length - 1 && (
											<Button
												variant="outline"
												className="w-full"
												onClick={() =>
													setActive(editor.steps[index + 1].id)
												}
											>
												{t('sop.nextStep')}
												<ArrowRight />
											</Button>
										)}
									</div>
								))}
							</fieldset>
						</div>
					</div>
					<div className="flex shrink-0 items-center justify-between gap-3 border-t px-5 py-4">
						<span className="text-xs text-muted-foreground">
							{t('sop.configuredCount', {
								ready: editor.steps.filter(stepReady).length,
								total: editor.steps.length,
							})}
						</span>
						<div className="flex gap-2">
							<Button variant="outline" disabled={busy} onClick={requestClose}>
								{t('common.cancel')}
							</Button>
							{active === 'overview' && !sop ? (
								<Button
									onClick={() => {
										if (!editor.name.trim())
											showError(t('sop.nameRequired'), 'overview');
										else {
											setError('');
											setActive(editor.steps[0].id);
										}
									}}
								>
									{t('sop.configureSteps')}
									<ArrowRight />
								</Button>
							) : (
								<Button disabled={busy} onClick={() => void save()}>
									{busy ? <Loader2 className="animate-spin" /> : <Check />}
									{t('common.save')}
								</Button>
							)}
						</div>
					</div>
				</DialogContent>
			</Dialog>
			<Dialog open={discardOpen} onOpenChange={setDiscardOpen}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>{t('sop.discardTitle')}</DialogTitle>
						<DialogDescription>{t('sop.discardDescription')}</DialogDescription>
					</DialogHeader>
					<DialogFooter>
						<Button variant="outline" onClick={() => setDiscardOpen(false)}>
							{t('sop.keepEditing')}
						</Button>
						<Button variant="destructive" onClick={onClose}>
							{t('sop.discard')}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
			{credentialOpen && (
				<CreateCredentialDialog
					open
					onOpenChange={setCredentialOpen}
					onCreated={() => setModelRevision((current) => current + 1)}
				/>
			)}
		</>
	);
}
