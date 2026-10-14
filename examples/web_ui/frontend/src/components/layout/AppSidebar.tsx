import {
	BookText,
	BotMessageSquare,
	Cable,
	Calendars,
	Compass,
	KeyRound,
	Languages,
	LibraryBig,
	LogOut,
	ListChecks,
	Repeat2,
	Settings,
	UserRound,
} from 'lucide-react';
import { useOnborda } from 'onborda';
import { useNavigate, useLocation } from 'react-router-dom';

import AgentScope from '@/assets/images/agentscope.svg?react';
import MCPSvg from '@/assets/images/mcp.svg?react';
import { CHAT_TOUR_NAME } from '@/components/tour/chatTourSteps';
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuLabel,
	DropdownMenuSeparator,
	DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
	Sidebar,
	SidebarContent,
	SidebarFooter,
	SidebarGroup,
	SidebarGroupContent,
	SidebarHeader,
	SidebarMenu,
	SidebarMenuButton,
	SidebarMenuItem,
} from '@/components/ui/sidebar';
import { useAuth } from '@/hooks/useAuth';
import i18n from '@/i18n';
import { useTranslation } from '@/i18n/useI18n';

const iconButtonClassName =
	'h-auto! min-h-12! flex-col! justify-center! gap-0.5! p-1! text-[10px] leading-3';
const iconLabelClassName = 'max-w-full text-center text-[9px] leading-3 whitespace-normal!';

