import { client } from './client';
import type { HealthResponse } from './types';

/** The probe is I/O-free on the server, so anything this slow is a stalled backend. */
const HEALTH_TIMEOUT_MS = 10_000;

export const healthApi = {
	/** Probe the backend through the same-origin reverse proxy. */
	check: () =>
		client.get<HealthResponse>('/health', undefined, {
			silent: true,
			timeoutMs: HEALTH_TIMEOUT_MS,
		}),
};
