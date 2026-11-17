import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { toast } from 'sonner';

import { userAdminApi, type AuthUser } from '@/api/auth';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from '@/components/ui/table';
import { useAuth } from '@/hooks/useAuth';
import { useTranslation } from '@/i18n/useI18n';
import { formatNumber } from '@/utils/common';

const usersKey = ['admin', 'users'];

type AccountAction = {
	kind: 'password' | 'status';
	account: AuthUser;
};

function AccountActionDialog({ action, close }: { action: AccountAction; close: () => void }) {
	const { t } = useTranslation();
	const { user, logout } = useAuth();
	const queryClient = useQueryClient();
	const [password, setPassword] = useState('');
	const [confirmPassword, setConfirmPassword] = useState('');
	const [mismatch, setMismatch] = useState(false);
	const { account, kind } = action;
	const isReset = kind === 'password';
	const actionKey = isReset ? 'resetPassword' : account.enabled ? 'disable' : 'enable';
	const mutation = useMutation({
		mutationFn: () =>
			isReset
				? userAdminApi.resetPassword(account.username, password)
				: userAdminApi.setStatus(account.username, !account.enabled),
		onSuccess: (updated) => {
			toast.success(t(`userAdmin.${actionKey}Success`));
			close();
			if (isReset && updated.id === user?.id) {
				logout();
				return;
			}
			queryClient.setQueryData<AuthUser[]>(usersKey, (users) =>
				users?.map((item) => (item.id === updated.id ? updated : item)),
			);
			void queryClient.invalidateQueries({ queryKey: usersKey });
		},
	});

	const submit = (event: FormEvent<HTMLFormElement>) => {
		event.preventDefault();
		if (mutation.isPending) return;
		if (isReset && password !== confirmPassword) {
			setMismatch(true);
			return;
		}
		setMismatch(false);
		mutation.mutate();
	};

	return (
		<Dialog open onOpenChange={(open) => !open && !mutation.isPending && close()}>
			<DialogContent showCloseButton={!mutation.isPending}>
				<DialogHeader>
					<DialogTitle>{t(`userAdmin.${actionKey}`)}</DialogTitle>
					<DialogDescription>
						{t(`userAdmin.${actionKey}Description`, { username: account.username })}
					</DialogDescription>
				</DialogHeader>
				<form onSubmit={submit} className="grid gap-4">
					{isReset && (
						<>
							<div className="grid gap-2">
								<Label htmlFor="admin-new-password">
									{t('userAdmin.newPassword')}
								</Label>
								<Input
									id="admin-new-password"
									type="password"
									autoComplete="new-password"
									minLength={6}
									maxLength={1024}
									required
									value={password}
									disabled={mutation.isPending}
									onChange={(event) => {
										setPassword(event.target.value);
										setMismatch(false);
									}}
								/>
							</div>
							<div className="grid gap-2">
								<Label htmlFor="admin-confirm-password">
									{t('auth.confirmPassword')}
								</Label>
								<Input
									id="admin-confirm-password"
									type="password"
									autoComplete="new-password"
									minLength={6}
									maxLength={1024}
									required
									value={confirmPassword}
									disabled={mutation.isPending}
									onChange={(event) => {
										setConfirmPassword(event.target.value);
										setMismatch(false);
									}}
								/>
							</div>
						</>
					)}
					{(mismatch || mutation.isError) && (
						<Alert variant="destructive">
							<AlertDescription>
								{t(mismatch ? 'auth.passwordMismatch' : 'userAdmin.updateFailed')}
							</AlertDescription>
						</Alert>
					)}
					<DialogFooter>
						<Button
							type="button"
							variant="outline"
							disabled={mutation.isPending}
							onClick={close}
						>
							{t('common.cancel')}
						</Button>
						<Button
							type="submit"
							variant={!isReset && account.enabled ? 'destructive' : 'default'}
							disabled={mutation.isPending}
						>
							{t(mutation.isPending ? 'common.saving' : `userAdmin.${actionKey}`)}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}

function UserUsageDialog({ account, close }: { account: AuthUser; close: () => void }) {
	const { t } = useTranslation();
	const [days, setDays] = useState<7 | 30>(30);
	const usage = useQuery({
		queryKey: ['admin', 'usage', account.id, days],
		queryFn: () => userAdminApi.usage(account.username, days),
	});
	const columns = [
		['auth.totalTokens', 'total_tokens'],
		['auth.inputTokens', 'input_tokens'],
		['auth.outputTokens', 'output_tokens'],
	] as const;

	return (
		<Dialog open onOpenChange={(open) => !open && close()}>
			<DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
				<DialogHeader className="pr-8">
					<DialogTitle>
						{t('userAdmin.usageTitle', { username: account.username })}
					</DialogTitle>
					<DialogDescription>{t('userAdmin.usageDescription')}</DialogDescription>
				</DialogHeader>
				<div className="flex gap-2" role="group" aria-label={t('userAdmin.usagePeriod')}>
					{([7, 30] as const).map((period) => (
						<Button
							key={period}
							type="button"
							size="sm"
							variant={days === period ? 'secondary' : 'ghost'}
							aria-pressed={days === period}
							onClick={() => setDays(period)}
						>
							{t('userAdmin.lastDays', { count: period })}
						</Button>
					))}
				</div>
				{usage.isPending && <p role="status">{t('common.loading')}</p>}
				{usage.isError && (
					<Alert variant="destructive">
						<AlertDescription>{t('auth.usageLoadFailed')}</AlertDescription>
					</Alert>
				)}
				{usage.data && (
					<>
						<dl className="grid grid-cols-3 gap-2">
							{columns.map(([label, key]) => (
								<div key={key} className="rounded-lg bg-muted/60 p-3">
									<dt className="text-xs text-muted-foreground">{t(label)}</dt>
									<dd className="mt-1 break-all font-mono text-base font-semibold">
										{formatNumber(usage.data[key])}
									</dd>
								</div>
							))}
						</dl>
						{usage.data.daily.length === 0 ? (
							<p className="py-3 text-center text-muted-foreground">
								{t('auth.dailyUsageEmpty')}
							</p>
						) : (
							<div className="max-h-64 overflow-auto rounded-lg border">
								<Table aria-label={t('auth.dailyUsage')}>
									<TableHeader className="bg-muted/50">
										<TableRow>
											<TableHead scope="col">{t('auth.date')}</TableHead>
											{columns.map(([label, key]) => (
												<TableHead
													key={key}
													scope="col"
													className="text-right"
												>
													{t(label)}
												</TableHead>
											))}
										</TableRow>
									</TableHeader>
									<TableBody>
										{usage.data.daily.map((day) => (
											<TableRow key={day.date} className="font-mono">
												<TableCell>{day.date}</TableCell>
												{columns.map(([, key]) => (
													<TableCell key={key} className="text-right">
														{formatNumber(day[key])}
													</TableCell>
												))}
											</TableRow>
										))}
									</TableBody>
								</Table>
							</div>
						)}
					</>
				)}
			</DialogContent>
		</Dialog>
	);
}

export function UserAdminPage() {
	const { t } = useTranslation();
	const [search, setSearch] = useState('');
	const [action, setAction] = useState<AccountAction | null>(null);
	const [usageAccount, setUsageAccount] = useState<AuthUser | null>(null);
	const users = useQuery({ queryKey: usersKey, queryFn: userAdminApi.list });
	const filter = search.trim().toLowerCase();
	const results = users.data?.filter((account) =>
		account.username.toLowerCase().includes(filter),
	);

	return (
		<main className="h-full overflow-auto p-4 sm:p-6">
			<div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
				<h1 className="font-heading text-xl font-semibold">{t('userAdmin.title')}</h1>
				<div className="relative w-full sm:max-w-xs">
					<Search
						aria-hidden="true"
						className="pointer-events-none absolute top-2 left-2 size-4 text-muted-foreground"
					/>
					<Input
						type="search"
						className="pl-8"
						aria-label={t('userAdmin.search')}
						placeholder={t('userAdmin.search')}
						value={search}
						onChange={(event) => setSearch(event.target.value)}
					/>
				</div>
				{users.isPending && <p role="status">{t('common.loading')}</p>}
				{users.isError && (
					<Alert variant="destructive">
						<AlertDescription>{t('userAdmin.loadFailed')}</AlertDescription>
					</Alert>
				)}
				{results && (
					<div className="rounded-xl border bg-card">
						<Table>
							<TableHeader className="bg-muted/50">
								<TableRow>
									<TableHead scope="col" className="pl-4">
										{t('auth.username')}
									</TableHead>
									<TableHead scope="col">{t('userAdmin.role')}</TableHead>
									<TableHead scope="col">{t('userAdmin.status')}</TableHead>
									<TableHead scope="col" className="pr-4 text-right">
										{t('userAdmin.actions')}
									</TableHead>
								</TableRow>
							</TableHeader>
							<TableBody>
								{results.map((account) => (
									<TableRow key={account.id}>
										<TableCell
											className="max-w-52 truncate pl-4 font-medium"
											title={account.username}
										>
											{account.username}
										</TableCell>
										<TableCell>
											{t(
												account.is_admin
													? 'userAdmin.administrator'
													: 'userAdmin.member',
											)}
										</TableCell>
										<TableCell>
											<Badge
												variant={
													account.enabled ? 'secondary' : 'destructive'
												}
											>
												{t(
													account.enabled
														? 'userAdmin.enabled'
														: 'common.disabled',
												)}
											</Badge>
										</TableCell>
										<TableCell className="pr-4">
											<div className="flex justify-end gap-1">
												<Button
													size="sm"
													variant="ghost"
													onClick={() => setUsageAccount(account)}
												>
													{t('userAdmin.viewUsage')}
												</Button>
												<Button
													size="sm"
													variant="ghost"
													onClick={() =>
														setAction({ kind: 'password', account })
													}
												>
													{t('userAdmin.resetPassword')}
												</Button>
												{!account.is_admin && (
													<Button
														size="sm"
														variant="ghost"
														onClick={() =>
															setAction({ kind: 'status', account })
														}
													>
														{t(
															account.enabled
																? 'userAdmin.disable'
																: 'userAdmin.enable',
														)}
													</Button>
												)}
											</div>
										</TableCell>
									</TableRow>
								))}
								{results.length === 0 && (
									<TableRow>
										<TableCell
											colSpan={4}
											className="py-6 text-center text-muted-foreground"
										>
											{t('userAdmin.noResults')}
										</TableCell>
									</TableRow>
								)}
							</TableBody>
						</Table>
					</div>
				)}
			</div>
			{action && <AccountActionDialog action={action} close={() => setAction(null)} />}
			{usageAccount && (
				<UserUsageDialog account={usageAccount} close={() => setUsageAccount(null)} />
			)}
		</main>
	);
}
