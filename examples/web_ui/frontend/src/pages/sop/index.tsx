import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
	Bot,
	ChevronDown,
	GitBranch,
	History,
	ListOrdered,
	Loader2,
	MoreHorizontal,
	Pencil,
	Play,
	Plus,
	RefreshCw,
	Search,
	Trash2,
	Workflow,
	X,
} from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { SOPEditor } from './SOPEditor';
import { SOPGraph } from './SOPGraph';
import { SOPRuns } from './SOPRuns';
import { sopApi } from '@/api';
import type { AgentView, SOPRecord } from '@/api';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogClose,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
	DialogTrigger,
} from '@/components/ui/dialog';
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuSeparator,
	DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { useAgents } from '@/hooks/useAgents';
import { useTranslation } from '@/i18n/useI18n';
import { cn } from '@/lib/utils';

export function SOPPage() {
	const { t } = useTranslation();
	const { agents } = useAgents();
	const queryClient = useQueryClient();
	const [selectedId, setSelectedId] = useState<string | null>(null);
	const [search, setSearch] = useState('');
	const [tab, setTab] = useState('definition');
	const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
	const [editor, setEditor] = useState<{ sop: SOPRecord | null } | null>(null);
	const [runTarget, setRunTarget] = useState<SOPRecord | null>(null);
	const [runInput, setRunInput] = useState('');
	const [busy, setBusy] = useState(false);
	const [deleteTarget, setDeleteTarget] = useState<{
		type: 'sop' | 'run';
		id: string;
		sopId: string;
		name: string;
	} | null>(null);
	const sopsQuery = useQuery({ queryKey: ['sops'], queryFn: sopApi.list });
	const sops = sopsQuery.data?.sops ?? [];
	const selected = sops.find((sop) => sop.id === selectedId) ?? sops[0] ?? null;
	const filtered = sops.filter((sop) =>
		`${sop.data.name} ${sop.data.description}`
			.toLocaleLowerCase()
			.includes(search.trim().toLocaleLowerCase()),
	);
	const runsQuery = useQuery({
		queryKey: ['sop-runs', selected?.id],
		queryFn: () => sopApi.listRuns(selected!.id),
		enabled: !!selected,
		refetchInterval: (query) =>
			query.state.data?.runs.some(
				(run) => !['completed', 'cancelled', 'failed'].includes(run.state.phase),
			)
				? 4000
				: false,
	});
	const runs = runsQuery.data?.runs ?? [];
	const refreshRuns = () =>
		queryClient.invalidateQueries({ queryKey: ['sop-runs', selected?.id] });
	const selectSop = (id: string) => {
		setSelectedId(id);
		setSelectedRunId(null);
		setTab('definition');
	};
	const openRun = () => {
		if (selected) {
			setRunInput('');
			setRunTarget(selected);
		}
	};

	const startRun = async () => {
		if (!runTarget) return;
		setBusy(true);
		try {
			const run = await sopApi.startRun(runTarget.id, runInput);
			setSelectedId(runTarget.id);
			setSelectedRunId(run.id);
			setRunTarget(null);
			setRunInput('');
			setTab('runs');
			await queryClient.invalidateQueries({ queryKey: ['sop-runs', runTarget.id] });
			toast.success(t('sop.started'));
		} catch {
			/* The API client displays the error. Preserve the input for another attempt. */
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
				await queryClient.invalidateQueries({ queryKey: ['sops'] });
				queryClient.removeQueries({ queryKey: ['sop-runs', deleteTarget.id] });
				setSelectedRunId(null);
			} else {
				await sopApi.deleteRun(deleteTarget.id);
				await queryClient.invalidateQueries({ queryKey: ['sop-runs', deleteTarget.sopId] });
			}
			setDeleteTarget(null);
			toast.success(t('sop.deleted'));
		} catch {
			/* The API client displays the error. */
		} finally {
			setBusy(false);
		}
	};

	return (
		<div className="flex size-full p-2">
			<main className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-[22px] bg-card shadow-panel">
				<header className="flex shrink-0 items-start justify-between gap-4 border-b px-5 pt-5 pb-4 sm:px-6">
					<div>
						<h1 className="text-2xl font-semibold tracking-tight">{t('common.sop')}</h1>
						<p className="mt-1 text-sm text-muted-foreground">{t('sop.subtitle')}</p>
					</div>
					<Button className="mt-0.5" onClick={() => setEditor({ sop: null })}>
						<Plus className="size-3.5" />
						<span className="hidden sm:inline">{t('sop.new')}</span>
						<span className="sr-only sm:hidden">{t('sop.new')}</span>
					</Button>
				</header>
				<div className="flex min-h-0 flex-1 flex-col md:flex-row">
					<div className="shrink-0 border-b px-4 py-3 md:hidden">
						<Select
							value={selected?.id ?? ''}
							onValueChange={selectSop}
							disabled={!sops.length}
						>
							<SelectTrigger aria-label={t('sop.procedures')} className="h-9 w-full">
								<SelectValue
									placeholder={
										sopsQuery.isPending ? t('sop.loading') : t('sop.emptyList')
									}
								/>
							</SelectTrigger>
							<SelectContent>
								{sops.map((sop) => (
									<SelectItem key={sop.id} value={sop.id}>
										{sop.data.name}
									</SelectItem>
								))}
							</SelectContent>
						</Select>
					</div>
					<aside
						aria-label={t('sop.procedures')}
						className="hidden shrink-0 flex-col border-r bg-muted/25 md:flex md:w-60 xl:w-64"
					>
						<div className="shrink-0 px-4 pt-4 pb-3">
							<div className="mb-3 flex items-center justify-between text-xs font-medium text-muted-foreground">
								<span>{t('sop.procedures')}</span>
								<span className="font-mono text-[11px] text-text-tertiary">
									{sops.length}
								</span>
							</div>
							<div className="relative">
								<Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-text-tertiary" />
								<Input
									value={search}
									onChange={(event) => setSearch(event.target.value)}
									placeholder={t('sop.search')}
									aria-label={t('sop.search')}
									className="h-8 border-transparent bg-background pl-8 pr-7 text-xs shadow-xs focus-visible:border-ring"
								/>
								{search && (
									<button
										type="button"
										onClick={() => setSearch('')}
										className="absolute top-1/2 right-2 -translate-y-1/2 text-muted-foreground"
										aria-label={t('sop.clearSearch')}
									>
										<X className="size-3" />
									</button>
								)}
							</div>
						</div>
						<div className="min-h-0 space-y-1 overflow-y-auto px-2 pb-3">
							{sopsQuery.isPending
								? [0, 1, 2].map((id) => (
										<div key={id} className="space-y-2 p-3">
											<Skeleton className="h-4 w-3/4" />
											<Skeleton className="h-3 w-1/2" />
										</div>
									))
								: filtered.map((sop) => (
										<button
											key={sop.id}
											type="button"
											aria-current={
												selected?.id === sop.id ? 'true' : undefined
											}
											onClick={() => selectSop(sop.id)}
											className={cn(
												'group flex w-full items-start gap-2.5 rounded-xl px-3 py-3 text-left transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
												selected?.id === sop.id &&
													'bg-background shadow-xs ring-1 ring-border/70',
											)}
										>
											<span
												className={cn(
													'mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground',
													selected?.id === sop.id &&
														'bg-foreground/5 text-foreground',
												)}
											>
												<Workflow className="size-4" />
											</span>
											<span className="min-w-0 flex-1">
												<span className="block truncate text-[13px] font-medium">
													{sop.data.name}
												</span>
												<span className="mt-1 block truncate text-[11px] text-muted-foreground">
													{t('sop.stepCount', {
														count: sop.data.steps.length,
													})}
													<span className="mx-1.5 text-text-tertiary">
														·
													</span>
													{t(`sop.${sop.data.execution_mode}`)}
												</span>
											</span>
										</button>
									))}
							{!sopsQuery.isPending &&
								!sopsQuery.isError &&
								filtered.length === 0 && (
									<p className="px-3 py-5 text-center text-xs leading-relaxed text-muted-foreground">
										{search ? t('sop.noSearchResults') : t('sop.emptyList')}
									</p>
								)}
						</div>
					</aside>
					{selected ? (
						<div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
							<div className="flex max-h-[45%] shrink-0 flex-wrap items-start justify-between gap-4 overflow-y-auto overscroll-contain px-5 pt-6 pb-5 sm:px-7">
								<div className="w-full min-w-0 sm:w-auto sm:flex-1">
									<div className="mb-2 flex items-center gap-1.5 text-[11px] text-muted-foreground">
										{selected.data.execution_mode === 'dag' ? (
											<GitBranch className="size-3" />
										) : (
											<ListOrdered className="size-3" />
										)}
										{t(`sop.${selected.data.execution_mode}`)}
										<span className="mx-1 text-text-tertiary">/</span>
										{t('sop.stepCount', { count: selected.data.steps.length })}
									</div>
									<h2 className="line-clamp-2 text-xl font-medium tracking-tight [overflow-wrap:anywhere]">
										{selected.data.name}
									</h2>
									{selected.data.description && (
										<SOPDescription key={selected.id} sop={selected} />
									)}
								</div>
								<div className="flex shrink-0 items-center gap-2">
									<Button
										variant="outline"
										onClick={() => setEditor({ sop: selected })}
									>
										<Pencil className="size-3.5" />
										{t('common.edit')}
									</Button>
									<Button onClick={openRun}>
										<Play className="size-3.5" />
										{t('sop.startRun')}
									</Button>
									<DropdownMenu>
										<DropdownMenuTrigger asChild>
											<Button
												variant="ghost"
												size="icon"
												aria-label={t('sop.moreActions')}
											>
												<MoreHorizontal className="size-4" />
											</Button>
										</DropdownMenuTrigger>
										<DropdownMenuContent align="end">
											<DropdownMenuItem
												onSelect={() => setEditor({ sop: selected })}
											>
												<Pencil />
												{t('sop.edit')}
											</DropdownMenuItem>
											<DropdownMenuSeparator />
											<DropdownMenuItem
												className="text-destructive focus:text-destructive"
												onSelect={() =>
													setDeleteTarget({
														type: 'sop',
														id: selected.id,
														sopId: selected.id,
														name: selected.data.name,
													})
												}
											>
												<Trash2 />
												{t('common.delete')}
											</DropdownMenuItem>
										</DropdownMenuContent>
									</DropdownMenu>
								</div>
							</div>
							<Tabs
								value={tab}
								onValueChange={setTab}
								className="min-h-0 flex-1 gap-0 overflow-hidden"
							>
								<div className="shrink-0 border-b px-5 sm:px-7">
									<TabsList variant="line" className="h-10 gap-5 p-0">
										<TabsTrigger
											value="definition"
											className="flex-none rounded-none px-0 pb-3 text-[13px] after:bottom-0"
										>
											<Workflow className="size-3.5" />
											{t('sop.definition')}
										</TabsTrigger>
										<TabsTrigger
											value="runs"
											className="flex-none rounded-none px-0 pb-3 text-[13px] after:bottom-0"
										>
											<History className="size-3.5" />
											{t('sop.runs')}
											<span className="ml-0.5 rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
												{runs.length}
											</span>
										</TabsTrigger>
									</TabsList>
								</div>
								<TabsContent
									value="definition"
									className="min-h-0 overflow-y-auto overscroll-contain"
								>
									<div className="mx-auto max-w-5xl p-5 sm:p-7">
										<Definition
											key={selected.id}
											sop={selected}
											agents={agents}
										/>
									</div>
								</TabsContent>
								<TabsContent
									value="runs"
									className="min-h-0 overflow-y-auto overscroll-contain"
								>
									<div className="mx-auto max-w-5xl p-5 sm:p-7">
										<SOPRuns
											key={selected.id}
											runs={runs}
											selectedId={selectedRunId}
											onSelect={setSelectedRunId}
											loading={runsQuery.isPending}
											refreshing={runsQuery.isFetching}
											error={runsQuery.isError}
											onRefresh={refreshRuns}
											onStart={openRun}
											onDelete={(id) =>
												setDeleteTarget({
													type: 'run',
													id,
													sopId: selected.id,
													name: t('sop.runDetail'),
												})
											}
										/>
									</div>
								</TabsContent>
							</Tabs>
						</div>
					) : (
						<div className="flex min-h-0 flex-1 flex-col items-center justify-center p-8 text-center">
							{sopsQuery.isPending ? (
								<>
									<Loader2 className="size-6 animate-spin text-muted-foreground" />
									<span className="sr-only">{t('sop.loading')}</span>
								</>
							) : sopsQuery.isError ? (
								<>
									<p className="text-sm text-muted-foreground">
										{t('sop.loadFailed')}
									</p>
									<Button
										variant="outline"
										className="mt-4"
										onClick={() => void sopsQuery.refetch()}
									>
										<RefreshCw />
										{t('sop.tryAgain')}
									</Button>
								</>
							) : (
								<>
									<span className="mb-5 flex size-16 items-center justify-center rounded-2xl border bg-muted/50">
										<Workflow className="size-7 text-muted-foreground" />
									</span>
									<h2 className="text-lg font-medium">{t('sop.emptyTitle')}</h2>
									<p className="mt-2 max-w-sm text-sm leading-relaxed text-muted-foreground">
										{t('sop.emptyHint')}
									</p>
									<Button
										className="mt-6"
										onClick={() => setEditor({ sop: null })}
									>
										<Plus />
										{t('sop.new')}
									</Button>
									<div className="mt-8 flex items-center gap-3 text-xs text-text-tertiary">
										<span>{t('sop.defineSteps')}</span>
										<span>→</span>
										<span>{t('sop.assignAgents')}</span>
										<span>→</span>
										<span>{t('sop.runAndReview')}</span>
									</div>
								</>
							)}
						</div>
					)}
				</div>
			</main>
			{editor && (
				<SOPEditor
					sop={editor.sop}
					agents={agents}
					onClose={() => setEditor(null)}
					onSaved={(id) => {
						setSelectedId(id);
						setSearch('');
						setEditor(null);
						setTab('definition');
						void queryClient.invalidateQueries({ queryKey: ['sops'] });
					}}
				/>
			)}
			<Dialog
				open={!!runTarget}
				onOpenChange={(open) => {
					if (!open && !busy) setRunTarget(null);
				}}
			>
				<DialogContent className="sm:max-w-lg" showCloseButton={!busy}>
					<DialogHeader>
						<DialogTitle>{t('sop.startRun')}</DialogTitle>
						<DialogDescription>
							{runTarget?.data.name}
							<span className="mx-1.5">·</span>
							{t('sop.stepCount', { count: runTarget?.data.steps.length ?? 0 })}
						</DialogDescription>
					</DialogHeader>
					<label className="space-y-2">
						<span className="text-xs font-medium text-text-secondary">
							{t('sop.runContext')}
							<span className="ml-2 font-normal text-text-tertiary">
								{t('sop.optional')}
							</span>
						</span>
						<Textarea
							autoFocus
							disabled={busy}
							value={runInput}
							onChange={(event) => setRunInput(event.target.value)}
							placeholder={t('sop.inputPlaceholder')}
							className="min-h-32 resize-y leading-relaxed"
						/>
					</label>
					<p className="text-xs leading-relaxed text-muted-foreground">
						{t('sop.startHint')}
					</p>
					<DialogFooter>
						<Button
							variant="outline"
							disabled={busy}
							onClick={() => setRunTarget(null)}
						>
							{t('common.cancel')}
						</Button>
						<Button disabled={busy} onClick={() => void startRun()}>
							{busy ? <Loader2 className="animate-spin" /> : <Play />}
							{t('sop.startRun')}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
			<Dialog
				open={!!deleteTarget}
				onOpenChange={(open) => {
					if (!open && !busy) setDeleteTarget(null);
				}}
			>
				<DialogContent showCloseButton={!busy}>
					<DialogHeader>
						<DialogTitle>{t('sop.deleteTitle')}</DialogTitle>
						<DialogDescription>
							{deleteTarget?.name && (
								<span className="mb-2 block font-medium text-foreground">
									{deleteTarget.name}
								</span>
							)}
							{deleteTarget?.type === 'sop'
								? t('sop.deleteSopWarning')
								: t('sop.deleteRunWarning')}
						</DialogDescription>
					</DialogHeader>
					<DialogFooter>
						<Button
							variant="outline"
							disabled={busy}
							onClick={() => setDeleteTarget(null)}
						>
							{t('common.cancel')}
						</Button>
						<Button
							variant="destructive"
							disabled={busy}
							onClick={() => void confirmDelete()}
						>
							{busy && <Loader2 className="animate-spin" />}
							{t('common.delete')}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</div>
	);
}

