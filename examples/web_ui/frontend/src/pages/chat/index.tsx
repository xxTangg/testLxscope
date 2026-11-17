import {
	BotMessageSquare,
	Cable,
	CalendarClock,
	Ellipsis,
	type LucideIcon,
	MessageSquareDashed,
	Pencil,
	Plus,
	Settings2,
	Trash2,
	Users,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';

import { ChatViewport } from './ChatViewport';
import type { SessionRecord, SessionSourceKind } from '@/api';
import { AgentDialog } from '@/components/dialog/AgentDialog';
import { DeleteDialog } from '@/components/dialog/DeleteDialog';
import { EditAgentDialog } from '@/components/dialog/EditAgentDialog';
import { RenameSessionDialog } from '@/components/dialog/RenameSessionDialog';
import { AgentSelect } from '@/components/select/AgentSelect';
import { ChatTourController } from '@/components/tour/ChatTourController';
import { Button } from '@/components/ui/button';
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
	Empty,
	EmptyHeader,
	EmptyTitle,
	EmptyDescription,
	EmptyMedia,
} from '@/components/ui/empty';
import {
	Sidebar,
	SidebarContent,
	SidebarGroup,
	SidebarGroupContent,
	SidebarGroupLabel,
	SidebarMenu,
	SidebarMenuAction,
	SidebarMenuBadge,
	SidebarMenuButton,
	SidebarMenuItem,
	SidebarProvider,
	useSidebar,
} from '@/components/ui/sidebar';
import { AudioProvider } from '@/context/AudioContext';
import { useAgents } from '@/hooks/useAgents';
import { useSessions } from '@/hooks/useSessions';
import { useTranslation } from '@/i18n/useI18n.ts';
import { formatSessionTime, isSessionToday, sessionDisplayName } from '@/utils/sessionTime';

/**
 * The chat page's outer shell. Responsibilities split cleanly:
 *
 * - **This component** owns *which* `(agent, session)` is being
 *   viewed. The URL is the single source of truth: every selection
 *   (agent dropdown, session row, team member, new session) is a
 *   ``navigate(...)`` call. State is derived from ``useParams``,
 *   never duplicated in React state. Renders the main left sidebar
 *   (agent picker + session list + create/rename/delete actions) and
 *   computes the ``effective`` ids to feed the chat viewport.
 * - **`ChatViewport`** owns *what* to render for that pair: messages,
 *   model selector, permission mode, workspace drawer, team sidebar.
 *
 * Splitting along this seam means switching between the leader's
 * session and a focused team member is just a prop change for the
 * viewport — the leader's session list stays anchored in this outer
 * sidebar. Driving everything off URL also gets us browser back /
 * forward, shareable links, and refresh-preserving state for free.
 *
 * @returns The chat page JSX.
 */
// Icon per session origin, shown only when a sidebar mixes sources.
const SOURCE_ICON: Record<SessionSourceKind, LucideIcon> = {
	user: BotMessageSquare,
	schedule: CalendarClock,
	channel: Cable,
	team: Users,
};

/** localStorage keys holding the last (agent, session) the user viewed. */
const LAST_AGENT_KEY = 'chat_last_agent';
const LAST_SESSION_KEY = 'chat_last_session';

