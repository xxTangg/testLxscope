import assert from 'node:assert/strict';
import { readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { after, before, describe, test } from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';

// Run against a built UI with the deployment image's browser runtime:
// TEST_WEB_UI_URL=http://web-ui node --test chatAccountNavigation.test.mjs
const baseUrl = process.env.TEST_WEB_UI_URL;
const ownAgent = {
	id: 'own-agent',
	user_id: 'bob',
	editable: true,
	data: { name: '通用智能体', system_prompt: '', chat_config: {} },
};
const session = (id) => ({
	session: {
		id,
		agent_id: ownAgent.id,
		user_id: 'bob',
		created_at: '2026-11-16T00:00:00Z',
		updated_at: '2026-11-16T00:00:00Z',
		origin: { type: 'user' },
		config: {},
		state: {},
	},
	is_running: false,
	team: null,
});

describe('Chat selection after authentication', { skip: !baseUrl }, () => {
	let browser;
	before(async () => {
		const require = createRequire(import.meta.url);
		const { chromium } = require(
			process.env.PLAYWRIGHT_MODULE_PATH ??
				'/usr/local/lib/node_modules/@playwright/mcp/node_modules/playwright',
		);
		const root = '/ms-playwright';
		const folder = readdirSync(root).find((name) => name.startsWith('chromium-'));
		const platform = readdirSync(`${root}/${folder}`).find((name) =>
			name.startsWith('chrome-linux'),
		);
		browser = await chromium.launch({
			headless: true,
			executablePath: `${root}/${folder}/${platform}/chrome`,
			args: ['--no-sandbox'],
		});
	});
	after(async () => browser?.close());

	async function open(t, options = {}) {
		const { agents = [ownAgent], path = '/chat', authenticated = true } = options;
		const sessions = [...(options.sessions ?? [])];
		const context = await browser.newContext();
		t.after(() => context.close());
		await context.addInitScript(
			({ authenticated, rememberedAgent, rememberedSession }) => {
				if (sessionStorage.getItem('fixture_initialized')) return;
				sessionStorage.setItem('fixture_initialized', '1');
				localStorage.setItem('i18nextLng', 'zh');
				if (authenticated) localStorage.setItem('agentscope_access_token', 'synthetic-bob');
				else {
					localStorage.setItem('chat_panel_layout', '[["team"]]');
					sessionStorage.setItem('force_tour', '1');
				}
				if (rememberedAgent) localStorage.setItem('chat_last_agent', rememberedAgent);
				if (rememberedSession) localStorage.setItem('chat_last_session', rememberedSession);
			},
			{ authenticated, ...options },
		);
		const page = await context.newPage();
		page.setDefaultTimeout(10_000);
		const requests = [];
		const errors = [];
		page.on('pageerror', (error) => errors.push(error.message));
		await page.route('**/api/**', async (route) => {
			const request = route.request();
			const url = new URL(request.url());
			const path = url.pathname.slice('/api'.length);
			const body = request.postData() ? request.postDataJSON() : null;
			const entry = {
				path,
				agent: url.searchParams.get('agent_id'),
				body,
				authorization: request.headers().authorization,
			};
			requests.push(entry);
			const reply = (data, status = 200) =>
				route.fulfill({
					status,
					contentType: 'application/json',
					body: JSON.stringify(data),
				});
			if (entry.agent && entry.agent !== ownAgent.id) {
				return reply({ detail: 'Agent not found.' }, 404);
			}
			const user = { id: 'bob', username: 'bob', is_admin: false, enabled: true };
			if (path === '/auth/login' || path === '/auth/register') {
				return reply({
					access_token: 'synthetic-bob',
					user,
					show_tour: path === '/auth/register',
				});
			}
			if (path === '/auth/me') return reply(user);
			if (path === '/agent/') {
				await delay(200); // Prove that no raw URL ID is used while the list loads.
				return options.agentFailure
					? reply({ detail: 'Synthetic agent service failure.' }, 503)
					: reply({ agents, total: agents.length });
			}
			if (path === '/agent/schema/v2') return reply({ schema: { properties: {} } });
			if (path === '/credential/') return reply({ credentials: [], total: 0 });
			if (path === '/chat/attachments/supported_content_types') {
				return reply({ media_types: [], extensions: [] });
			}
			if (path === '/sessions/') {
				if (request.method() === 'POST') {
					assert.equal(body.agent_id, ownAgent.id);
					sessions.unshift(session('new-session'));
					return reply({ session_id: 'new-session' });
				}
				return reply({ sessions, total: sessions.length });
			}
			if (path.startsWith('/sessions/')) {
				const id = path.split('/')[2];
				if (!sessions.some((view) => view.session.id === id)) {
					return reply({ detail: 'Session not found.' }, 404);
				}
				if (path.endsWith('/messages')) {
					return reply({
						messages: [],
						is_running: false,
						has_more: false,
						event_cursor: null,
					});
				}
				if (path.endsWith('/stream')) {
					return route.fulfill({
						status: 200,
						contentType: 'text/event-stream',
						body: '',
					});
				}
			}
			if (path === '/workspace/mcp' || path === '/workspace/skill') return reply([]);
			if (path === '/workspace/status') return reply({ cwd: '~', workdir: '~', git: null });
			if (path === '/knowledge_bases/') return reply({ knowledge_bases: [], total: 0 });
			if (path === '/knowledge_bases/middleware/parameters_schema') {
				return reply({ parameter_schema: { properties: {} } });
			}
			return reply({ detail: `Unmocked API route: ${path}` }, 503);
		});
		await page.goto(baseUrl + path);
		return { page, requests, errors };
	}

	async function assertHealthy({ page, requests, errors }) {
		await page.waitForTimeout(100);
		assert.deepEqual(errors, []);
		assert.equal(await page.locator('[data-sonner-toast][data-type="error"]').count(), 0);
		assert.equal(
			requests.some((r) => r.agent && r.agent !== ownAgent.id),
			false,
		);
		assert.equal(
			requests.some((r) => r.path.includes('/foreign-session/')),
			false,
		);
	}

	test('an unavailable agent falls back to an owned agent before requesting sessions', async (t) => {
		const fixture = await open(t, { path: '/chat/foreign-agent/foreign-session' });
		await fixture.page.waitForURL(baseUrl + '/chat/own-agent');
		assert.equal(
			await fixture.page.getByText('该智能体不可用，已返回当前账号的聊天页面。').count(),
			1,
		);
		await assertHealthy(fixture);
	});

	test('an empty account drops the stale URL and disables new-session actions', async (t) => {
		const fixture = await open(t, {
			path: '/chat/foreign-agent/foreign-session',
			agents: [],
			rememberedAgent: 'foreign-agent',
			rememberedSession: 'foreign-session',
		});
		await fixture.page.waitForURL(baseUrl + '/chat');
		assert.equal(await fixture.page.locator('#tour-create-session').isDisabled(), true);
		assert.equal(
			await fixture.page.evaluate(() => localStorage.getItem('chat_last_agent')),
			null,
		);
		assert.equal(
			fixture.requests.some((r) => r.path === '/sessions/'),
			false,
		);
		await assertHealthy(fixture);
	});

	test('login from the previous account route recovers silently and clears old selections', async (t) => {
		const fixture = await open(t, {
			path: '/chat/foreign-agent/foreign-session',
			authenticated: false,
			rememberedAgent: 'foreign-agent',
			rememberedSession: 'foreign-session',
		});
		await fixture.page.waitForURL(baseUrl + '/login');
		await fixture.page.locator('#login-username').fill('bob');
		await fixture.page.locator('#login-password').fill('synthetic-password');
		await fixture.page.locator('button[type="submit"]').click();
		await fixture.page.waitForURL(baseUrl + '/chat/own-agent');
		assert.equal(await fixture.page.locator('[data-sonner-toast]').count(), 0);
		assert.deepEqual(
			await fixture.page.evaluate(() => [
				localStorage.getItem('chat_last_agent'),
				localStorage.getItem('chat_last_session'),
				localStorage.getItem('agentscope_access_token'),
			]),
			[null, null, 'synthetic-bob'],
		);
		assert.deepEqual(
			await fixture.page.evaluate(() => [
				localStorage.getItem('chat_panel_layout'),
				sessionStorage.getItem('force_tour'),
			]),
			['[]', null],
		);
		assert.equal(
			fixture.requests
				.filter((r) => r.path === '/agent/')
				.every((r) => r.authorization === 'Bearer synthetic-bob'),
			true,
		);
		await assertHealthy(fixture);
	});

	test('registration from a stale route opens the new account default agent silently', async (t) => {
		const fixture = await open(t, {
			path: '/chat/foreign-agent/foreign-session',
			authenticated: false,
			rememberedAgent: 'foreign-agent',
			rememberedSession: 'foreign-session',
		});
		await fixture.page.waitForURL(baseUrl + '/login');
		await fixture.page.locator('form button[type="button"]').last().click();
		await fixture.page.locator('#login-username').fill('bob');
		await fixture.page.locator('#login-password').fill('synthetic-password');
		await fixture.page.locator('#login-confirm-password').fill('synthetic-password');
		await fixture.page.locator('button[type="submit"]').click();
		await fixture.page.waitForURL(baseUrl + '/chat/own-agent');
		await fixture.page.waitForFunction(
			() => !document.getElementById('tour-create-session')?.disabled,
		);
		assert.equal(await fixture.page.locator('[data-sonner-toast]').count(), 0);
		assert.equal(
			await fixture.page.evaluate(() => localStorage.getItem('chat_last_agent')),
			null,
		);
		await assertHealthy(fixture);
	});

	test('a valid bookmarked session still loads and becomes the remembered selection', async (t) => {
		const fixture = await open(t, {
			path: '/chat/own-agent/own-session',
			sessions: [session('own-session')],
		});
		await fixture.page.waitForFunction(
			() => localStorage.getItem('chat_last_session') === 'own-session',
		);
		assert.equal(new URL(fixture.page.url()).pathname, '/chat/own-agent/own-session');
		await assertHealthy(fixture);
		assert.equal(
			fixture.requests.some((r) => r.path.endsWith('/own-session/messages')),
			true,
		);
	});

	test('a stale session is replaced with an available session without reading its messages', async (t) => {
		const fixture = await open(t, {
			path: '/chat/own-agent/foreign-session',
			sessions: [session('own-session')],
		});
		await fixture.page.waitForURL(baseUrl + '/chat/own-agent/own-session');
		await assertHealthy(fixture);
	});

	test('an agent with no sessions drops an invalid session URL without requesting its messages', async (t) => {
		const fixture = await open(t, { path: '/chat/own-agent/foreign-session' });
		await fixture.page.waitForURL(baseUrl + '/chat/own-agent');
		await assertHealthy(fixture);
	});

	test('restoring a valid remembered session and creating a new session both work', async (t) => {
		const fixture = await open(t, {
			sessions: [session('first-session'), session('own-session')],
			rememberedAgent: 'own-agent',
			rememberedSession: 'own-session',
		});
		await fixture.page.waitForURL(baseUrl + '/chat/own-agent/own-session');
		await fixture.page.locator('#tour-create-session').click();
		await fixture.page.waitForURL(baseUrl + '/chat/own-agent/new-session');
		await assertHealthy(fixture);
		assert.equal(
			fixture.requests.some((r) => r.body?.agent_id === ownAgent.id),
			true,
		);
	});

	test('a failed agent-list request keeps the route and still reports a real error', async (t) => {
		const fixture = await open(t, { path: '/chat/own-agent', agentFailure: true });
		await fixture.page.getByText('Synthetic agent service failure.').first().waitFor();
		assert.equal(new URL(fixture.page.url()).pathname, '/chat/own-agent');
		assert.equal(
			fixture.requests.some((r) => r.path === '/sessions/'),
			false,
		);
		assert.deepEqual(fixture.errors, []);
	});

	test('registration starts the tour once even when the user leaves it open', async (t) => {
		const fixture = await open(t, { authenticated: false });
		const { page } = fixture;
		const guide = page.getByText('你的通用智能体', { exact: true });
		await page.waitForURL(baseUrl + '/login');
		await page.locator('form button[type="button"]').last().click();
		await page.locator('#login-username').fill('bob');
		await page.locator('#login-password').fill('synthetic-password');
		await page.locator('#login-confirm-password').fill('synthetic-password');
		await page.locator('button[type="submit"]').click();
		await page.waitForURL(baseUrl + '/chat/own-agent');
		await guide.waitFor();

		await page.reload();
		await page.locator('#tour-create-session:enabled').waitFor();
		await page.waitForTimeout(600);
		assert.equal(await guide.count(), 0);

		await page.getByRole('button', { name: '账号中心', exact: true }).click();
		await page.getByRole('menuitem', { name: '退出登录', exact: true }).click();
		await page.waitForURL(baseUrl + '/login');
		await page.locator('#login-username').fill('bob');
		await page.locator('#login-password').fill('synthetic-password');
		await page.locator('button[type="submit"]').click();
		await page.waitForURL(baseUrl + '/chat/own-agent');
		await page.locator('#tour-create-session:enabled').waitFor();
		await page.waitForTimeout(600);
		assert.equal(await guide.count(), 0);
		await assertHealthy(fixture);
	});

	test('an existing account can open the guide manually and advance after creating a session', async (t) => {
		const fixture = await open(t);
		await fixture.page.waitForURL(baseUrl + '/chat/own-agent');
		await fixture.page.getByRole('button', { name: '新手引导', exact: true }).click();
		await fixture.page.getByText('你的通用智能体', { exact: true }).waitFor();
		await fixture.page.getByRole('button', { name: '下一步', exact: true }).click();
		await fixture.page.getByText('创建会话', { exact: true }).waitFor();
		await fixture.page.locator('#tour-create-session').click();
		await fixture.page.waitForURL(baseUrl + '/chat/own-agent/new-session');
		await fixture.page
			.locator('[data-name="onborda-card"]')
			.getByText('选择模型', { exact: true })
			.waitFor();
		await assertHealthy(fixture);
	});
});
