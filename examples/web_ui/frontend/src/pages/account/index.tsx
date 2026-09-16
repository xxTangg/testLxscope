import { useQuery } from '@tanstack/react-query';
import { Loader2, LogOut, RefreshCw, Repeat2, UserRound } from 'lucide-react';
import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';

import { authApi } from '@/api';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { useAuth } from '@/hooks/useAuth';
import { useTranslation } from '@/i18n/useI18n';
import { formatNumber } from '@/utils/common';

type ActivityDay = {
	date: Date;
	dateKey: string;
	totalTokens: number;
	inRange: boolean;
};

const addDays = (date: Date, amount: number) => {
	const result = new Date(date);
	result.setDate(result.getDate() + amount);
	return result;
};

const toDateKey = (date: Date) => {
	const year = date.getFullYear();
	const month = String(date.getMonth() + 1).padStart(2, '0');
	const day = String(date.getDate()).padStart(2, '0');
	return `${year}-${month}-${day}`;
};

const activityColor = (tokens: number, maximum: number) => {
	if (tokens === 0) return 'bg-muted/60';
	const ratio = tokens / maximum;
	if (ratio <= 0.25) return 'bg-primary/20';
	if (ratio <= 0.5) return 'bg-primary/40';
	if (ratio <= 0.75) return 'bg-primary/60';
	return 'bg-primary';
};

