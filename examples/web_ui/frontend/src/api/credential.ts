import { client } from './client';
import type {
	CreateCredentialRequest,
	CreateCredentialResponse,
	CredentialListResponse,
	CredentialView,
	CredentialSchemasResponse,
	UpdateCredentialRequest,
} from './types';

export const NEW_API_CREDENTIAL_TYPE = 'newapi_credential';
export const LONGXIN_AI_LABEL = 'longxin_AI';

export interface NewApiModelCandidate {
	id: string;
	capabilities: Array<'chat' | 'embedding'>;
	capabilities_known: boolean;
}

export const credentialApi = {
	list: async (): Promise<CredentialListResponse> => {
		return client.get<CredentialListResponse>('/credential/');
	},

	schemas: async (): Promise<CredentialSchemasResponse> => {
		const { schemas } = await client.get<CredentialSchemasResponse>('/credential/schemas');
		return {
			schemas: schemas.map((schema) => ({ ...schema, title: LONGXIN_AI_LABEL })),
		};
	},

	create: (body: CreateCredentialRequest) =>
		client.post<CreateCredentialResponse>('/credential/', body),

	update: (credentialId: string, body: UpdateCredentialRequest) =>
		client.patch<CredentialView>(`/credential/${credentialId}`, body),

	setEnabled: (credentialId: string, enabled: boolean) =>
		client.patch<CredentialView>(`/credential/${credentialId}/enabled`, { enabled }),

	checkModel: (credentialId: string, model: string, signal: AbortSignal) =>
		client.post<{ model: string; status: 'passed' | 'failed'; detail: string }>(
			`/credential/${credentialId}/check-model`,
			{ model },
			undefined,
			{ signal, silent: true, timeoutMs: 15_000 },
		),

	delete: (credentialId: string) => client.delete(`/credential/${credentialId}`),
};
