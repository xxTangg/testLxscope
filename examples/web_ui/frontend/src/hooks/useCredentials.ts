import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback } from 'react';

import { credentialApi } from '../api';
import type { CreateCredentialRequest, UpdateCredentialRequest } from '../api';
import { AVAILABLE_MODELS_KEY } from './useAvailableModels';
import { AVAILABLE_REALTIME_MODELS_KEY } from './useAvailableRealtimeModels';

const CREDENTIALS_KEY = ['credentials'];

/** Share credential records across the management page and all credential dialogs. */
export function useCredentials() {
	const queryClient = useQueryClient();
	const query = useQuery({
		queryKey: CREDENTIALS_KEY,
		queryFn: async () => (await credentialApi.list()).credentials,
	});
	const refresh = useCallback(async () => {
		await Promise.all([
			queryClient.invalidateQueries({ queryKey: CREDENTIALS_KEY }),
			queryClient.invalidateQueries({ queryKey: AVAILABLE_MODELS_KEY }),
			queryClient.invalidateQueries({ queryKey: AVAILABLE_REALTIME_MODELS_KEY }),
		]);
	}, [queryClient]);

	const create = useCallback(
		async (body: CreateCredentialRequest) => {
			const result = await credentialApi.create(body);
			await refresh();
			return result;
		},
		[refresh],
	);

	const update = useCallback(
		async (id: string, body: UpdateCredentialRequest) => {
			const result = await credentialApi.update(id, body);
			await refresh();
			return result;
		},
		[refresh],
	);

	const remove = useCallback(
		async (id: string) => {
			await credentialApi.delete(id);
			await refresh();
		},
		[refresh],
	);

	const setEnabled = useCallback(
		async (id: string, enabled: boolean) => {
			await credentialApi.setEnabled(id, enabled);
			await refresh();
		},
		[refresh],
	);

	return {
		credentials: query.data ?? [],
		loading: query.isPending,
		error: query.error,
		refetch: query.refetch,
		create,
		update,
		remove,
		setEnabled,
	};
}
