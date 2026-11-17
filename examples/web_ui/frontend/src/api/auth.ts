import { client, setAccessToken } from './client';

export interface AuthUser {
	id: string;
	username: string;
	is_admin: boolean;
	enabled: boolean;
}

export interface LoginResponse {
	access_token: string;
	user: AuthUser;
	show_tour: boolean;
}

export interface DailyTokenUsage {
	date: string;
	input_tokens: number;
	output_tokens: number;
	cache_input_tokens: number;
	cache_creation_input_tokens: number;
	total_tokens: number;
	message_count: number;
	session_count: number;
}

export interface TokenUsage {
	input_tokens: number;
	output_tokens: number;
	cache_input_tokens: number;
	cache_creation_input_tokens: number;
	total_tokens: number;
	message_count: number;
	session_count: number;
	daily: DailyTokenUsage[];
}

async function authenticate(
	path: '/auth/login' | '/auth/register',
	username: string,
	password: string,
) {
	const response = await client.post<LoginResponse>(path, { username, password }, undefined, {
		authenticated: false,
		silent: true,
	});
	setAccessToken(response.access_token);
	return response;
}

export const authApi = {
	login: (username: string, password: string) => authenticate('/auth/login', username, password),
	register: (username: string, password: string) =>
		authenticate('/auth/register', username, password),
	me: () => client.get<AuthUser>('/auth/me', undefined, { silent: true }),
	usage: () => client.get<TokenUsage>('/auth/usage', undefined, { silent: true }),
};

export const userAdminApi = {
	list: () => client.get<AuthUser[]>('/admin/users', undefined, { silent: true }),
	resetPassword: (username: string, password: string) =>
		client.patch<AuthUser>('/admin/users/password', { password }, { username }, { silent: true }),
	setStatus: (username: string, enabled: boolean) =>
		client.patch<AuthUser>('/admin/users/status', { enabled }, { username }, { silent: true }),
	usage: (username: string, days: 7 | 30) =>
		client.get<TokenUsage>('/admin/users/usage', { username, days: String(days) }, { silent: true }),
};
