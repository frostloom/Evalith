import { useState } from "react";
import {
  ButtonBase,
  Divider,
  IconButton,
  InputAdornment,
  List,
  ListItemButton,
  ListItemText,
  Popover,
  Tab,
  Tabs,
  TextField,
  Tooltip,
} from "@mui/material";
import {
  FolderClosed,
  TerminalSquare,
  Cpu,
  Search,
  Plus,
  ChevronDown,
  PanelLeftClose,
  Menu,
  MessageSquare,
  ListChecks,
  Files,
} from "lucide-react";
import { ThemeToggle } from "./theme";
import { EvalithMark } from "./ui";
import type { Project, WorkspaceTab } from "./types";

export function Navigation({
  projects,
  activeProject,
  section,
  modelsActive,
  executorsActive,
  collapsed,
  mobileOpen,
  onCollapse,
  onMobileToggle,
  onHome,
  onModels,
  onExecutors,
  onImport,
  onOpen,
  onSection,
}: {
  projects: Project[];
  activeProject: Project | null;
  section: WorkspaceTab;
  modelsActive: boolean;
  executorsActive: boolean;
  collapsed: boolean;
  mobileOpen: boolean;
  onCollapse: () => void;
  onMobileToggle: () => void;
  onHome: () => void;
  onModels: () => void;
  onExecutors: () => void;
  onImport: () => void;
  onOpen: (project: Project) => void;
  onSection: (tab: WorkspaceTab) => void;
}) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [search, setSearch] = useState("");
  const close = () => {
    setAnchor(null);
    setSearch("");
  };
  return (
    <aside
      className={`sidebar ${collapsed ? "is-collapsed" : ""} ${mobileOpen ? "is-mobile-open" : ""}`}
      aria-label="工作区侧栏"
    >
      <div className="sidebar-brand">
        <ButtonBase
          className="brand"
          onClick={onHome}
          aria-label="Evalith，回到项目目录"
        >
          <EvalithMark />
          <strong>Evalith</strong>
        </ButtonBase>
        <Tooltip title={collapsed ? "展开侧栏" : "收起侧栏"}>
          <IconButton
            className="desktop-collapse"
            onClick={onCollapse}
            aria-label={collapsed ? "展开侧栏" : "收起侧栏"}
          >
            <PanelLeftClose />
          </IconButton>
        </Tooltip>
        <IconButton
          className="mobile-toggle"
          onClick={onMobileToggle}
          aria-expanded={mobileOpen}
          aria-label={mobileOpen ? "收起导航" : "展开导航"}
        >
          <Menu />
        </IconButton>
      </div>
      <div className="sidebar-content" id="sidebar-content">
        <nav aria-label="工作区导航" className="workspace-nav">
          <button
            aria-label="项目目录"
            className={`nav-item ${!activeProject && !modelsActive && !executorsActive ? "is-active" : ""}`}
            onClick={onHome}
            aria-current={
              !activeProject && !modelsActive && !executorsActive
                ? "page"
                : undefined
            }
          >
            <FolderClosed />
            <span>项目目录</span>
            <span className="nav-count">{projects.length}</span>
          </button>
          <button
            className="nav-item nav-create"
            onClick={onImport}
            aria-label="建立新项目"
          >
            <Plus />
            <span>新建项目</span>
          </button>
        </nav>
        {!activeProject && projects.length > 0 && (
          <div className="recent-projects">
            <p className="nav-group">最近项目</p>
            {projects.slice(0, 6).map((project) => (
              <button
                className="nav-item recent-project"
                key={project.id}
                onClick={() => onOpen(project)}
                aria-label={`打开项目 ${project.name}`}
              >
                <span className="recent-project-dot" aria-hidden="true" />
                <span>{project.name}</span>
              </button>
            ))}
          </div>
        )}
        {activeProject && (
          <div className="project-navigation">
            <p className="nav-group">当前项目</p>
            <ButtonBase
              className="project-switcher"
              aria-label="切换项目"
              aria-haspopup="dialog"
              aria-expanded={Boolean(anchor)}
              onClick={(event) => setAnchor(event.currentTarget)}
            >
              <span className="project-identity" aria-hidden="true">
                {activeProject.name.slice(0, 1)}
              </span>
              <span>{activeProject.name}</span>
              <ChevronDown />
            </ButtonBase>
            <Popover
              open={Boolean(anchor)}
              anchorEl={anchor}
              onClose={close}
              anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
              slotProps={{
                paper: {
                  role: "dialog",
                  "aria-label": "项目切换器",
                  sx: { width: 300, p: 1.5 },
                },
              }}
            >
              <TextField
                autoFocus
                fullWidth
                placeholder="搜索项目…"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                slotProps={{
                  htmlInput: { "aria-label": "搜索可切换的项目" },
                  input: {
                    startAdornment: (
                      <InputAdornment position="start">
                        <Search size={16} />
                      </InputAdornment>
                    ),
                  },
                }}
              />
              <List className="switcher-list" disablePadding>
                {projects
                  .filter((project) =>
                    project.name.toLowerCase().includes(search.toLowerCase()),
                  )
                  .map((project) => (
                    <ListItemButton
                      key={project.id}
                      selected={activeProject.id === project.id}
                      onClick={() => {
                        close();
                        onOpen(project);
                      }}
                    >
                      <ListItemText
                        primary={project.name}
                        secondary={`${project.file_count} 个文件`}
                      />
                    </ListItemButton>
                  ))}
                {!projects.some((project) =>
                  project.name.toLowerCase().includes(search.toLowerCase()),
                ) && <p className="empty-menu">没有匹配的项目</p>}
              </List>
              <Divider />
              <ListItemButton
                onClick={() => {
                  close();
                  onImport();
                }}
              >
                <Plus size={16} />
                <ListItemText primary="建立项目" sx={{ ml: 1 }} />
              </ListItemButton>
            </Popover>
            <Tabs
              orientation="vertical"
              value={section}
              onChange={(_, value: WorkspaceTab) => onSection(value)}
              selectionFollowsFocus
              aria-label="项目工作区章节"
              className="project-nav"
            >
              <Tab
                id="tab-conversation"
                aria-controls="panel-conversation"
                value="conversation"
                icon={<MessageSquare />}
                iconPosition="start"
                label="主会话"
              />
              <Tab
                id="tab-overview"
                aria-controls="panel-overview"
                value="overview"
                icon={<ListChecks />}
                iconPosition="start"
                label="项目理解"
              />
              <Tab
                id="tab-sources"
                aria-controls="panel-sources"
                value="sources"
                icon={<Files />}
                iconPosition="start"
                label="资料来源"
              />
            </Tabs>
          </div>
        )}
        <div className="sidebar-bottom">
          <p className="nav-group">配置</p>
          <nav className="workspace-nav" aria-label="配置导航">
            <button
              aria-label="执行器配置"
              className={`nav-item ${executorsActive ? "is-active" : ""}`}
              onClick={onExecutors}
              aria-current={executorsActive ? "page" : undefined}
            >
              <TerminalSquare />
              <span>执行器配置</span>
            </button>
            <button
              aria-label="模型配置"
              className={`nav-item ${modelsActive ? "is-active" : ""}`}
              onClick={onModels}
              aria-current={modelsActive ? "page" : undefined}
            >
              <Cpu />
              <span>模型配置</span>
            </button>
          </nav>
          <div className="sidebar-settings">
            <span>本地工作区</span>
            <ThemeToggle />
          </div>
        </div>
      </div>
    </aside>
  );
}
