const { Plugin } = require("obsidian");
const fs = require("fs");
const path = require("path");

/**
 * Focus Writer —— 把 Obsidian 焦点写入 .goodidea/runtime/focus.json
 *
 * 焦点定义（与 AGENTS.md 共创前提契约一致）：
 *  1. note-database 看板/表格中勾选（选中）的卡片 → 主输入
 *  2. 无选中时回退到 Obsidian 当前打开的文件（排除数据库视图/画布/base 等非认知对象）
 *  3. 都拿不到时删除 focus.json（显式"无焦点"）
 *
 * 输出格式：
 *  { "paths": ["闪念空间/xxx.md", ...], "written_at": ISO, "source": "note-database-selection" | "obsidian-active-file" }
 */
module.exports = class FocusWriterPlugin extends Plugin {
	async onload() {
		this.timer = null;

		// ① note-database 选中变化：checkbox 勾选/取消
		document.addEventListener("change", (e) => this.onChange(e), true);
		// ② 表格行/卡片点击（非 checkbox 区域的选中）
		document.addEventListener("click", (e) => this.onClick(e), true);
		// ③ active file 变化（打开/切换笔记）
		this.registerEvent(this.app.workspace.on("file-open", () => this.scheduleUpdate()));
		// ④ DOM 兜底：表格 is-selected / aria-selected 等类变化
		this.mo = new MutationObserver(() => this.scheduleUpdate());
		this.mo.observe(document.body, {
			childList: true,
			subtree: true,
			attributes: true,
			attributeFilter: ["class", "aria-selected"],
		});

		this.scheduleUpdate();
	}

	onChange(e) {
		const t = e.target;
		if (t && t.matches && t.matches(".db-board-card-checkbox, .note-database-container input[type=checkbox]")) {
			this.scheduleUpdate();
		}
	}

	onClick(e) {
		if (e.target && e.target.closest && e.target.closest("[data-note-database-row-path]")) {
			this.scheduleUpdate();
		}
	}

	scheduleUpdate() {
		if (this.timer) clearTimeout(this.timer);
		this.timer = setTimeout(() => this.updateFocus(), 250);
	}

	updateFocus() {
		const paths = [];
		let source = null;

		// ① 看板：勾选的 checkbox → 祖先卡片 → 路径
		const checkedCards = document.querySelectorAll(
			'.db-board-card[data-note-database-row-path] input.db-board-card-checkbox:checked'
		);
		for (const cb of checkedCards) {
			const card = cb.closest(".db-board-card");
			const p = card && card.getAttribute("data-note-database-row-path");
			if (p) paths.push(p);
		}
		// ② 表格/列表：aria-selected / is-selected 行
		const selRows = document.querySelectorAll(
			'.note-database-container [aria-selected="true"], .note-database-container .is-selected'
		);
		for (const row of selRows) {
			const p =
				row.getAttribute("data-note-database-row-path") ||
				(row.querySelector("[data-note-database-row-path]") || {}).getAttribute &&
				row.querySelector("[data-note-database-row-path]").getAttribute("data-note-database-row-path");
			if (p && !paths.includes(p)) paths.push(p);
		}

		if (paths.length > 0) {
			source = "note-database-selection";
		} else {
			// ③ 回退：active file（排除数据库视图/画布/base 等非认知对象）
			const f = this.app.workspace.getActiveFile();
			if (f && f.extension === "md") {
				const cache = this.app.metadataCache.getFileCache(f);
				if (!(cache && cache.frontmatter && cache.frontmatter.db_view)) {
					paths.push(f.path);
					source = "obsidian-active-file";
				}
			}
		}

		if (source === null) {
			this.writeFocus(null); // 无焦点 → 删除文件
			return;
		}

		this.writeFocus({
			paths: Array.from(new Set(paths)),
			written_at: new Date().toISOString(),
			source,
		});
	}

	writeFocus(obj) {
		try {
			const base = this.app.vault.adapter.getBasePath();
			const dir = path.join(base, ".goodidea", "runtime");
			const file = path.join(dir, "focus.json");
			if (obj === null) {
				if (fs.existsSync(file)) fs.unlinkSync(file);
				return;
			}
			fs.mkdirSync(dir, { recursive: true });
			fs.writeFileSync(file, JSON.stringify(obj, null, 2));
		} catch (err) {
			console.error("FocusWriter:", err);
		}
	}

	onunload() {
		if (this.timer) clearTimeout(this.timer);
		if (this.mo) this.mo.disconnect();
	}
};
