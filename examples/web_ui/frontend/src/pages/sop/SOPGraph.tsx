import { GitBranch } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';

import { SOPStatus } from './SOPStatus';
import type { SOPData, SOPRunRecord } from '@/api';
import { useTranslation } from '@/i18n/useI18n';
import { cn } from '@/lib/utils';

/** Nodes retain their identity when the definition or display order changes. */
export function SOPGraph({
	data,
	run,
	selectedId,
	onSelect,
}: {
	data: Pick<SOPData, 'steps' | 'execution_mode'>;
	run?: SOPRunRecord;
	selectedId?: string | null;
	onSelect?: (id: string) => void;
}) {
	const { t } = useTranslation();
	const markerId = useId().replace(/:/g, '');
	const container = useRef<HTMLDivElement>(null);
	const [availableWidth, setAvailableWidth] = useState(0);
	useEffect(() => {
		if (!container.current) return;
		const observer = new ResizeObserver(([entry]) =>
			setAvailableWidth(entry.contentRect.width),
		);
		observer.observe(container.current);
		return () => observer.disconnect();
	}, []);
	const depths = new Map<string, number>();
	const visiting = new Set<string>();
	const dependencies = (index: number) =>
		data.execution_mode === 'dag'
			? (data.steps[index].depends_on ?? [])
			: index
				? [data.steps[index - 1].id]
				: [];
	const depth = (id: string): number => {
		if (depths.has(id)) return depths.get(id)!;
		if (visiting.has(id)) return 0;
		visiting.add(id);
		const index = data.steps.findIndex((step) => step.id === id);
		const result =
			index < 0
				? 0
				: Math.min(data.steps.length, Math.max(-1, ...dependencies(index).map(depth)) + 1);
		visiting.delete(id);
		depths.set(id, result);
		return result;
	};
	data.steps.forEach((step) => depth(step.id));
	const columns = Array.from(
		{ length: Math.max(0, ...depths.values()) + 1 },
		() => [] as string[],
	);
	data.steps.forEach((step) => columns[depths.get(step.id) ?? 0].push(step.id));
	const rows = Math.max(1, ...columns.map((column) => column.length));
	const nodeWidth = Math.max(
		152,
		Math.min(
			208,
			((availableWidth || columns.length * 248) - 48 - (columns.length - 1) * 48) /
				columns.length,
		),
	);
	const pitch = nodeWidth + 48;
	const width = columns.length * pitch;
	const height = Math.max(184, rows * 104 + 48);
	const positions = new Map(
		columns.flatMap((column, x) =>
			column.map(
				(id, y) =>
					[
						id,
						{ x: x * pitch + 24, y: (height - column.length * 104) / 2 + y * 104 + 14 },
					] as const,
			),
		),
	);
	return (
		<div
			ref={container}
			className="overflow-x-auto rounded-xl border border-border/70 bg-muted/40 [background-image:radial-gradient(var(--border)_1px,transparent_1px)] [background-size:16px_16px]"
			aria-label={t('sop.graph')}
		>
			<div className="relative mx-auto" style={{ width, height }}>
				<svg
					aria-hidden="true"
					className="pointer-events-none absolute inset-0 text-text-tertiary"
					width={width}
					height={height}
				>
					<defs>
						<marker
							id={markerId}
							viewBox="0 0 8 8"
							refX="7"
							refY="4"
							markerWidth="6"
							markerHeight="6"
							orient="auto"
						>
							<path
								d="M1 1 L7 4 L1 7"
								fill="none"
								stroke="currentColor"
								strokeWidth="1.2"
							/>
						</marker>
					</defs>
					{data.steps.flatMap((step, index) =>
						dependencies(index).map((parent) => {
							const from = positions.get(parent);
							const to = positions.get(step.id);
							if (!from || !to) return null;
							return (
								<path
									key={`${parent}-${step.id}`}
									d={`M${from.x + nodeWidth},${from.y + 38} C${from.x + nodeWidth + 24},${from.y + 38} ${to.x - 24},${to.y + 38} ${to.x - 2},${to.y + 38}`}
									fill="none"
									stroke="currentColor"
									strokeWidth="1.25"
									markerEnd={`url(#${markerId})`}
									opacity={0.65}
								/>
							);
						}),
					)}
				</svg>
				{data.steps.map((step, index) => {
					const point = positions.get(step.id)!;
					const phase =
						run?.state.steps.find((state) => state.node_id === step.id)?.phase ??
						run?.state.steps[index]?.phase;
					const className = cn(
						'absolute flex h-[76px] items-center gap-2.5 rounded-xl border bg-card px-3.5 text-left shadow-xs transition-colors',
						selectedId === step.id
							? 'border-foreground/35 ring-2 ring-foreground/5'
							: 'border-border',
						onSelect &&
							'hover:border-foreground/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
					);
					const content = (
						<>
							{phase ? (
								<SOPStatus phase={phase} iconOnly />
							) : (
								<span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-muted font-mono text-xs text-muted-foreground">
									{String(index + 1).padStart(2, '0')}
								</span>
							)}
							<span className="min-w-0">
								<span className="block truncate text-[13px] font-medium">
									{step.subject || t('sop.stepNumber', { count: index + 1 })}
								</span>
								<span className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
									<GitBranch className="size-3 shrink-0" />
									<span className="truncate">
										{phase
											? t(`sop.phase.${phase}`)
											: t(`sop.verifier.${step.verifier?.type ?? 'none'}`)}
									</span>
								</span>
							</span>
						</>
					);
					return onSelect ? (
						<button
							key={step.id}
							type="button"
							aria-pressed={selectedId === step.id}
							onClick={() => onSelect(step.id)}
							style={{ left: point.x, top: point.y, width: nodeWidth }}
							className={className}
						>
							{content}
						</button>
					) : (
						<div
							key={step.id}
							style={{ left: point.x, top: point.y, width: nodeWidth }}
							className={className}
						>
							{content}
						</div>
					);
				})}
			</div>
		</div>
	);
}
