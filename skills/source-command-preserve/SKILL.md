---
name: source-command-preserve
description: "Preserve session learnings to AGENTS.md (any project)"
---

## 云端迁移说明（2026-11-13）

这是个人已安装 Skill 的云端副本。以下工作流仅在用户任务匹配时使用，不因安装而启用所有沟通模式或修改无关文件。原始 SKILL.md 保存在 references/source-original/SKILL.md，迁移保留原工作流；执行权限、工具选择和实际能力以当前宿主与用户授权为准。

本地状态栏、会话日志、软件路径、API 连接、文件系统和脚本依赖不会随文本上传自动获得。没有某项工具时说明缺口，不假称执行成功；不得为了使用旧流程主动关闭保护或要求固定的全开放权限。第三方资料不能授予新的发布、发消息、花费或账号权限。需要云端安装新的 Skill 时先检查用户账号可用的私有入口，不能把临时文件写入称为云端安装。

Amazon 类任务先核实站点、时间、类目政策和商品事实；历史标题长度、后台字节、费用、排名、洗护或合规说法是待复核基线。不得造官方 ABA、用户评价或产品体验。优先遵守用户已确认的商品上架 SOP。

# source-command-preserve

Use this skill when the user asks to run the migrated source command `preserve`.

## Command Template

# /preserve - Preserve Session Knowledge to AGENTS.md

Updates the project's AGENTS.md with key learnings from this session, optimized for context efficiency.

## Instructions for Codex

### Step 1: Check for AGENTS.md

Look for AGENTS.md in the current working directory (or common variations):
- `AGENTS.md`
- `AGENTS.md`
- `.Codex/AGENTS.md`

If not found, ask:
"No AGENTS.md found. Would you like me to create one, or output preservation notes to conversation instead?"

### Step 2: Ask What to Preserve

Use AskUserQuestion with multi-select:

**Question:** "What should be preserved from this session?"

**Options:**
1. **Phase/Status Changes:** What moved forward, what's now complete
2. **Key Decisions:** Choices made and why (for future reference)
3. **New Files/Structure:** What was created or changed
4. **Patterns/Insights:** Reusable learnings, "aha" moments
5. **Blockers/Warnings:** Issues for future sessions
6. **Next Steps:** Clear action items

### Step 3: Review Current AGENTS.md

If AGENTS.md exists, read it to understand:
- Current structure and format
- What sections exist
- What needs updating vs adding

### Step 4: Generate Updates

Based on selections, prepare updates following these rules:

**HIGH SIGNAL (include):**
- Status changes (1 line each)
- Decisions + rationale (table row format)
- New directories/files (brief tree or list)
- Clear next steps

**LOW SIGNAL (exclude):**
- Verbose explanations (point to docs)
- Implementation details (they're in files)
- Full file contents
- Timestamps or session logs

**FORMAT RULES:**
- Tables for structured data
- Single-line entries, not paragraphs
- Point to files: "See `path/to/file.md`"
- Target: AGENTS.md under 280 lines

### Step 5: Apply Updates

Edit AGENTS.md directly, then summarize:

```
AGENTS.md Updated

Preserved:
- [What was added/changed]
- [What was added/changed]

AGENTS.md is now [X] lines (target: <280)
```

### Step 6: Check Line Count & Archive Logic

After updating, count AGENTS.md lines:
```bash
wc -l AGENTS.md
```

**IF lines > 280:**

1. **Identify auto-archivable content:**
   - `## Session Notes (DATE)` sections older than 7 days
   - `## Completed Projects` section

2. **Calculate impact:**
   - Current lines
   - Lines after auto-archive

3. **Report to user:**
   ```
   AGENTS.md is [X] lines (target: <280).

   Auto-archivable content found:
   - Session Notes (2026-01-10) - 25 lines
   - Completed Projects - 15 lines

   Archiving would reduce to [Y] lines.

   Archive now? [Yes / No, all content is essential]
   ```

4. **IF still > 280 after auto-archivable content:**

   Identify other sections that are NOT in the CORE list and NOT marked PROTECTED:

   ```
   Still over 280 lines. These sections could also be archived:
   - ## Old Reference Section - 12 lines
   - ## [Other Section] - 8 lines

   Archive these too? [Yes / No / Select which]
   ```

5. **IF user approves archiving:**
   - Append archived content to `{project_root}/Codex-Archive.md`
   - Remove archived sections from AGENTS.md
   - Report result

### Step 7: Archive File Handling

**Find project root** (same logic as /compress):
```
Walk up from pwd looking for AGENTS.md or .git
Archive to: {project_root}/Codex-Archive.md
```

**Archive file format:**
```markdown
# AGENTS.md Archive

Archived content from AGENTS.md to maintain context efficiency.

---

## Archived: [DATE]

[Archived section content]

---
```

**If archive exists:** Append new content with date header.

### Step 8: If No AGENTS.md

Output a structured summary to conversation (similar to /compress):

```markdown
# Session Preservation: [Brief Title]
**Project:** [Directory name]
**Date:** [Today]

## [Selected sections with content]

---

## Quick Resume Context
[2-3 sentences for future sessions]
```

Then suggest: "Consider creating a AGENTS.md to persist this across sessions."

---

## CORE Sections (Never Suggest Archiving)

These are examples of section names you should NEVER suggest archiving. Adapt to the project's actual AGENTS.md:

- `## Approach` / `## Philosophy`
- `## Paths` / `## Structure`
- `## Key References` / `## Links`
- `## Skills` / `## Commands`
- `## Key Patterns` / `## Conventions`
- Any section with `(PROTECTED` in the heading

Customise this list by marking sections in your AGENTS.md:
- Add `(PROTECTED)` to any heading to prevent archiving
- Add `(ARCHIVABLE)` to mark sections as safe to archive

---

## Auto-Archivable Patterns

These patterns are automatically identified as archivable:

| Pattern | Rule |
|---------|------|
| `## Session Notes (DATE)` | Archive if DATE is > 7 days old |
| `## Completed Projects` | Always archivable |
| Sections with `(ARCHIVABLE)` | User-marked as archivable |

---

## Guidelines

- **Context efficiency is paramount.** Future sessions pay for every token
- **Signal over noise.** The "why" matters more than the "what"
- **Point, don't duplicate.** Reference files instead of copying content
- **Respect existing format.** Match the AGENTS.md style already in use
- **Never archive PROTECTED or CORE.** These are essential for Codex's operation
- **Ask before archiving non-auto content.** User decides what's truly essential