const ChatPageInner = () => {
	const navigate = useNavigate();
	const location = useLocation();
	const afterAuthentication = Boolean(
		(location.state as { afterAuthentication?: boolean } | null)?.afterAuthentication,
	);
	const [now, setNow] = useState(() => new Date());

	useEffect(() => {
		// Regroup sessions after Beijing midnight, including tabs reopened later.
		const refreshDate = () => setNow(new Date());
		const timer = window.setInterval(refreshDate, 60_000);
		document.addEventListener('visibilitychange', refreshDate);
		return () => {
			window.clearInterval(timer);
			document.removeEventListener('visibilitychange', refreshDate);
		};
	}, []);
	const {
		agentId: urlAgentId,
		sessionId: urlSessionId,
		memberId: urlMemberId,
	} = useParams<{
		agentId?: string;
		sessionId?: string;
		memberId?: string;
	}>();
	const { t } = useTranslation();
	const {
		agents,
		loading: agentsLoading,
		error: agentsError,
		refetch: refetchAgents,
		remove: removeAgent,
	} = useAgents();
	const selectedAgent = agents.find((a) => a.id === urlAgentId) ?? null;
	const selectedAgentId = selectedAgent?.id ?? null;
	const {
		sessions,
		loading: sessionsLoading,
		error: sessionsError,
		refetch: refetchSessions,
		create: createSession,
		update: updateSession,
		remove: removeSession,
	} = useSessions(selectedAgentId);

	const { isMobile, setOpen, setOpenMobile } = useSidebar();
	const ensureSidebarOpen = useCallback(() => {
		setOpen(true);
		setOpenMobile(true);
	}, [setOpen, setOpenMobile]);
	const [editOpen, setEditOpen] = useState(false);
	const [deleteOpen, setDeleteOpen] = useState(false);
	const [renameOpen, setRenameOpen] = useState(false);
	const [renameSession, setRenameSession] = useState<SessionRecord | null>(null);
	const [deleteSessionOpen, setDeleteSessionOpen] = useState(false);
	const [sessionToDelete, setSessionToDelete] = useState<SessionRecord | null>(null);

	const currentView = sessions.find((v) => v.session.id === urlSessionId) ?? null;
	const selectedSessionId = currentView?.session.id ?? null;
	// Show a per-origin icon only when sessions actually mix sources —
	// a uniform list needs no disambiguation.
	const showSourceIcons = new Set(sessions.map((v) => v.session.origin.type)).size > 1;

	// "Inner focus" — when the URL carries a third `:memberId` segment
	// the user is drilling into a team member's chat. The main sidebar
	// stays anchored on the outer (leader) session; only the chat
	// viewport follows this inner focus. When `urlMemberId` is
	// undefined or doesn't resolve to a known team member, the inner
	// focus collapses back to the outer (leader) session.
	const focusedMember = urlMemberId
		? (currentView?.team?.members.find((m) => m.agent.id === urlMemberId) ?? null)
		: null;
	const effectiveAgentId =
		focusedMember && focusedMember.session_id ? focusedMember.agent.id : selectedAgentId;
	const effectiveSessionId =
		focusedMember && focusedMember.session_id ? focusedMember.session_id : selectedSessionId;

	// Remember where the user was, so coming back to a bare `/chat` —
	// from another page, or from a new tab — reopens it instead of
	// making them pick the same pair again.
	useEffect(() => {
		if (!selectedAgentId || !selectedSessionId) return;
		localStorage.setItem(LAST_AGENT_KEY, selectedAgentId);
		localStorage.setItem(LAST_SESSION_KEY, selectedSessionId);
	}, [selectedAgentId, selectedSessionId]);

	// Validate URL and saved selections against this account's visible list
	// before any session or workspace request can use them.
	useEffect(() => {
		if (agentsLoading || agentsError) return;
		const remembered = localStorage.getItem(LAST_AGENT_KEY);
		const rememberedAgent = agents.find((a) => a.id === remembered);
		if (remembered && !rememberedAgent) {
			localStorage.removeItem(LAST_AGENT_KEY);
			localStorage.removeItem(LAST_SESSION_KEY);
		}
		if (selectedAgentId) return;
		const agent = rememberedAgent ?? agents[0];
		if (urlAgentId && !afterAuthentication) {
			toast.info(t('chat.agentUnavailable'), { id: 'chat-agent-unavailable' });
		}
		if (urlAgentId || agent) {
			navigate(agent ? `/chat/${agent.id}` : '/chat', { replace: true });
		}
	}, [
		agents,
		agentsLoading,
		agentsError,
		selectedAgentId,
		urlAgentId,
		afterAuthentication,
		navigate,
		t,
	]);

	// Redirect: URL has an agent but no session, or its sessionId no
	// longer exists for this agent → reopen the last session viewed
	// under *this* agent, falling back to the first available one.
	useEffect(() => {
		if (!selectedAgentId || sessionsLoading || sessionsError) return;
		if (sessions.length === 0) {
			if (urlSessionId) navigate(`/chat/${selectedAgentId}`, { replace: true });
			return;
		}
		const matches = urlSessionId && sessions.some((v) => v.session.id === urlSessionId);
		if (matches) return;
		const remembered =
			localStorage.getItem(LAST_AGENT_KEY) === selectedAgentId
				? localStorage.getItem(LAST_SESSION_KEY)
				: null;
		const view = sessions.find((v) => v.session.id === remembered) ?? sessions[0];
		navigate(`/chat/${selectedAgentId}/${view.session.id}`, { replace: true });
	}, [selectedAgentId, urlSessionId, sessions, sessionsLoading, sessionsError, navigate]);

	/**
	 * Create a new session under the currently selected agent and
	 * pre-fill it with the model + fallback the currently open session
	 * is using (so "new chat" inherits whatever the user just had
	 * configured). Falls back to any other session under this agent
	 * when there is no current one — keeps the model choice sticky
	 * across "delete last → create new" instead of dropping back to
	 * whatever ChatViewport's auto-pick happens to land on. Navigates
	 * to the freshly created session.
	 */
	const handleCreateSession = async () => {
		if (!selectedAgentId) return;
		const seedConfig = currentView?.session.config ?? sessions[0]?.session.config;
		const res = await createSession({
			agent_id: selectedAgentId,
			...(seedConfig?.chat_model_config
				? { chat_model_config: seedConfig.chat_model_config }
				: {}),
			...(seedConfig?.fallback_chat_model_config
				? { fallback_chat_model_config: seedConfig.fallback_chat_model_config }
				: {}),
			...(seedConfig?.realtime_model_config
				? { realtime_model_config: seedConfig.realtime_model_config }
				: {}),
		});
		navigate(`/chat/${selectedAgentId}/${res.session_id}`);
	};

	const handleAgentDeleted = async () => {
		navigate('/chat', { replace: true });
		await refetchAgents();
	};

	const handleDeleteSession = async (sessionId: string) => {
		await removeSession(sessionId);
		// If we just removed the session the URL is pointing at, fall
		// back to the parent /chat/:agentId path; the redirect effect
		// will then pick the next available session.
		if (sessionId === urlSessionId && urlAgentId) {
			navigate(`/chat/${urlAgentId}`, { replace: true });
		}
	};

	const requestDeleteSession = (session: SessionRecord) => {
		setSessionToDelete(session);
		setDeleteSessionOpen(true);
	};

	const handleRenameConfirm = async (name: string) => {
		if (!renameSession) return;
		await updateSession(renameSession.id, { name });
	};

	const todaySessions = sessions.filter((sess) => isSessionToday(sess.session.created_at, now));
	const earlierSessions = sessions.filter(
		(sess) => !isSessionToday(sess.session.created_at, now),
	);

	return (
		<div className="flex h-full w-full p-2 gap-2">
			{/*
			 * Desktop stays `collapsible="none"` so the session list sits in
			 * normal flow beside the app rail (AppSidebar). Mobile switches to
			 * `offcanvas`, which makes shadcn's Sidebar render its Sheet overlay
			 * (the drawer we want) — instead of the desktop `fixed left-0`
			 * container, which would otherwise cover the app rail.
			 */}
			<Sidebar collapsible={isMobile ? 'offcanvas' : 'none'} className="rounded-[22px]">
				{/* Scrolling moves down to the session list below, so the
				    agent picker and the new-session button stay put. */}
				<SidebarContent className="my-2 overflow-hidden">
					<SidebarGroup className="px-2 py-0">
						<SidebarGroupLabel className="justify-between">
							{t('common.agent')}
							<AgentDialog onCreated={refetchAgents}>
								<Button
									variant="ghost"
									size="icon-xs"
									title={t('dialog-agent-create.title')}
								>
									<Plus id="tour-create-agent" className="size-3.5" />
								</Button>
							</AgentDialog>
						</SidebarGroupLabel>
						<SidebarGroupContent id="tour-agent-select" className="flex items-center">
							<AgentSelect
								className="flex-1 min-w-0"
								agents={agents}
								value={selectedAgentId}
								onChange={(id) => navigate(`/chat/${id}`)}
								variant="ghost"
								size="default"
							/>
							<DropdownMenu>
								<DropdownMenuTrigger asChild>
									<Button
										className="shrink-0 text-muted-foreground"
										variant="ghost"
										size="icon"
										disabled={!urlAgentId || !selectedAgent?.editable}
									>
										<Ellipsis />
									</Button>
								</DropdownMenuTrigger>
								{/* w-auto: the default pins the menu to the
								    trigger's width, which is a 32px icon button. */}
								<DropdownMenuContent className="w-auto">
									<DropdownMenuItem onClick={() => setEditOpen(true)}>
										<Settings2 />
										{t('agent-menu.settings')}
									</DropdownMenuItem>
									<DropdownMenuItem
										onClick={() => setDeleteOpen(true)}
										variant="destructive"
									>
										<Trash2 />
										{t('agent-menu.delete')}
									</DropdownMenuItem>
								</DropdownMenuContent>
							</DropdownMenu>
						</SidebarGroupContent>
					</SidebarGroup>
					<SidebarGroup className="mt-5 min-h-0 flex-1 px-2 py-0">
						<SidebarGroupLabel
							className="justify-between"
							title="Asia/Shanghai (UTC+08:00)"
						>
							{t('chat.session.label')}
							<span className="text-[10px] text-text-data font-mono">
								{sessions.length}
							</span>
						</SidebarGroupLabel>
						<SidebarGroupContent className="flex min-h-0 flex-1 flex-col">
							<SidebarGroup>
								<SidebarMenu className="mb-2">
									<Button
										id="tour-create-session"
										onClick={handleCreateSession}
										disabled={!selectedAgentId || sessionsLoading}
									>
										<Plus />
										{t('chat.newSession')}
									</Button>
								</SidebarMenu>
							</SidebarGroup>

							<div className="no-scrollbar min-h-0 flex-1 overflow-y-auto">
								{sessions.length === 0 ? (
									<Empty className="border-none py-4 min-h-50">
										<EmptyHeader>
											<EmptyMedia variant="icon">
												<MessageSquareDashed />
											</EmptyMedia>
											<EmptyTitle>{t('chat.session.emptyTitle')}</EmptyTitle>
											<EmptyDescription>
												{selectedAgentId
													? t('chat.session.emptyHasAgent')
													: t('chat.session.emptyNoAgent')}
											</EmptyDescription>
										</EmptyHeader>
									</Empty>
								) : (
									<>
										<SidebarGroup>
											<SidebarGroupLabel>
												{t('chat.session.today')}
											</SidebarGroupLabel>
											<SidebarGroupContent>
												<SidebarMenu>
													{todaySessions.map((view) => {
														const session = view.session;
														const SourceIcon =
															SOURCE_ICON[session.origin.type] ??
															BotMessageSquare;
														return (
															<SidebarMenuItem key={session.id}>
																{/* Wider right gutter than the stock
															    pr-8: the badge holds a mono timestamp. */}
																<SidebarMenuButton
																	className="text-muted-foreground hover:text-foreground group-has-data-[sidebar=menu-action]/menu-item:pr-16"
																	isActive={
																		urlSessionId === session.id
																	}
																	onClick={() => {
																		navigate(
																			`/chat/${urlAgentId}/${session.id}`,
																		);
																		setOpenMobile(false);
																	}}
																>
																	{showSourceIcons && (
																		<SourceIcon />
																	)}
																	<span className="truncate">
																		{sessionDisplayName(
																			session,
																		)}
																	</span>
																</SidebarMenuButton>
																{/* Badge and action are mutually exclusive.
															    Keyboard focus reveals the action, plain
															    focus-within does not — otherwise clicking
															    the row would pin it open. */}
																<SidebarMenuBadge
																	className="max-md:hidden group-hover/menu-item:hidden group-has-focus-visible/menu-item:hidden group-has-data-[state=open]/menu-item:hidden text-text-tertiary! font-mono"
																	title={`${formatSessionTime(session.created_at)} (UTC+08:00)`}
																>
																	{formatSessionTime(
																		session.created_at,
																		'time',
																	)}
																</SidebarMenuBadge>
																<DropdownMenu>
																	<DropdownMenuTrigger asChild>
																		<SidebarMenuAction className="md:opacity-0 group-hover/menu-item:opacity-100 group-has-focus-visible/menu-item:opacity-100 aria-expanded:opacity-100 peer-data-active/menu-button:text-sidebar-accent-foreground">
																			<Ellipsis />
																		</SidebarMenuAction>
																	</DropdownMenuTrigger>
																	<DropdownMenuContent
																		className="w-auto"
																		side="right"
																		align="start"
																	>
																		<DropdownMenuItem
																			onClick={() => {
																				setRenameSession(
																					session,
																				);
																				setRenameOpen(true);
																			}}
																		>
																			<Pencil />
																			{t(
																				'session-menu.rename',
																			)}
																		</DropdownMenuItem>
																		<DropdownMenuItem
																			variant="destructive"
																			onClick={() =>
																				requestDeleteSession(
																					session,
																				)
																			}
																		>
																			<Trash2 />
																			{t(
																				'session-menu.delete',
																			)}
																		</DropdownMenuItem>
																	</DropdownMenuContent>
																</DropdownMenu>
															</SidebarMenuItem>
														);
													})}
												</SidebarMenu>
											</SidebarGroupContent>
										</SidebarGroup>
										<SidebarGroup>
											<SidebarGroupLabel>
												{t('chat.session.earlier')}
											</SidebarGroupLabel>
											<SidebarGroupContent>
												<SidebarMenu>
													{earlierSessions.map((view) => {
														const session = view.session;
														const SourceIcon =
															SOURCE_ICON[session.origin.type] ??
															BotMessageSquare;
														return (
															<SidebarMenuItem key={session.id}>
																<SidebarMenuButton
																	className="text-muted-foreground hover:text-foreground group-has-data-[sidebar=menu-action]/menu-item:pr-16"
																	isActive={
																		urlSessionId === session.id
																	}
																	onClick={() => {
																		navigate(
																			`/chat/${urlAgentId}/${session.id}`,
																		);
																		setOpenMobile(false);
																	}}
																>
																	{showSourceIcons && (
																		<SourceIcon />
																	)}
																	<span className="truncate">
																		{sessionDisplayName(
																			session,
																		)}
																	</span>
																</SidebarMenuButton>
																<SidebarMenuBadge
																	className="max-md:hidden group-hover/menu-item:hidden group-has-focus-visible/menu-item:hidden group-has-data-[state=open]/menu-item:hidden text-text-tertiary! font-mono"
																	title={`${formatSessionTime(session.created_at)} (UTC+08:00)`}
																>
																	{formatSessionTime(
																		session.created_at,
																		'date',
																	).slice(5)}
																</SidebarMenuBadge>
																<DropdownMenu>
																	<DropdownMenuTrigger asChild>
																		<SidebarMenuAction className="md:opacity-0 group-hover/menu-item:opacity-100 group-has-focus-visible/menu-item:opacity-100 aria-expanded:opacity-100 peer-data-active/menu-button:text-sidebar-accent-foreground">
																			<Ellipsis />
																		</SidebarMenuAction>
																	</DropdownMenuTrigger>
																	<DropdownMenuContent
																		className="w-auto"
																		side="right"
																		align="start"
																	>
																		<DropdownMenuItem
																			onClick={() => {
																				setRenameSession(
																					session,
																				);
																				setRenameOpen(true);
																			}}
																		>
																			<Pencil />
																			{t(
																				'session-menu.rename',
																			)}
																		</DropdownMenuItem>
																		<DropdownMenuItem
																			variant="destructive"
																			onClick={() =>
																				requestDeleteSession(
																					session,
																				)
																			}
																		>
																			<Trash2 />
																			{t(
																				'session-menu.delete',
																			)}
																		</DropdownMenuItem>
																	</DropdownMenuContent>
																</DropdownMenu>
															</SidebarMenuItem>
														);
													})}
												</SidebarMenu>
											</SidebarGroupContent>
										</SidebarGroup>
									</>
								)}
							</div>
						</SidebarGroupContent>
					</SidebarGroup>
				</SidebarContent>
			</Sidebar>
			<div className="flex flex-1 min-w-0">
				<ChatViewport
					agentId={effectiveAgentId}
					sessionId={effectiveSessionId}
					onSessionsChanged={refetchSessions}
				/>
			</div>
			{selectedAgent && (
				<>
					<EditAgentDialog
						open={editOpen}
						onOpenChange={setEditOpen}
						agent={selectedAgent}
						onUpdated={refetchAgents}
					/>
					<DeleteDialog
						open={deleteOpen}
						onOpenChange={setDeleteOpen}
						title={t('common.deleteTitle', {
							entity: t('dialog-agent-delete.entity'),
							name: selectedAgent.data.name,
						})}
						description={t('common.deleteDescription')}
						confirmLabel={t('dialog-agent-delete.confirm')}
						onConfirm={async () => {
							await removeAgent(selectedAgent.id);
							await handleAgentDeleted();
						}}
					/>
				</>
			)}
			<RenameSessionDialog
				open={renameOpen}
				onOpenChange={setRenameOpen}
				currentName={renameSession ? sessionDisplayName(renameSession) : ''}
				onConfirm={handleRenameConfirm}
			/>
			<DeleteDialog
				open={deleteSessionOpen}
				onOpenChange={setDeleteSessionOpen}
				title={t('common.deleteTitle', {
					entity: t('dialog-session-delete.entity'),
					name: (() => {
						const raw = sessionToDelete ? sessionDisplayName(sessionToDelete) : '';
						return raw.length > 30 ? `${raw.slice(0, 30)}…` : raw;
					})(),
				})}
				description={t('common.deleteDescription')}
				confirmLabel={t('dialog-session-delete.confirm')}
				onConfirm={async () => {
					if (sessionToDelete) {
						await handleDeleteSession(sessionToDelete.id);
					}
				}}
			/>
			<ChatTourController
				ready={
					!!selectedAgentId &&
					!agentsLoading &&
					!agentsError &&
					!sessionsLoading &&
					!sessionsError
				}
				sessionsCount={sessions.length}
				onEnsureSidebarOpen={ensureSidebarOpen}
			/>
		</div>
	);
};

export const ChatPage = () => (
	<AudioProvider>
		<SidebarProvider defaultOpen>
			<ChatPageInner />
		</SidebarProvider>
	</AudioProvider>
);
