import { ChevronDown, ChevronUp } from 'lucide-react';
import { useId, useState } from 'react';
import type { ReactNode } from 'react';

import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { useTranslation } from '@/i18n/useI18n';
import { cn } from '@/lib/utils';

interface SkillSummaryCardProps {
	title: string;
	description: string;
	author?: string | null;
	iconUrl?: string | null;
	leading?: ReactNode;
	actions?: ReactNode;
	muted?: boolean;
}

/** Uniform collapsed cards, with independent disclosure of the full text. */
export function SkillSummaryCard({
	title,
	description,
	author,
	iconUrl,
	leading,
	actions,
	muted,
}: SkillSummaryCardProps) {
	const { t } = useTranslation();
	const [expanded, setExpanded] = useState(false);
	const contentId = useId();

	return (
		<article
			data-slot="skill-summary-card"
			data-expanded={expanded}
			className={cn(
				'flex w-full min-w-0 shrink-0 flex-col gap-2 rounded-lg border border-border p-3',
				expanded ? 'min-h-40' : 'h-40',
			)}
		>
			<div
				id={contentId}
				className={cn('flex min-w-0 flex-col gap-2', muted && 'text-muted-foreground')}
			>
				<div className="flex min-h-10 min-w-0 items-start gap-2.5">
					{leading && <div className="flex h-8 shrink-0 items-center">{leading}</div>}
					<Avatar className="shrink-0 rounded-md">
						<AvatarImage src={iconUrl ?? undefined} alt="" loading="lazy" />
						<AvatarFallback className="rounded-md">
							{title.slice(0, 1).toUpperCase()}
						</AvatarFallback>
					</Avatar>
					<div className="min-w-0 flex-1">
						<h3
							className={cn(
								'text-sm font-medium leading-5',
								expanded ? '[overflow-wrap:anywhere]' : 'truncate',
							)}
							title={title}
						>
							{title}
						</h3>
						<p
							className={cn(
								'min-h-4 text-xs leading-4 text-muted-foreground',
								expanded ? '[overflow-wrap:anywhere]' : 'truncate',
							)}
							title={author ?? undefined}
						>
							{author && `@${author}`}
						</p>
					</div>
				</div>
				<p
					className={cn(
						'text-sm leading-5 text-muted-foreground [overflow-wrap:anywhere]',
						expanded ? 'whitespace-pre-wrap' : 'line-clamp-2 h-10',
					)}
				>
					{description}
				</p>
			</div>
			<div className="mt-auto flex shrink-0 items-center justify-between gap-2">
				<Button
					type="button"
					variant="ghost"
					size="xs"
					aria-expanded={expanded}
					aria-controls={contentId}
					onClick={() => setExpanded((value) => !value)}
				>
					{expanded ? <ChevronUp /> : <ChevronDown />}
					{t(expanded ? 'common.collapse' : 'common.expand')}
				</Button>
				{actions}
			</div>
		</article>
	);
}
