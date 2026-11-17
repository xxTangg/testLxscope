import { useCallback, useEffect, useMemo, useState } from 'react';

import { authApi, type AuthUser, type LoginResponse } from '@/api';
import { AUTH_UNAUTHORIZED_EVENT, clearAccessToken, getAccessToken } from '@/api/client';
import { AuthContext, type AuthStatus } from '@/context/auth-context';
import { queryClient } from '@/lib/query-client';

function clearUserState() {
	queryClient.clear();
	localStorage.removeItem('chat_last_agent');
	localStorage.removeItem('chat_last_session');
	localStorage.removeItem('chat_panel_layout');
	sessionStorage.removeItem('force_tour');
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
	const [status, setStatus] = useState<AuthStatus>('loading');
	const [user, setUser] = useState<AuthUser | null>(null);
	const [autoTourPending, setAutoTourPending] = useState(false);
	const clearAutoTour = useCallback(() => setAutoTourPending(false), []);

	const becomeAnonymous = useCallback(() => {
		clearAccessToken();
		clearUserState();
		setUser(null);
		setAutoTourPending(false);
		setStatus('anonymous');
	}, []);

	useEffect(() => {
		const handleUnauthorized = () => becomeAnonymous();
		window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);

		if (!getAccessToken()) {
			setStatus('anonymous');
		} else {
			authApi
				.me()
				.then((currentUser) => {
					setUser(currentUser);
					setStatus('authenticated');
				})
				.catch(() => becomeAnonymous());
		}

		return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
	}, [becomeAnonymous]);

	const finishAuthentication = useCallback(({ user, show_tour }: LoginResponse) => {
		clearUserState();
		setUser(user);
		setAutoTourPending(show_tour === true);
		setStatus('authenticated');
	}, []);

	const login = useCallback(
		async (username: string, password: string) => {
			finishAuthentication(await authApi.login(username, password));
		},
		[finishAuthentication],
	);

	const register = useCallback(
		async (username: string, password: string) => {
			finishAuthentication(await authApi.register(username, password));
		},
		[finishAuthentication],
	);

	const value = useMemo(
		() => ({
			status,
			user,
			autoTourPending,
			clearAutoTour,
			login,
			register,
			logout: becomeAnonymous,
		}),
		[status, user, autoTourPending, clearAutoTour, login, register, becomeAnonymous],
	);

	return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