export function AppSidebar() {
	const navigate = useNavigate();
	const location = useLocation();
	const { t } = useTranslation();
	const { startOnborda } = useOnborda();
	const { user, logout } = useAuth();

	const handleStartTour = () => {
		if (!location.pathname.startsWith('/chat')) {
			// Page not mounted yet — leave a flag, navigate, and let the
			// ChatTourController auto-trigger after ChatPage mounts.
			sessionStorage.setItem('force_tour', '1');
			navigate('/chat');
		} else {
			startOnborda(CHAT_TOUR_NAME);
		}
	};

	const handleToggleLanguage = () => {
		const next = i18n.language.startsWith('zh') ? 'en' : 'zh';
		i18n.changeLanguage(next);
	};

	const handleLogout = async () => {
		await logout();
		navigate('/login', { replace: true });
	};

	return (
		<Sidebar
			collapsible="none"
			className="w-[calc(var(--sidebar-width-icon)+1px)]! bg-transparent"
		>
			<SidebarHeader>
				<AgentScope className="mt-2 size-8" />
			</SidebarHeader>
			<SidebarContent>
				<SidebarGroup>
					<SidebarGroupContent>
						<SidebarMenu>
							<SidebarMenuItem key={'chat'}>
								<SidebarMenuButton
									tooltip={{ children: t('common.chat'), hidden: false }}
									isActive={
										location.pathname === '/chat' ||
										location.pathname.startsWith('/chat/')
									}
									onClick={() => navigate('/chat')}
									className={iconButtonClassName}
								>
									<BotMessageSquare />
									<span className={iconLabelClassName}>{t('common.chat')}</span>
								</SidebarMenuButton>
							</SidebarMenuItem>
							<SidebarMenuItem>
								<SidebarMenuButton
									tooltip={{ children: t('common.schedule'), hidden: false }}
									isActive={location.pathname === '/schedule'}
									onClick={() => navigate('/schedule')}
									className={iconButtonClassName}
								>
									<Calendars />
									<span className={iconLabelClassName}>
										{t('common.schedule')}
									</span>
								</SidebarMenuButton>
							</SidebarMenuItem>
							<SidebarMenuItem>
								<SidebarMenuButton
									tooltip={{ children: t('common.sop'), hidden: false }}
									isActive={location.pathname === '/sop'}
									onClick={() => navigate('/sop')}
									className={iconButtonClassName}
								>
									<ListChecks />
									<span className={iconLabelClassName}>{t('common.sop')}</span>
								</SidebarMenuButton>
							</SidebarMenuItem>
							<SidebarMenuItem>
								<SidebarMenuButton
									tooltip={{ children: t('common.channel'), hidden: false }}
									isActive={location.pathname === '/channel'}
									onClick={() => navigate('/channel')}
									className={iconButtonClassName}
								>
									<Cable />
									<span className={iconLabelClassName}>
										{t('common.channel')}
									</span>
								</SidebarMenuButton>
							</SidebarMenuItem>
						</SidebarMenu>
					</SidebarGroupContent>
				</SidebarGroup>
				<SidebarGroup>
					<SidebarGroupContent>
						<SidebarMenu>
							<SidebarMenuItem>
								<SidebarMenuButton
									tooltip={{ children: t('common.credential'), hidden: false }}
									isActive={location.pathname === '/credential'}
									onClick={() => navigate('/credential')}
									className={iconButtonClassName}
								>
									<KeyRound />
									<span className={iconLabelClassName}>
										{t('common.credential')}
									</span>
								</SidebarMenuButton>
							</SidebarMenuItem>
							<SidebarMenuItem>
								<SidebarMenuButton
									tooltip={{ children: t('common.mcp-hub'), hidden: false }}
									// Stays lit while browsing a hub under /mcp/:hubId.
									isActive={location.pathname.startsWith('/mcp')}
									onClick={() => navigate('/mcp')}
									className={iconButtonClassName}
								>
									<MCPSvg />
									<span className={iconLabelClassName}>
										{t('common.mcp-hub')}
									</span>
								</SidebarMenuButton>
							</SidebarMenuItem>
							<SidebarMenuItem>
								<SidebarMenuButton
									tooltip={{ children: t('common.skill-hub'), hidden: false }}
									isActive={location.pathname.startsWith('/skill')}
									onClick={() => navigate('/skill')}
									className={iconButtonClassName}
								>
									<BookText />
									<span className={iconLabelClassName}>
										{t('common.skill-hub')}
									</span>
								</SidebarMenuButton>
							</SidebarMenuItem>
							<SidebarMenuItem>
								<SidebarMenuButton
									tooltip={{ children: t('common.knowledge'), hidden: false }}
									isActive={location.pathname === '/knowledge'}
									onClick={() => navigate('/knowledge')}
									className={iconButtonClassName}
								>
									<LibraryBig />
									<span className={iconLabelClassName}>
										{t('common.knowledge')}
									</span>
								</SidebarMenuButton>
							</SidebarMenuItem>
						</SidebarMenu>
					</SidebarGroupContent>
				</SidebarGroup>
			</SidebarContent>
			<SidebarFooter>
				<SidebarMenu>
					<SidebarMenuItem>
						<DropdownMenu>
							<DropdownMenuTrigger asChild>
								<SidebarMenuButton
									tooltip={{
										children: user?.username ?? t('auth.accountCenter'),
										hidden: false,
									}}
									isActive={location.pathname === '/account'}
									className={iconButtonClassName}
								>
									<UserRound />
									<span className={iconLabelClassName}>
										{t('auth.accountCenter')}
									</span>
								</SidebarMenuButton>
							</DropdownMenuTrigger>
							<DropdownMenuContent side="right" align="end" className="min-w-52">
								<DropdownMenuLabel>
									<div className="font-medium text-foreground">
										{user?.username}
									</div>
									<div className="mt-0.5 font-sans text-xs font-normal">
										{t('auth.brand')}
									</div>
								</DropdownMenuLabel>
								<DropdownMenuSeparator />
								<DropdownMenuItem onSelect={() => navigate('/account')}>
									<UserRound />
									{t('auth.accountAndUsage')}
								</DropdownMenuItem>
								<DropdownMenuItem onSelect={() => navigate('/setup')}>
									<Settings />
									{t('common.settings')}
								</DropdownMenuItem>
								<DropdownMenuSeparator />
								<DropdownMenuItem onSelect={() => void handleLogout()}>
									<Repeat2 />
									{t('auth.switchAccount')}
								</DropdownMenuItem>
								<DropdownMenuItem
									variant="destructive"
									onSelect={() => void handleLogout()}
								>
									<LogOut />
									{t('auth.logout')}
								</DropdownMenuItem>
							</DropdownMenuContent>
						</DropdownMenu>
					</SidebarMenuItem>
					<SidebarMenuItem>
						<SidebarMenuButton
							tooltip={{
								children: i18n.language.startsWith('zh')
									? t('common.switchToEn')
									: t('common.switchToZh'),
								hidden: false,
							}}
							onClick={handleToggleLanguage}
							className={iconButtonClassName}
						>
							<Languages />
							<span className={iconLabelClassName}>{t('common.language')}</span>
						</SidebarMenuButton>
					</SidebarMenuItem>
					<SidebarMenuItem>
						<SidebarMenuButton
							tooltip={{ children: t('tour.trigger'), hidden: false }}
							onClick={handleStartTour}
							className={iconButtonClassName}
						>
							<Compass />
							<span className={iconLabelClassName}>{t('tour.trigger')}</span>
						</SidebarMenuButton>
					</SidebarMenuItem>
				</SidebarMenu>
			</SidebarFooter>
		</Sidebar>
	);
}