/** Keep full task material out of the fixed header so the active tab can scroll. */
function SOPDescription({ sop }: { sop: SOPRecord }) {
	const { t } = useTranslation();
	return (
		<Dialog>
			<div className="mt-2 flex max-w-3xl items-start gap-2">
				<p className="line-clamp-2 min-w-0 flex-1 text-sm leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">
					{sop.data.description}
				</p>
				<DialogTrigger asChild>
					<Button
						variant="link"
						size="xs"
						className="shrink-0 px-0 text-xs text-muted-foreground"
					>
						{t('sop.viewDescription')}
					</Button>
				</DialogTrigger>
			</div>
			<DialogContent className="flex max-h-[calc(100dvh-2rem)] flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl">
				<DialogHeader className="shrink-0 border-b px-5 py-4 pr-12">
					<DialogTitle>{t('sop.description')}</DialogTitle>
					<DialogDescription className="line-clamp-2 [overflow-wrap:anywhere]">
						{sop.data.name}
					</DialogDescription>
				</DialogHeader>
				<div
					tabIndex={0}
					role="region"
					aria-label={t('sop.fullDescription')}
					className="max-h-[60dvh] min-h-0 overflow-y-auto overscroll-contain whitespace-pre-wrap px-5 py-4 text-sm leading-7 [overflow-wrap:anywhere]"
				>
					{sop.data.description}
				</div>
				<DialogFooter className="m-0 shrink-0 rounded-none px-5 py-3">
					<DialogClose asChild>
						<Button variant="outline">{t('common.close')}</Button>
					</DialogClose>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

function Definition({ sop, agents }: { sop: SOPRecord; agents: AgentView[] }) {
	const { t } = useTranslation();
	const [active, setActive] = useState<string | null>(null);
	const selectNode = (id: string) => {
		setActive(id);
		window.requestAnimationFrame(() =>
			document.getElementById(`sop-definition-${id}`)?.scrollIntoView({
				behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
					? 'instant'
					: 'smooth',
				block: 'nearest',
			}),
		);
	};
	return (
		<div className="space-y-7">
			<section className="space-y-3">
				<div className="flex items-center justify-between">
					<h3 className="text-[13px] font-medium">{t('sop.flowOverview')}</h3>
					<span className="text-[11px] text-text-tertiary">{t('sop.graphHint')}</span>
				</div>
				<SOPGraph data={sop.data} selectedId={active} onSelect={selectNode} />
			</section>
			<section className="space-y-3">
				<h3 className="text-[13px] font-medium">{t('sop.stepDetails')}</h3>
				<div className="divide-y rounded-xl border">
					{sop.data.steps.map((step, index) => {
						const agent = agents.find((agent) => agent.id === step.executor.agent_id);
						const open = active === step.id;
						return (
							<div
								key={step.id}
								id={`sop-definition-${step.id}`}
								className="scroll-mt-4"
							>
								<button
									type="button"
									onClick={() => setActive(open ? null : step.id)}
									aria-expanded={open}
									aria-controls={`sop-definition-content-${step.id}`}
									className="flex w-full items-center gap-3 p-4 text-left transition-colors hover:bg-row-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
								>
									<span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-muted font-mono text-[11px] text-muted-foreground">
										{String(index + 1).padStart(2, '0')}
									</span>
									<span className="min-w-0 flex-1">
										<span className="block truncate text-[13px] font-medium">
											{step.subject}
										</span>
										<span className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
											<Bot className="size-3 shrink-0" />
											<span className="truncate">
												{agent?.data.name ?? t('sop.unavailableAgent')}
											</span>
										</span>
									</span>
									<span className="hidden shrink-0 rounded-md bg-muted px-2 py-1 text-[11px] text-muted-foreground sm:inline">
										{t(`sop.verifier.${step.verifier?.type ?? 'none'}`)}
									</span>
									<ChevronDown
										className={cn(
											'size-3.5 shrink-0 text-muted-foreground transition-transform',
											open && 'rotate-180',
										)}
									/>
								</button>
								{open && (
									<div
										id={`sop-definition-content-${step.id}`}
										className="space-y-3 px-4 pb-5 sm:pl-14"
									>
										<p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-text-secondary">
											{step.description}
										</p>
										<div className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-muted-foreground">
											<span>
												{t('common.model')}:{' '}
												{sop.data.session_settings[
													step.executor.session_key
												]?.chat_model_config?.model ?? '—'}
											</span>
											<span>
												{t('sop.maxAttempts')}: {step.max_attempts}
											</span>
										</div>
										{step.verifier?.type === 'human' && (
											<p className="rounded-lg bg-muted/60 p-3 text-xs leading-relaxed text-muted-foreground">
												{t('sop.question')}: {step.verifier.question}
											</p>
										)}
										{step.verifier?.type === 'agent' && (
											<p className="rounded-lg bg-muted/60 p-3 text-xs leading-relaxed text-muted-foreground">
												{t('sop.verifierAgent')}:{' '}
												{agents.find(
													(agent) =>
														step.verifier?.type === 'agent' &&
														agent.id === step.verifier.agent.agent_id,
												)?.data.name ?? t('sop.unavailableAgent')}
												{step.verifier.criteria && (
													<span className="mt-1.5 block">
														{t('sop.criteria')}:{' '}
														{step.verifier.criteria}
													</span>
												)}
											</p>
										)}
									</div>
								)}
							</div>
						);
					})}
				</div>
			</section>
		</div>
	);
}
