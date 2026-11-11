import { useState } from "react";
import {
  Avatar,
  ButtonBase,
  Divider,
  IconButton,
  InputAdornment,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Popover,
  TextField,
  Tooltip,
} from "@mui/material";
import AppsOutlined from "@mui/icons-material/AppsOutlined";
import AutoAwesomeOutlined from "@mui/icons-material/AutoAwesomeOutlined";
import ChatBubbleOutline from "@mui/icons-material/ChatBubbleOutline";
import TuneOutlined from "@mui/icons-material/TuneOutlined";
import PlayCircleOutline from "@mui/icons-material/PlayCircleOutline";
import SearchRounded from "@mui/icons-material/SearchRounded";
import AddRounded from "@mui/icons-material/AddRounded";
import ExpandMoreRounded from "@mui/icons-material/ExpandMoreRounded";
import ChevronLeftRounded from "@mui/icons-material/ChevronLeftRounded";
import MenuRounded from "@mui/icons-material/MenuRounded";
import { ThemeToggle } from "./theme";
import type { Project, WorkspaceTab } from "./types";

export function Navigation({
  projects,
  activeProject,
  section,
  modelsActive,
  collapsed,
  mobileOpen,
  onCollapse,
  onMobileToggle,
  onHome,
  onModels,
  onImport,
  onOpen,
  onSection,
}: {
  projects: Project[];
  activeProject: Project | null;
  section: WorkspaceTab;
  modelsActive: boolean;
  collapsed: boolean;
  mobileOpen: boolean;
  onCollapse: () => void;
  onMobileToggle: () => void;
  onHome: () => void;
  onModels: () => void;
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
    >
      <div className="sidebar-brand">
        <ButtonBase
          className="brand"
          onClick={onHome}
          aria-label="回到项目列表"
        >
          <span className="brand-mark" aria-hidden="true">
            E
          </span>
          <strong>Evalith</strong>
        </ButtonBase>
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
          aria-controls="sidebar-content"
          aria-label={mobileOpen ? "收起导航" : "展开导航"}
        >
          <MenuRounded />
        </IconButton>
      </div>
      <div className="sidebar-content" id="sidebar-content">
        <Tooltip
          describeChild
          title={collapsed ? (activeProject?.name ?? "切换项目") : ""}
          placement="right"
        >
          <ButtonBase
            className="project-switcher"
            aria-label="切换项目"
            aria-haspopup="dialog"
            aria-expanded={Boolean(anchor)}
            onClick={(event) => setAnchor(event.currentTarget)}
          >
            <Avatar variant="rounded">
              <AppsOutlined fontSize="small" />
            </Avatar>
            <span>
              {activeProject?.name ?? "选择项目"}
              <small>项目工作区</small>
            </span>
            <ExpandMoreRounded fontSize="small" />
          </ButtonBase>
        </Tooltip>
        <Popover
          open={Boolean(anchor)}
          anchorEl={anchor}
          onClose={close}
          anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
          slotProps={{
            paper: {
              role: "dialog",
              "aria-label": "项目切换器",
              sx: { width: 280, p: 1.5 },
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
                  selected={activeProject?.id === project.id}
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
              onHome();
            }}
          >
            <ListItemIcon>
              <AppsOutlined fontSize="small" />
            </ListItemIcon>
            <ListItemText primary="全部项目" />
          </ListItemButton>
          <ListItemButton
            onClick={() => {
              close();
              onImport();
            }}
          >
            <ListItemIcon>
              <AddRounded fontSize="small" />
            </ListItemIcon>
            <ListItemText primary="导入本地项目" />
          </ListItemButton>
        </Popover>
        <nav aria-label="主导航" className="function-nav">
          <NavRow
            icon={<AppsOutlined />}
            label="项目总览"
            active={!activeProject && !modelsActive}
            onClick={onHome}
            collapsed={collapsed}
          />
          <NavRow
            icon={<AutoAwesomeOutlined />}
            label="项目会话"
            active={
              !!activeProject && section === "conversation" && !modelsActive
            }
            onClick={() => onSection("conversation")}
            disabled={!activeProject}
            collapsed={collapsed}
          />
          <p className="nav-group">评测</p>
          <NavRow
            icon={<ChatBubbleOutline />}
            label="题目集"
            disabled
            collapsed={collapsed}
          />
          <NavRow
            icon={<PlayCircleOutline />}
            label="运行结果"
            disabled
            collapsed={collapsed}
          />
        </nav>
        <div className="sidebar-bottom">
          <NavRow
            icon={<TuneOutlined />}
            label="模型与凭据"
            active={modelsActive}
            onClick={onModels}
            collapsed={collapsed}
          />
          <div className="sidebar-settings">
            <span>本地工作区</span>
            <ThemeToggle />
          </div>
        </div>
      </div>
    </aside>
  );
}

function NavRow({
  icon,
  label,
  active,
  disabled,
  onClick,
  collapsed,
}: {
  icon: React.ReactNode;
  label: string;
  active?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  collapsed: boolean;
}) {
  return (
    <Tooltip
      describeChild
      title={
        disabled
          ? label === "题目集" || label === "运行结果"
            ? `${label}将在后续阶段开放`
            : "请先选择项目"
          : collapsed
            ? label
            : ""
      }
      placement="right"
    >
      <span>
        <ListItemButton
          className="nav-row"
          selected={active}
          disabled={disabled}
          onClick={onClick}
          aria-label={label}
          aria-current={active ? "page" : undefined}
        >
          <ListItemIcon>{icon}</ListItemIcon>
          <ListItemText primary={label} />
        </ListItemButton>
      </span>
    </Tooltip>
  );
}