export function AccountPage() {
	const { t, i18n } = useTranslation();
	const { user, logout } = useAuth();
	const navigate = useNavigate();
	const usage = useQuery({
		queryKey: ['auth', 'usage', user?.id],
		queryFn: authApi.usage,
		enabled: !!user,
	});

	const leaveAccount = async () => {
		await logout();
		navigate('/login', { replace: true });
	};

	const metrics = usage.data
		? [
				[t('auth.totalTokens'), usage.data.total_tokens],
				[t('auth.inputTokens'), usage.data.input_tokens],
				[t('auth.outputTokens'), usage.data.output_tokens],
				[t('auth.cacheTokens'), usage.data.cache_input_tokens],
			]
		: [];
	const dailyUsage = usage.data?.daily;
	const hasDailyUsage = (dailyUsage?.length ?? 0) > 0;
	const activity = useMemo(() => {
		const usageByDate = new Map((dailyUsage ?? []).map((day) => [day.date, day.total_tokens]));
		const today = new Date();
		const end = new Date(today.getFullYear(), today.getMonth(), today.getDate());
		const start = addDays(end, -364);
		const startOffset = (start.getDay() + 6) % 7;
		const gridStart = addDays(start, -startOffset);
		const endOffset = (end.getDay() + 6) % 7;
		const gridEnd = addDays(end, 6 - endOffset);
		const days: ActivityDay[] = [];

		for (let date = gridStart; date <= gridEnd; date = addDays(date, 1)) {
			const dateKey = toDateKey(date);
			days.push({
				date: new Date(date),
				dateKey,
				totalTokens: usageByDate.get(dateKey) ?? 0,
				inRange: date >= start && date <= end,
			});
		}

		const weeks: ActivityDay[][] = [];
		for (let index = 0; index < days.length; index += 7) {
			weeks.push(days.slice(index, index + 7));
		}

		return {
			weeks,
			maximum: Math.max(1, ...(dailyUsage ?? []).map((day) => day.total_tokens)),
		};
	}, [dailyUsage]);
	const activityLocale = i18n.language.startsWith('zh') ? 'zh-CN' : 'en-US';
	const dayLabels = i18n.language.startsWith('zh')
		? ['一', '二', '三', '四', '五', '六', '日']
		: ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

	return (
		<div className="h-full overflow-auto p-6">
			<div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
				<div>
					<h1 className="font-heading text-xl font-semibold">
						{t('auth.accountCenter')}
					</h1>
					<p className="mt-1 text-sm text-muted-foreground">
						{t('auth.accountCenterDescription')}
					</p>
				</div>

				<Card>
					<CardHeader>
						<CardTitle className="flex items-center gap-2">
							<UserRound className="size-4" />
							{t('auth.accountInfo')}
						</CardTitle>
						<CardDescription>{t('auth.brand')}</CardDescription>
					</CardHeader>
					<CardContent className="flex flex-col gap-4">
						<div className="grid gap-4 sm:grid-cols-2">
							<div>
								<div className="text-xs text-muted-foreground">
									{t('auth.username')}
								</div>
								<div className="mt-1 font-medium">{user?.username}</div>
							</div>
							<div>
								<div className="text-xs text-muted-foreground">
									{t('auth.userId')}
								</div>
								<div className="mt-1 truncate font-mono text-sm">{user?.id}</div>
							</div>
						</div>
						<Separator />
						<div className="flex flex-wrap gap-2">
							<Button variant="outline" onClick={() => void leaveAccount()}>
								<Repeat2 />
								{t('auth.switchAccount')}
							</Button>
							<Button variant="outline" onClick={() => void leaveAccount()}>
								<LogOut />
								{t('auth.logout')}
							</Button>
						</div>
					</CardContent>
				</Card>

				<Card>
					<CardHeader>
						<div className="flex items-start justify-between gap-4">
							<div>
								<CardTitle>{t('auth.tokenUsage')}</CardTitle>
								<CardDescription>{t('auth.tokenUsageDescription')}</CardDescription>
							</div>
							<Button
								variant="ghost"
								size="icon-sm"
								onClick={() => void usage.refetch()}
								disabled={usage.isFetching}
								aria-label={t('auth.refreshUsage')}
							>
								<RefreshCw className={usage.isFetching ? 'animate-spin' : ''} />
							</Button>
						</div>
					</CardHeader>
					<CardContent>
						{usage.isLoading ? (
							<div className="flex h-24 items-center justify-center">
								<Loader2 className="size-5 animate-spin text-muted-foreground" />
							</div>
						) : usage.isError ? (
							<Alert variant="destructive">
								<AlertDescription>{t('auth.usageLoadFailed')}</AlertDescription>
							</Alert>
						) : (
							<>
								<div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
									{metrics.map(([label, value]) => (
										<div key={label} className="rounded-lg bg-muted/60 p-3">
											<div className="text-xs text-muted-foreground">
												{label}
											</div>
											<div className="mt-1 font-mono text-lg font-semibold">
												{formatNumber(value as number)}
											</div>
										</div>
									))}
								</div>
								<p className="mt-4 text-xs text-muted-foreground">
									{t('auth.usageScope', {
										sessions: usage.data?.session_count ?? 0,
										messages: usage.data?.message_count ?? 0,
									})}
								</p>
								<div className="flex flex-col">
									<div className="order-2 mt-6">
										<div>
											<h3 className="text-sm font-medium">
												{t('auth.dailyUsage')}
											</h3>
											<p className="mt-1 text-xs text-muted-foreground">
												{t('auth.dailyUsageDescription')}
											</p>
										</div>
										{!hasDailyUsage ? (
											<p className="mt-3 rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">
												{t('auth.dailyUsageEmpty')}
											</p>
										) : (
											<div className="mt-3 max-h-80 divide-y overflow-y-auto rounded-lg border pr-1">
												{dailyUsage?.map((day) => (
													<div
														key={day.date}
														className="grid gap-3 px-3 py-3 sm:grid-cols-6 sm:items-center"
													>
														<div>
															<div className="text-xs text-muted-foreground">
																{t('auth.date')}
															</div>
															<div className="mt-1 font-mono text-sm font-medium">
																{day.date}
															</div>
														</div>
														<div>
															<div className="text-xs text-muted-foreground">
																{t('auth.totalTokens')}
															</div>
															<div className="mt-1 font-mono text-sm font-semibold">
																{formatNumber(day.total_tokens)}
															</div>
														</div>
														<div>
															<div className="text-xs text-muted-foreground">
																{t('auth.inputTokens')}
															</div>
															<div className="mt-1 font-mono text-sm">
																{formatNumber(day.input_tokens)}
															</div>
														</div>
														<div>
															<div className="text-xs text-muted-foreground">
																{t('auth.outputTokens')}
															</div>
															<div className="mt-1 font-mono text-sm">
																{formatNumber(day.output_tokens)}
															</div>
														</div>
														<div>
															<div className="text-xs text-muted-foreground">
																{t('auth.cacheTokens')}
															</div>
															<div className="mt-1 font-mono text-sm">
																{formatNumber(
																	day.cache_input_tokens,
																)}
															</div>
														</div>
														<div>
															<div className="text-xs text-muted-foreground">
																{t('auth.messageCount')}
															</div>
															<div className="mt-1 font-mono text-sm">
																{formatNumber(day.message_count)}
															</div>
														</div>
													</div>
												))}
											</div>
										)}
									</div>
									<div className="order-1 mt-6">
										<div className="flex items-center justify-between gap-4">
											<div>
												<h3 className="text-sm font-medium">
													{t('auth.tokenActivity')}
												</h3>
												<p className="mt-1 text-xs text-muted-foreground">
													{t('auth.tokenActivityDescription')}
												</p>
											</div>
											<span className="text-sm font-medium text-foreground">
												{t('auth.daily')}
											</span>
										</div>
										<div className="mt-4 overflow-x-auto pb-2">
											<div className="min-w-[680px]">
												<div
													className="ml-7 grid gap-1 text-[10px] text-muted-foreground"
													style={{
														gridTemplateColumns: `repeat(${activity.weeks.length}, 12px)`,
													}}
												>
													{activity.weeks.map((week, index) => {
														const firstDay = week.find(
															(day) => day.inRange,
														);
														if (!firstDay) return <span key={index} />;
														const monthKey = `${firstDay.date.getFullYear()}-${firstDay.date.getMonth()}`;
														const previousWeek =
															activity.weeks[index - 1];
														const previousDay = previousWeek?.find(
															(day) => day.inRange,
														);
														const previousMonthKey = previousDay
															? `${previousDay.date.getFullYear()}-${previousDay.date.getMonth()}`
															: '';
														return (
															<span key={`${monthKey}-${index}`}>
																{monthKey !== previousMonthKey
																	? firstDay.date.toLocaleDateString(
																			activityLocale,
																			{
																				month: 'short',
																			},
																		)
																	: ''}
															</span>
														);
													})}
												</div>
												<div className="mt-2 flex gap-1">
													<div className="grid w-5 shrink-0 grid-rows-7 gap-1 text-[10px] leading-3 text-muted-foreground">
														{dayLabels.map((label, index) => (
															<span key={`${label}-${index}`}>
																{index % 2 === 0 ? label : ''}
															</span>
														))}
													</div>
													<div className="grid grid-flow-col grid-rows-7 gap-1">
														{activity.weeks.flatMap((week) =>
															week.map((day) => (
																<span
																	key={day.dateKey}
																	className={`size-3 rounded-[3px] ${
																		day.inRange
																			? activityColor(
																					day.totalTokens,
																					activity.maximum,
																				)
																			: 'bg-transparent'
																	}`}
																	aria-label={
																		day.inRange
																			? `${day.dateKey}: ${formatNumber(day.totalTokens)} ${t('auth.totalTokens')}`
																			: undefined
																	}
																	title={
																		day.inRange
																			? `${day.dateKey}: ${formatNumber(day.totalTokens)} ${t('auth.totalTokens')}`
																			: undefined
																	}
																/>
															)),
														)}
													</div>
												</div>
												<div className="mt-3 flex items-center justify-end gap-2 text-[10px] text-muted-foreground">
													<span>{t('auth.less')}</span>
													{[0, 0.2, 0.4, 0.6, 1].map((level) => (
														<span
															key={level}
															className={`size-3 rounded-[3px] ${activityColor(
																level * activity.maximum,
																activity.maximum,
															)}`}
														/>
													))}
													<span>{t('auth.more')}</span>
												</div>
											</div>
										</div>
									</div>
								</div>
							</>
						)}
					</CardContent>
				</Card>
			</div>
		</div>
	);
}
