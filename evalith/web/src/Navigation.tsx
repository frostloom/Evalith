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
import ArrowBackRounded from "@mui/icons-material/ArrowBackRounded";
import FolderOutlined from "@mui/icons-material/FolderOutlined";
import ChatBubbleOutline from "@mui/icons-material/ChatBubbleOutline";
import DescriptionOutlined from "@mui/icons-material/DescriptionOutlined";
import TuneOutlined from "@mui/icons-material/TuneOutlined";
import PlayCircleOutline from "@mui/icons-material/PlayCircleOutline";
import SearchRounded from "@mui/icons-material/SearchRounded";
import AddRounded from "@mui/icons-material/AddRounded";
import ExpandMoreRounded from "@mui/icons-material/ExpandMoreRounded";
import ChevronLeftRounded from "@mui/icons-material/ChevronLeftRounded";
import MenuRounded from "@mui/icons-material/MenuRounded";
import ChecklistRounded from "@mui/icons-material/ChecklistRounded";
import TerminalRounded from "@mui/icons-material/TerminalRounded";
import { ThemeToggle } from "./theme";
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
  const brand = (
    <>
      <span className="brand-mark" aria-hidden="true">
        E
      </span>
      <strong>Evalith</strong>
    </>
  );

  const globalHeader = (
    <header className="global-header">
      <ButtonBase
        className="brand"
        onClick={onHome}
        aria-label="Evalith，回到项目目录"
      >
        {brand}
      </ButtonBase>
      <nav aria-label="工作区导航">
        <button
          className={`global-nav-item ${!activeProject && !modelsActive && !executorsActive ? "is-active" : ""}`}
          onClick={onHome}
          aria-current={
            !activeProject && !modelsActive && !executorsActive
              ? "page"
              : undefined
          }
          aria-label="项目目录"
        >
          <FolderOutlined />
          项目目录
        </button>
        <button
          className={`global-nav-item ${executorsActive ? "is-active" : ""}`}
          onClick={onExecutors}
          aria-current={executorsActive ? "page" : undefined}
        >
          <TerminalRounded />
          执行器配置
        </button>
        <button
          className={`global-nav-item ${modelsActive ? "is-active" : ""}`}
          onClick={onModels}
          aria-current={modelsActive ? "page" : undefined}
          aria-label="模型配置"
        >
          <TuneOutlined />
          模型配置
        </button>
      </nav>
      <div className="global-header-actions">
        <ThemeToggle />
      </div>
    </header>
  );
  if (!activeProject) return globalHeader;

  return (
    <>
      {globalHeader}
      <aside
        className={`sidebar ${collapsed ? "is-collapsed" : ""} ${mobileOpen ? "is-mobile-open" : ""}`}
      >
        <div className="sidebar-toolbar">
          <button
            className="back-to-projects"
            onClick={onHome}
            aria-label="返回项目目录"
          >
            <ArrowBackRounded />
            <span>所有项目</span>
          </button>
          <Tooltip title={collapsed ? "展开侧栏" : "收起侧栏"}>
            <IconButton
              className="desktop-collapse"
              onClick={onCollapse}
              aria-label={collapsed ? "展开侧栏" : "收起侧栏"}
            >
              <ChevronLeftRounded />
            </IconButton>
          </Tooltip>
          <IconButton
            className="mobile-toggle"
            onClick={onMobileToggle}
            aria-expanded={mobileOpen}
            aria-label={mobileOpen ? "收起导航" : "展开导航"}
          >
            <MenuRounded />
          </IconButton>
        </div>
        <div className="sidebar-content" id="sidebar-content">
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
            <span>
              {activeProject.name}
              <small>项目工作区</small>
            </span>
            <ExpandMoreRounded fontSize="small" />
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
                      <SearchRounded fontSize="small" />
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
              <AddRounded fontSize="small" />
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
              icon={<ChatBubbleOutline />}
              iconPosition="start"
              label="主会话"
            />
            <Tab
              id="tab-overview"
              aria-controls="panel-overview"
              value="overview"
              icon={<ChecklistRounded />}
              iconPosition="start"
              label="项目理解"
            />
            <Tab
              id="tab-sources"
              aria-controls="panel-sources"
              value="sources"
              icon={<DescriptionOutlined />}
              iconPosition="start"
              label="资料来源"
            />
          </Tabs>
          <div className="future-nav">
            <p className="nav-group">评测</p>
            <Tooltip
              describeChild
              title="题目集将在后续阶段开放"
              placement="right"
            >
              <span>
                <button disabled>
                  <FolderOutlined />
                  <span>题目集</span>
                </button>
              </span>
            </Tooltip>
            <Tooltip
              describeChild
              title="运行结果将在后续阶段开放"
              placement="right"
            >
              <span>
                <button disabled>
                  <PlayCircleOutline />
                  <span>运行结果</span>
                </button>
              </span>
            </Tooltip>
          </div>
          <div className="sidebar-bottom">
            <div className="project-source-note">
              <FolderOutlined />
              <span>{activeProject.file_count} 份项目资料</span>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
