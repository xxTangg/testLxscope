import { Eye, EyeOff, Plus, Trash2, Pen, Loader2, FlaskConical } from 'lucide-react';
import { useState, useEffect, useRef } from 'react';

import { credentialApi, embeddingModelApi, modelApi, ttsModelApi } from '@/api';
import type {
	CredentialView,
	CredentialSchema,
	EmbeddingModelCard,
	ModelCard,
	TTSModelCard,
} from '@/api';
import { LONGXIN_AI_LABEL, NEW_API_CREDENTIAL_TYPE } from '@/api/credential';
import { CreateCredentialDialog } from '@/components/dialog/CreateCredentialDialog';
import { DeleteDialog } from '@/components/dialog/DeleteDialog';
import { EditCredentialDialog } from '@/components/dialog/EditCredentialDialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Separator } from '@/components/ui/separator';
import {
	Sidebar,
	SidebarContent,
	SidebarGroup,
	SidebarGroupContent,
	SidebarGroupLabel,
	SidebarHeader,
	SidebarMenu,
	SidebarMenuButton,
	SidebarMenuItem,
} from '@/components/ui/sidebar';
import { Skeleton } from '@/components/ui/skeleton';
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useCredentials } from '@/hooks/useCredentials';
import { useTranslation } from '@/i18n/useI18n';
import { cn } from '@/lib/utils';
import { formatNumber } from '@/utils/common.ts';

/** Which model list the detail panel is showing. */
type ModelTab = 'llm' | 'tts' | 'embedding';

/** A row in the model table — one of the three card shapes. */
type ModelRow = ModelCard | TTSModelCard | EmbeddingModelCard;
type ModelCheck = { status: 'checking' | 'passed' | 'failed'; detail?: string };

// ─── Masked value ─────────────────────────────────────────────────────────────

function MaskedValue({ value }: { value: string }) {
	const [visible, setVisible] = useState(false);
	const masked = value.length > 8 ? value.slice(0, 4) + '••••••••' + value.slice(-4) : '••••••••';
	return (
		<span className="flex items-center gap-x-1.5 font-mono text-sm">
			{visible ? value : masked}
			<Button
				size={'icon-sm'}
				className="text-text-tertiary hover:text-foreground"
				variant={'ghost'}
				onClick={() => setVisible((v) => !v)}
			>
				{visible ? <EyeOff /> : <Eye />}
			</Button>
		</span>
	);
}

// ─── Model table ──────────────────────────────────────────────────────────────

/** MIME main-types that stand on their own in the ACCEPTS / OUTPUTS cells. */
const MODALITIES = new Set(['text', 'image', 'video', 'audio']);

/** Marks a model as reasoning-capable; not a real input modality. */
const THINKING_TYPE = 'application/x-thinking';

/** Dense-vector output of an embedding model. */
const EMBEDDING_TYPE = 'application/x-embedding';

/**
 * Collapse a model's MIME list into short modality labels. Anything
 * outside the four media types (PDFs, office documents, …) folds into a
 * single `file` entry so the cell stays one line.
 *
 * @param types - MIME types straight off the model card.
 * @returns De-duplicated labels in encounter order.
 */
function modalities(types: string[]): string[] {
	const out = new Set<string>();
	for (const type of types) {
		if (type === THINKING_TYPE) continue;
		if (type === EMBEDDING_TYPE) {
			out.add('vector');
			continue;
		}
		const main = type.split('/')[0];
		out.add(MODALITIES.has(main) ? main : 'file');
	}
	return [...out];
}

/** Inline pill sitting next to a model name (reasoning, realtime, status). */
function ModelTag({ children }: { children: React.ReactNode }) {
	return (
		<span className="rounded bg-surface-muted px-1.75 py-0.5 font-mono text-[9px] tracking-[0.06em] uppercase text-text-secondary">
			{children}
		</span>
	);
}

function HeadCell({ children }: { children: React.ReactNode }) {
	return (
		<TableHead className="h-auto bg-muted px-4 py-2.25 font-mono text-[9.5px] font-normal tracking-widest uppercase text-text-tertiary">
			{children}
		</TableHead>
	);
}

