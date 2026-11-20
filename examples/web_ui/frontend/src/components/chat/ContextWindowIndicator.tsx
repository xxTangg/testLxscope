import type { ContextWindowUsage } from '@/api';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useTranslation } from '@/i18n/useI18n';

const inputCategories = [
	{ key: 'system_tokens', label: 'system' },
	{ key: 'tool_tokens', label: 'tools' },
	{ key: 'message_tokens', label: 'messages' },
	{ key: 'summary_tokens', label: 'summary' },
] as const;

const percentageDigits = 1;
const percentageScale = 10 ** (percentageDigits + 2);

function getUsageBreakdown(usage: ContextWindowUsage, usedUnits: number) {
	const inputTokens = inputCategories.reduce((total, { key }) => total + usage[key], 0);
	let cumulativeTokens = 0;
	let previousUnits = 0;

	// Round cumulative shares so the displayed details add up to the displayed total.
	return inputCategories.map(({ key, label }) => {
		cumulativeTokens += usage[key];
		const cumulativeUnits =
			inputTokens > 0 ? Math.round((usedUnits * cumulativeTokens) / inputTokens) : 0;
		const ratio = (cumulativeUnits - previousUnits) / percentageScale;
		previousUnits = cumulativeUnits;
		return { label, ratio };
	});
}

export function ContextWindowIndicator({ usage }: { usage: ContextWindowUsage | null }) {
	const { t, i18n } = useTranslation();
	const percent = new Intl.NumberFormat(i18n.language, {
		style: 'percent',
		maximumFractionDigits: percentageDigits,
	});
	const title = t('chat.contextWindow.title');
	const triggerTokens = usage ? Math.ceil(usage.trigger_ratio * usage.context_size) : 0;
	const fixedTokens = usage ? usage.system_tokens + usage.tool_tokens : 0;
	const conversationBudget = Math.max(0, triggerTokens - fixedTokens);
	const conversationTokens = usage ? usage.message_tokens + usage.summary_tokens : 0;
	const usedRatio = conversationBudget > 0 ? conversationTokens / conversationBudget : 0;
	const usedUnits = Math.round(usedRatio * percentageScale);
	const displayedRatio = usedUnits / percentageScale;
	const exhausted = usage !== null && conversationBudget === 0;
	const status = exhausted ? t('chat.contextWindow.exhausted') : percent.format(displayedRatio);
	const fillUnits = exhausted ? percentageScale : Math.min(usedUnits, percentageScale);
	const fillClassName = `block h-full rounded-full ${exhausted || usedRatio >= 1 ? 'bg-amber-500' : 'bg-teal-500'}`;
	const fillStyle = { width: `${(fillUnits * 100) / percentageScale}%` };
	const breakdown = usage && !exhausted ? getUsageBreakdown(usage, usedUnits) : null;

	return (
		<Popover>
			<PopoverTrigger asChild>
				<Button
					type="button"
					variant="ghost"
					size="sm"
					className="gap-2 text-muted-foreground"
					aria-label={usage ? `${title} ${status}` : title}
				>
					<span
						aria-hidden
						className="h-1.5 w-10 overflow-hidden rounded-full bg-foreground/10"
					>
						<span className={fillClassName} style={fillStyle} />
					</span>
					{t('chat.contextWindow.shortLabel')}
					<span className="font-mono tabular-nums">{usage ? status : '—'}</span>
				</Button>
			</PopoverTrigger>
			<PopoverContent
				side="top"
				align="end"
				sideOffset={8}
				className="max-h-[var(--radix-popover-content-available-height)] w-64 max-w-[calc(100dvw_-_1.5rem)] gap-3 overflow-y-auto p-4"
				aria-label={title}
			>
				<h2 className="font-medium">{title}</h2>
				{usage ? (
					<>
						<p className="text-xs text-muted-foreground">
							{exhausted
								? status
								: t('chat.contextWindow.usagePercent', { percent: status })}
						</p>
						<div
							aria-hidden
							className="h-2 overflow-hidden rounded-full bg-foreground/10"
						>
							<span className={fillClassName} style={fillStyle} />
						</div>
						{breakdown && (
							<div className="space-y-2 border-t pt-3 text-xs">
								<h3 className="font-medium">
									{t('chat.contextWindow.usageBreakdown')}
								</h3>
								<dl className="space-y-2 text-muted-foreground">
									{breakdown.map(({ label, ratio }) => (
										<div key={label} className="flex justify-between gap-2">
											<dt>{t(`chat.contextWindow.${label}`)}</dt>
											<dd className="shrink-0 font-mono tabular-nums">
												{percent.format(ratio)}
											</dd>
										</div>
									))}
								</dl>
							</div>
						)}
					</>
				) : (
					<p className="text-xs text-muted-foreground">
						{t('chat.contextWindow.unavailable')}
					</p>
				)}
			</PopoverContent>
		</Popover>
	);
}
