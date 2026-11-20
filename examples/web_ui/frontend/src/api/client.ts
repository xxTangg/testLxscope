import { toast } from 'sonner';

import { formatApiErrorMessage } from '../lib/api-error.ts';

const API_BASE_PATH = '/api/';

// Older versions saved a direct backend URL (usually :8001). Drop it once so
// existing browsers move to the same-origin API proxy without manual setup.
if (typeof window !== 'undefined') localStorage.removeItem('server_url');

export const getBaseUrl = () => `${window.location.origin}${API_BASE_PATH}`;

export const buildApiUrl = (path: string) => new URL(path.replace(/^\/+/, ''), getBaseUrl());
const ACCESS_TOKEN_KEY = 'agentscope_access_token';

export const getAccessToken = () => localStorage.getItem(ACCESS_TOKEN_KEY);
export const setAccessToken = (token: string) => localStorage.setItem(ACCESS_TOKEN_KEY, token);
export const clearAccessToken = () => localStorage.removeItem(ACCESS_TOKEN_KEY);

export const AUTH_UNAUTHORIZED_EVENT = 'agentscope:auth-unauthorized';

/**
 * Structured error thrown for non-2xx HTTP responses.
 * `message` is localized for display. `detail` contains the original response.
 */
export class ApiError extends Error {
	readonly status: number;
	readonly detail: string;

	constructor(status: number, detail: string) {
		super(formatApiErrorMessage(status, detail));
		this.name = 'ApiError';
		this.status = status;
		this.detail = detail;
	}
}

interface RequestOptions {
	method?: string;
	body?: unknown;
	params?: Record<string, string>;
	/** When true, suppresses the automatic error toast. Useful when the caller shows its own inline error UI. */
	silent?: boolean;
	signal?: AbortSignal;
	/** Public endpoints such as login opt out of the bearer token. */
	authenticated?: boolean;
	/** Gives up after this many ms and reports {@link TIMEOUT_STATUS}. Off by default — a streaming chat is meant to stay open. */
	timeoutMs?: number;
}

/** Reported when `timeoutMs` elapses. Real 408s come from a server, so either way the request did not complete in time. */
export const TIMEOUT_STATUS = 408;

function buildHeaders(hasBody: boolean, authenticated: boolean): Record<string, string> {
	const headers: Record<string, string> = {};
	const token = getAccessToken();
	if (authenticated && token) headers.Authorization = `Bearer ${token}`;
	if (hasBody) headers['Content-Type'] = 'application/json';
	return headers;
}

/** Parse the response body and extract the `detail` field if the backend returned JSON. */
async function extractErrorDetail(res: Response): Promise<string> {
	const text = await res.text();
	try {
		const json = JSON.parse(text) as { detail?: unknown };
		if (typeof json.detail === 'string') return json.detail;
		if (json.detail !== undefined) return JSON.stringify(json.detail);
	} catch {
		// not JSON – fall through
	}
	return text || res.statusText;
}

async function request<T>(
	path: string,
	options: RequestOptions,
	read: (response: Response) => T | Promise<T>,
): Promise<T> {
	const {
		method = 'GET',
		body,
		params,
		signal,
		silent = false,
		authenticated = true,
		timeoutMs,
	} = options;
	const url = buildApiUrl(path);
	if (params) {
		Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
	}

	// Chromium 102 supports AbortController but lacks the AbortSignal helpers.
	const controller = timeoutMs ? new AbortController() : undefined;
	const abortFromCaller = () => controller?.abort(signal?.reason);
	if (controller && signal) {
		if (signal.aborted) abortFromCaller();
		else signal.addEventListener('abort', abortFromCaller, { once: true });
	}
	const requestSignal = controller?.signal ?? signal;
	const timeoutReason = new DOMException('The request timed out.', 'TimeoutError');
	const timer = controller && setTimeout(() => controller.abort(timeoutReason), timeoutMs);
	let receivedResponse = false;
	try {
		const res = await fetch(url.toString(), {
			method,
			headers: buildHeaders(body !== undefined, authenticated),
			body: body ? JSON.stringify(body) : undefined,
			signal: requestSignal,
		});
		receivedResponse = true;
		if (!res.ok) {
			const detail = await extractErrorDetail(res);
			const error = new ApiError(res.status, detail);
			if (res.status === 401 && authenticated && getAccessToken()) {
				window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
			}
			if (!silent) toast.error(error.message);
			throw error;
		}
		return await read(res);
	} catch (e) {
		const timedOut = requestSignal?.reason === timeoutReason;
		if (!timedOut && (requestSignal?.aborted || receivedResponse)) throw e;
		const error = timedOut
			? new ApiError(TIMEOUT_STATUS, 'The server took too long to respond.')
			: new ApiError(
					0,
					'Cannot reach the server. Check the server address and your network.',
				);
		if (!silent) toast.error(error.message);
		throw error;
	} finally {
		clearTimeout(timer);
		if (controller) signal?.removeEventListener('abort', abortFromCaller);
	}
}

function requestJson<T>(path: string, options: RequestOptions): Promise<T> {
	return request(path, options, (res) =>
		res.status === 204 ? (undefined as T) : (res.json() as Promise<T>),
	);
}

export const client = {
	get: <T>(
		path: string,
		params?: Record<string, string>,
		options?: {
			silent?: boolean;
			signal?: AbortSignal;
			authenticated?: boolean;
			timeoutMs?: number;
		},
	) => requestJson<T>(path, { method: 'GET', params, ...options }),
	post: <T>(
		path: string,
		body?: unknown,
		params?: Record<string, string>,
		options?: {
			silent?: boolean;
			authenticated?: boolean;
			signal?: AbortSignal;
			timeoutMs?: number;
		},
	) => requestJson<T>(path, { method: 'POST', body, params, ...options }),
	patch: <T>(
		path: string,
		body?: unknown,
		params?: Record<string, string>,
		options?: { silent?: boolean },
	) => requestJson<T>(path, { method: 'PATCH', body, params, silent: options?.silent }),
	delete: <T = void>(path: string, params?: Record<string, string>) =>
		requestJson<T>(path, { method: 'DELETE', params }),
	blob: (path: string, options: RequestOptions = {}) =>
		request(path, options, (res) => res.blob()),
	stream: (path: string, options: RequestOptions = {}) => request(path, options, (res) => res),
};