/** Numeric / modality cell — mono, one step darker than the head row. */
function DataCell({ children, size }: { children: React.ReactNode; size: '11' | '11.5' }) {
	return (
		<TableCell
			className={cn(
				'px-4 py-2.5 font-mono text-text-secondary',
				size === '11' ? 'text-[11px]' : 'text-[11.5px]',
			)}
		>
			{children}
		</TableCell>
	);
}

interface ModelTableProps {
	/** Rows to render; the shape must match `variant`. */
	models: ModelRow[];
	/** Drives which numeric columns sit between MODEL and ACCEPTS. */
	variant: ModelTab;
	checks?: Record<string, ModelCheck>;
}

/**
 * The model list as a table: one row per model, sizes and modalities in
 * their own columns rather than repeated label/value pairs per card.
 *
 * @param models - Rows to render.
 * @param variant - Which column set applies.
 * @returns The bordered table plus its legend.
 */
function ModelTable({ models, variant, checks }: ModelTableProps) {
	const { t } = useTranslation();
	const isChat = variant === 'llm';
	const isEmbedding = variant === 'embedding';

	return (
		<div>
			<div className="overflow-x-auto rounded-[16px] border border-border">
				<Table className="min-w-[500px]">
					<TableHeader>
						<TableRow className="border-border hover:bg-transparent">
							<HeadCell>{t('credential.table.model')}</HeadCell>
							{checks && <HeadCell>{t('credential.checkStatus')}</HeadCell>}
							{(isChat || isEmbedding) && (
								<HeadCell>{t('credential.table.context')}</HeadCell>
							)}
							{isChat && <HeadCell>{t('credential.table.maxOutput')}</HeadCell>}
							{isEmbedding && <HeadCell>{t('credential.table.dimensions')}</HeadCell>}
							<HeadCell>{t('credential.table.accepts')}</HeadCell>
							<HeadCell>{t('credential.table.outputs')}</HeadCell>
						</TableRow>
					</TableHeader>
					<TableBody>
						{models.map((model) => {
							const chat = isChat ? (model as ModelCard) : null;
							const embed = isEmbedding ? (model as EmbeddingModelCard) : null;
							const tts = variant === 'tts' ? (model as TTSModelCard) : null;
							const context = chat?.context_size ?? embed?.context_size;
							return (
								<TableRow
									key={model.name}
									className="border-border hover:bg-row-hover"
								>
									<TableCell className="px-4 py-2.5 text-[12.5px] text-foreground">
										<span className="flex items-center gap-x-2">
											<span
												className="min-w-0 flex-1 truncate"
												title={model.name}
											>
												{model.label || model.name}
											</span>
											{model.input_types.includes(THINKING_TYPE) && (
												<ModelTag>{t('credential.reasoning')}</ModelTag>
											)}
											{tts?.realtime && (
												<ModelTag>{t('credential.realtime')}</ModelTag>
											)}
											{model.status !== 'active' && (
												<ModelTag>{model.status}</ModelTag>
											)}
										</span>
									</TableCell>
									{checks && (
										<DataCell size="11.5">
											<span title={checks[model.name]?.detail}>
												{t(
													'credential.check.' +
														(checks[model.name]?.status ?? 'unchecked'),
												)}
											</span>
										</DataCell>
									)}
									{(isChat || isEmbedding) && (
										<DataCell size="11.5">
											{context ? formatNumber(context) : '—'}
										</DataCell>
									)}
									{isChat && (
										<DataCell size="11.5">
											{chat?.output_size
												? formatNumber(chat.output_size)
												: '—'}
										</DataCell>
									)}
									{isEmbedding && (
										<DataCell size="11.5">{embed?.dimensions ?? '—'}</DataCell>
									)}
									<DataCell size="11">
										{modalities(model.input_types).join(' · ') || '—'}
									</DataCell>
									<DataCell size="11">
										{modalities(model.output_types).join(' · ') || '—'}
									</DataCell>
								</TableRow>
							);
						})}
					</TableBody>
				</Table>
			</div>
			<p className="mt-2.5 text-[11px] text-muted-foreground">
				{t(checks ? 'credential.configuredLegend' : 'credential.table.legend')}
			</p>
		</div>
	);
}

