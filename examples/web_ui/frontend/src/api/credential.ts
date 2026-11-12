import { client } from './client';
import type {
	CreateCredentialRequest,
	CreateCredentialResponse,
	CredentialListResponse,
	CredentialView,
	CredentialSchemasResponse,
	UpdateCredentialRequest,
} from './types';

const LONGXIN_AI_CREDENTIAL_TYPE = 'newapi_credential';
export const LONGXIN_AI_LABEL = 'longxin_AI';

export const credentialApi = {
	list: async (): Promise<CredentialListResponse> => {
		const { credentials } = await client.get<CredentialListResponse>('/credential/');
		const visible = credentials.filter((record) => record.data.type === LONGXIN_AI_CREDENTIAL_TYPE);
		return { credentials: visible, total: visible.length };
	},

	schemas: async (): Promise<CredentialSchemasResponse> => {
		const { schemas } = await client.get<CredentialSchemasResponse>('/credential/schemas');
		return {
			schemas: schemas
				.filter((schema) => schema.properties.type?.const === LONGXIN_AI_CREDENTIAL_TYPE)
				.map((schema) => ({ ...schema, title: LONGXIN_AI_LABEL })),
		};
	},

	create: (body: CreateCredentialRequest) =>
		client.post<CreateCredentialResponse>('/credential/', body),

	update: (credentialId: string, body: UpdateCredentialRequest) =>
		client.patch<CredentialView>(`/credential/${credentialId}`, body),

	delete: (credentialId: string) => client.delete(`/credential/${credentialId}`),
};
