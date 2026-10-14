import { client } from './client';
import type { ChatModelConfig, PermissionMode, RecordBase } from './types';

export type SOPPhase = 'pending' | 'running' | 'awaiting' | 'completed' | 'failed';

export interface SOPAgentRef {
	agent_id: string;
	session_key: string;
}

export type SOPVerifier =
	| { type: 'human'; question: string }
	| { type: 'agent'; agent: SOPAgentRef; criteria: string }
	| null;

export interface SOPStep {
	version: 'v1';
	subject: string;
	description: string;
	executor: SOPAgentRef;
	verifier: SOPVerifier;
	max_attempts: number;
}

export interface SOPSessionSettings {
	chat_model_config: ChatModelConfig;
	fallback_chat_model_config?: ChatModelConfig | null;
	permission_mode?: PermissionMode;
}

export interface SOPData {
	name: string;
	description: string;
	steps: SOPStep[];
	workspace_grain: 'run' | 'per_session_key';
	session_settings: Record<string, SOPSessionSettings>;
}

export interface SOPRecord extends RecordBase {
	user_id: string;
	data: SOPData;
}

export interface SOPStepRunState {
	phase: SOPPhase;
	given: unknown[];
	submission: Array<{ type: string; text?: string; [key: string]: unknown }> | null;
	verifications: Array<{ passed: boolean; message: string; verifier: string; created_at: string }>;
}

export interface SOPRunRecord extends RecordBase {
	user_id: string;
	sop_id: string;
	definition: SOPData;
	sessions: Record<string, string>;
	state: { id: string; phase: SOPPhase; inputs: unknown[]; steps: SOPStepRunState[]; created_at: string };
}

export const sopApi = {
	list: () => client.get<{ sops: SOPRecord[]; total: number }>('/sop/'),
	create: (data: SOPData) => client.post<{ sop_id: string }>('/sop/', { data }),
	update: (id: string, data: SOPData) => client.patch<SOPRecord>(`/sop/${id}`, { data }),
	delete: (id: string) => client.delete(`/sop/${id}`),
	listRuns: (sopId: string) =>
		client.get<{ runs: SOPRunRecord[]; total: number }>('/sop/runs', { sop_id: sopId }),
	startRun: (sopId: string, input: string) =>
		client.post<SOPRunRecord>(`/sop/${sopId}/runs`, {
			inputs: input.trim()
				? [{ name: 'user', role: 'user', content: [{ type: 'text', text: input.trim() }] }]
				: [],
		}),
	verdict: (runId: string, stepIndex: number, passed: boolean, message: string) =>
		client.post<SOPRunRecord>(`/sop/runs/${runId}/verdict`, {
			step_index: stepIndex,
			passed,
			message,
		}),
	deleteRun: (runId: string) => client.delete(`/sop/runs/${runId}`),
};