// ─── Detail panel ─────────────────────────────────────────────────────────────

interface DetailPanelProps {
	credential: CredentialView;
	schema: CredentialSchema | null;
	onEdit: () => void;
	onDelete: () => void;
	onSetEnabled: (enabled: boolean) => Promise<void>;
}

function DetailPanel({ credential, schema, onEdit, onDelete, onSetEnabled }: DetailPanelProps) {
	const { t } = useTranslation();
	const [models, setModels] = useState<ModelCard[]>([]);
	const [ttsModels, setTtsModels] = useState<TTSModelCard[]>([]);
	const [embeddingModels, setEmbeddingModels] = useState<EmbeddingModelCard[]>([]);
	const [modelsLoading, setModelsLoading] = useState(false);
	const [tab, setTab] = useState<ModelTab>('llm');
	const [checks, setChecks] = useState<Record<string, ModelCheck>>({});
	const [checking, setChecking] = useState(false);
	const [changingEnabled, setChangingEnabled] = useState(false);
	const controllerRef = useRef<AbortController | null>(null);
	const enabled = credential.enabled !== false;

	const type = credential.data.type as string | undefined;
	const modelsByTab = { llm: models, tts: ttsModels, embedding: embeddingModels };
	const activeTab = modelsByTab[tab].length
		? tab
		: ((Object.keys(modelsByTab) as ModelTab[]).find((key) => modelsByTab[key].length) ??
			'llm');
	const shown = modelsByTab[activeTab];
	const total = models.length + ttsModels.length + embeddingModels.length;

	useEffect(() => {
		if (!type) return;
		setChecks({});
		setChecking(false);
		let active = true;
		setModelsLoading(true);
		Promise.all([
			modelApi
				.list(type, credential.id)
				.then((res) => res.models)
				.catch(() => [] as ModelCard[]),
			ttsModelApi
				.list(type)
				.then((res) => res.models)
				.catch(() => [] as TTSModelCard[]),
			embeddingModelApi
				.list(type, credential.id)
				.then((res) => res.models)
				.catch(() => [] as EmbeddingModelCard[]),
		])
			.then(([chatModels, tts, embeddings]) => {
				if (!active) return;
				setModels(chatModels);
				setTtsModels(tts);
				setEmbeddingModels(embeddings);
			})
			.finally(() => {
				if (active) setModelsLoading(false);
			});
		return () => {
			active = false;
			controllerRef.current?.abort();
		};
	}, [credential.id, credential.updated_at, type, enabled]);

	const checkModels = async () => {
		const controller = new AbortController();
		controllerRef.current = controller;
		setChecking(true);
		setChecks(Object.fromEntries(models.map((model) => [model.name, { status: 'checking' }])));
		let next = 0;
		await Promise.all(
			Array.from({ length: Math.min(3, models.length) }, async () => {
				while (next < models.length && !controller.signal.aborted) {
					const model = models[next++].name;
					try {
						const result = await credentialApi.checkModel(
							credential.id,
							model,
							controller.signal,
						);
						if (!controller.signal.aborted)
							setChecks((previous) => ({ ...previous, [model]: result }));
					} catch (error) {
						if (!controller.signal.aborted)
							setChecks((previous) => ({
								...previous,
								[model]: {
									status: 'failed',
									detail: error instanceof Error ? error.message : '',
								},
							}));
					}
				}
			}),
		);
		if (!controller.signal.aborted) setChecking(false);
	};

	const toggleEnabled = async () => {
		setChangingEnabled(true);
		try {
			await onSetEnabled(!enabled);
		} catch {
			// The API client displays the error.
		} finally {
			setChangingEnabled(false);
		}
	};

	// Fields to display: use schema properties order, skip id/type/const fields
	const displayFields = schema
		? Object.entries(schema.properties).filter(
				([key, prop]) =>
					!['id', 'type', 'enabled', 'embedding_models'].includes(key) &&
					prop.const === undefined,
			)
		: Object.entries(credential.data)
				.filter(([key]) => !['id', 'type', 'enabled', 'embedding_models'].includes(key))
				.map(
					([key]) =>
						[key, { title: key, writeOnly: false }] as [
							string,
							{ title: string; writeOnly: boolean },
						],
				);

	const name = (credential.data.name as string | undefined) ?? credential.id;

	return (
		<div className="flex h-full flex-col">
			{/* Header */}
			<div className="shrink-0 flex items-start justify-between gap-x-4 p-[18px_18px_16px]">
				<div className="flex flex-col gap-y-1">
					<span className="text-foreground text-lg font-medium tracking-[-0.015em]">
						{name}
					</span>
					<span className="font-mono text-text-data text-sm">{LONGXIN_AI_LABEL}</span>
					<Badge variant="secondary">
						{t(enabled ? 'credential.enabled' : 'credential.disabled')}
					</Badge>
					{!credential.editable && (
						<Badge variant="secondary" title={t('common.readOnlyTooltip')}>
							{t('common.readOnly')}
						</Badge>
					)}
				</div>
				<div className="flex items-center gap-x-2 shrink-0">
					<Button
						size="sm"
						variant="ghost"
						className="text-text-tertiary hover:text-foreground"
						onClick={onEdit}
						aria-label={t('dialog-credential-edit.title')}
						disabled={!credential.editable}
						tooltip={credential.editable ? undefined : t('common.readOnlyTooltip')}
					>
						<Pen />
						{t('credential.editConfiguration')}
					</Button>
					<Button
						size="sm"
						variant="outline"
						disabled={!credential.editable || changingEnabled}
						onClick={toggleEnabled}
					>
						{t(enabled ? 'credential.disable' : 'credential.enable')}
					</Button>
					<Button
						size="icon-sm"
						variant="ghost"
						className="text-text-tertiary hover:bg-destructive-alpha-8 hover:text-destructive"
						onClick={onDelete}
						aria-label={t('common.delete')}
						disabled={!credential.editable}
						tooltip={credential.editable ? undefined : t('common.readOnlyTooltip')}
					>
						<Trash2 />
					</Button>
				</div>
			</div>

			<Separator className="shrink-0" />

			<div className="min-h-0 flex-1 overflow-y-auto">
				{/* Fields */}
				<div className="flex flex-col gap-y-3 p-[20px_18px_0]">
					{displayFields.map(([key, prop]) => {
						const schemaProp = prop as {
							title?: string;
							writeOnly?: boolean;
							format?: string;
						};
						const label = schemaProp.title ?? key.replace(/_/g, ' ');
						const isSecret = schemaProp.writeOnly || schemaProp.format === 'password';
						const val = credential.data[key];
						if (val === undefined || val === null) return null;
						const strVal = String(val);
						return (
							<div
								key={key}
								className="grid grid-cols-[104px_1fr] gap-x-4.5 gap-y-3 items-baseline font-mono"
							>
								<span className="text-[10px] text-text-tertiary tracking-[0.12em] uppercase">
									{label}
								</span>
								{isSecret ? (
									<MaskedValue value={strVal} />
								) : (
									<span className="text-sm text-foreground break-all">
										{strVal}
									</span>
								)}
							</div>
						);
					})}
				</div>

				{/* Available Models */}
				<Tabs
					value={activeTab}
					onValueChange={(v) => setTab(v as ModelTab)}
					className="gap-0 px-[18px] pb-6"
				>
					<div className="mt-[30px] mb-3 flex flex-wrap items-center justify-between gap-2">
						<span className="flex items-center gap-x-2 text-[13.5px] font-medium text-foreground">
							{t(
								type === NEW_API_CREDENTIAL_TYPE
									? 'credential.availableModels'
									: 'credential.candidateModels',
							)}
							<span className="font-mono text-[11px] text-text-data">{total}</span>
						</span>
						{type === NEW_API_CREDENTIAL_TYPE && models.length > 0 && (
							<Button
								size="sm"
								variant="outline"
								tooltip={t('credential.checkHint')}
								disabled={checking || !credential.editable || !enabled}
								onClick={checkModels}
							>
								{checking ? (
									<Loader2 className="size-3.5 animate-spin" />
								) : (
									<FlaskConical className="size-3.5" />
								)}
								{t('credential.checkModels')}
							</Button>
						)}
						{/* Only worth a switch when there is a second list to switch to. */}
						{(ttsModels.length > 0 || embeddingModels.length > 0) && (
							<TabsList className="bg-surface-muted">
								{/* Only the shadow is overridden here; the stock one
							    is shadow-sm. */}
								{models.length > 0 && (
									<TabsTrigger
										value="llm"
										className="px-2.5 text-[11.5px] text-muted-foreground group-data-[variant=default]/tabs-list:data-active:shadow-tab!"
									>
										{t('common.llm')}
										<span className="font-mono text-[10px] text-text-data">
											{models.length}
										</span>
									</TabsTrigger>
								)}
								{ttsModels.length > 0 && (
									<TabsTrigger
										value="tts"
										className="px-2.5 text-[11.5px] text-muted-foreground group-data-[variant=default]/tabs-list:data-active:shadow-tab!"
									>
										{t('common.tts')}
										<span className="font-mono text-[10px] text-text-data">
											{ttsModels.length}
										</span>
									</TabsTrigger>
								)}
								{embeddingModels.length > 0 && (
									<TabsTrigger
										value="embedding"
										className="px-2.5 text-[11.5px] text-muted-foreground group-data-[variant=default]/tabs-list:data-active:shadow-tab!"
									>
										{t('common.embedding')}
										<span className="font-mono text-[10px] text-text-data">
											{embeddingModels.length}
										</span>
									</TabsTrigger>
								)}
							</TabsList>
						)}
					</div>

					{modelsLoading ? (
						<Skeleton className="h-40 rounded-[16px]" />
					) : shown.length === 0 ? (
						<Empty className="border-none py-6">
							<EmptyHeader>
								<EmptyTitle>{t('credential.noModels')}</EmptyTitle>
								<EmptyDescription>
									{t('credential.noModelsDescription')}
								</EmptyDescription>
							</EmptyHeader>
						</Empty>
					) : (
						<>
							<TabsContent value="llm">
								<ModelTable
									models={models}
									variant="llm"
									checks={type === NEW_API_CREDENTIAL_TYPE ? checks : undefined}
								/>
							</TabsContent>
							<TabsContent value="tts">
								<ModelTable models={ttsModels} variant="tts" />
							</TabsContent>
							<TabsContent value="embedding">
								<ModelTable models={embeddingModels} variant="embedding" />
							</TabsContent>
						</>
					)}
				</Tabs>
			</div>
		</div>
	);
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export const CredentialPage = () => {
	const { t } = useTranslation();
	const { credentials, loading, remove, setEnabled } = useCredentials();
	const [schemas, setSchemas] = useState<CredentialSchema[]>([]);
	const [selectedId, setSelectedId] = useState<string | null>(null);
	const [createOpen, setCreateOpen] = useState(false);
	const [editOpen, setEditOpen] = useState(false);
	const [deleteOpen, setDeleteOpen] = useState(false);
	const ordered = [...credentials].sort(
		(left, right) =>
			left.created_at.localeCompare(right.created_at) || left.id.localeCompare(right.id),
	);

	useEffect(() => {
		credentialApi.schemas().then(({ schemas }) => setSchemas(schemas));
	}, []);

	useEffect(() => {
		if (credentials.length > 0 && !credentials.some((entry) => entry.id === selectedId)) {
			setSelectedId(
				[...credentials].sort((left, right) =>
					left.created_at.localeCompare(right.created_at),
				)[0].id,
			);
		}
	}, [credentials, selectedId]);

	const selected = credentials.find((entry) => entry.id === selectedId);
	const schema =
		schemas.find((entry) => entry.properties.type?.const === selected?.data.type) ?? null;

	const handleDelete = async () => {
		if (!selected) return;
		await remove(selected.id);
		setSelectedId(null);
	};

	return (
		<div className="flex h-full w-full gap-2 p-2">
			<Sidebar collapsible="none" className="rounded-[22px]">
				<SidebarHeader className="flex flex-col gap-y-3 p-[20px_18px_14px]">
					<div className="text-xl font-medium tracking-[-0.02em]">
						{t('common.credential')}
					</div>
					<p className="text-xs text-text-tertiary">{t('credential.subtitle')}</p>
					<Button
						variant="outline"
						className="justify-start"
						onClick={() => setCreateOpen(true)}
					>
						<Plus />
						{t('credential.newConfiguration')}
					</Button>
				</SidebarHeader>
				<SidebarContent>
					{loading ? (
						<div className="space-y-2 p-4">
							<Skeleton className="h-8 rounded" />
						</div>
					) : (
						<SidebarGroup className="mt-4 px-2">
							<SidebarGroupLabel className="justify-between">
								{LONGXIN_AI_LABEL}
								<span className="font-mono text-xs">{credentials.length}</span>
							</SidebarGroupLabel>
							<SidebarGroupContent>
								<SidebarMenu>
									{ordered.map((entry) => (
										<SidebarMenuItem key={entry.id}>
											<SidebarMenuButton
												isActive={entry.id === selectedId}
												onClick={() => setSelectedId(entry.id)}
												title={entry.id}
											>
												<span className="min-w-0 flex-1 truncate">
													{String(entry.data.name || entry.id)}
												</span>
												{entry.enabled === false && (
													<Badge variant="secondary">
														{t('credential.disabled')}
													</Badge>
												)}
												{entry.data.type !== NEW_API_CREDENTIAL_TYPE && (
													<Badge variant="secondary">
														{t('credential.legacy')}
													</Badge>
												)}
												{!entry.editable && (
													<Badge variant="secondary">
														{t('common.readOnly')}
													</Badge>
												)}
											</SidebarMenuButton>
										</SidebarMenuItem>
									))}
								</SidebarMenu>
							</SidebarGroupContent>
						</SidebarGroup>
					)}
				</SidebarContent>
			</Sidebar>
			<main className="min-h-0 flex-1 overflow-hidden rounded-[22px] bg-card shadow-panel">
				{selected ? (
					<DetailPanel
						key={selected.id}
						credential={selected}
						schema={schema}
						onEdit={() => setEditOpen(true)}
						onDelete={() => setDeleteOpen(true)}
						onSetEnabled={(enabled) => setEnabled(selected.id, enabled)}
					/>
				) : (
					<div className="flex h-full items-center justify-center">
						<Empty className="border-none">
							<EmptyHeader>
								<EmptyTitle>{t('credential.selectHint')}</EmptyTitle>
								<EmptyDescription>
									{t('credential.selectHintDescription')}
								</EmptyDescription>
							</EmptyHeader>
						</Empty>
					</div>
				)}
			</main>
			<CreateCredentialDialog
				open={createOpen}
				onOpenChange={setCreateOpen}
				onCreated={(id) => setSelectedId(id)}
			/>
			{selected && (
				<>
					<EditCredentialDialog
						key={selected.id}
						open={editOpen}
						onOpenChange={setEditOpen}
						credential={selected}
					/>
					<DeleteDialog
						open={deleteOpen}
						onOpenChange={setDeleteOpen}
						title={t('common.deleteTitle', {
							entity: t('credential.deleteEntity'),
							name: selected.data.name || selected.id,
						})}
						description={t('common.deleteDescription')}
						onConfirm={handleDelete}
					/>
				</>
			)}
		</div>
	);
};
