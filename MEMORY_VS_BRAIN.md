# Hermes `~/.hermes/memories/` vs Mavis Brain — 單一真相來源決策

> 2026-06-07 決策

## TL;DR

| Store | 範圍 | 用途 | 誰寫 |
|---|---|---|---|
| **`~/.hermes/memories/`** | **單一裝置** | per-device 工作狀態、工具 quirk、本地慣例 | Hermes CLI 自己（`memory` toolset） |
| **Mavis Brain (NAS)** | **跨裝置** | 使用者偏好、workflow、fact、跨裝置 context | L3 M3 蒸餾 + 自動 sync hook |

**單一真相來源 = Brain**。`~/.hermes/memories/` 只是「這個 Mac 的 cache」。

## 為什麼分兩個

### `~/.hermes/memories/MEMORY.md` 問題

- ❌ **per-device**：iPhone 寫一份、Mac 寫一份、Windows 又寫一份
- ❌ **無 schema**：自由文字，LLM 自己決定寫什麼
- ❌ **無 dedup**：今天寫「Jason 偏好簡潔」、明天又寫「Jason 喜歡精簡」——兩筆衝突
- ❌ **無結構化**：無法 query「給我所有 preference」
- ❌ **無 sync**：換裝置要重新累積

### Mavis Brain 解決

- ✅ **跨裝置**：Tailscale 通的 4 個 device 共享
- ✅ **有 schema**：7 種 category + importance 0-10
- ✅ **dedup**（client-side + server-side add-only）：重複的不會被覆蓋
- ✅ **結構化查詢**：recall / brain-stats / decay / summarize
- ✅ **smart 排名**：client-side forgetting curve + TTL + pinned

## 各寫什麼

### 寫進 `~/.hermes/memories/` 的：
- 這個 Mac 跑的「奇怪 shell alias」
- 「這台 Mac 的 IP 是 192.168.x.x」
- 「Hermes Desktop 路徑在 /Applications/Hermes.app」
- 「MiniMax image MCP token 從這個路徑抓」

→ **設備特定**的、不會跨機有意義的

### 寫進 Brain 的：
- 「Jason 偏好繁中溝通」
- 「Jason 偏好簡潔回覆」
- 「Jason 每天 09:00 跑 cron」
- 「Jason 喜歡日式拉麵」
- 「Cursor 1.5 處理大檔會閃退」

→ **跨裝置有意義**、**使用者特質**、**workflow SOP**

## 自動分流

`mavis-brain-auto-extract` hook 在 `agent:end` 自動：
1. 拿 session 對話
2. 跑 `extract_facts.py` (M3 蒸餾)
3. **過濾掉純設備特定的 fact**（含 shell path / IP / local file 等 keyword 的 skip）
4. 寫進 Brain

`~/.hermes/memories/` 由 Hermes 自己的 `memory` toolset 自動寫（**不需要**我介入）。

## 衝突時的優先順序

| 情境 | 優先 |
|---|---|
| Brain 寫了「Jason 偏好 A」, `~/.hermes/memories/` 寫了「Jason 偏好 A」 | **Brain** 為主（用腦自動 dedup 同 category + 50% overlap） |
| `~/.hermes/memories/` 寫了「Mac 的 /tmp 在 /tmp」 | 保留（設備特定） |
| 兩邊都寫了「Jason 喜歡 X」但措辭不同 | **Brain** 為主（client-side smart search 用 score 排） |

## 怎麼用

### 你要查「我之前講過 X 嗎」
```bash
sync.sh recall "X" 5
# 跨裝置, 經 smart rank
```

### 你要查「這個 Mac 為什麼怪怪的」
```bash
# ~/.hermes/memories/MEMORY.md 開來看
cat ~/.hermes/memories/MEMORY.md
```

### 你要把對話永久化
```
# 不用手動 -- session-end hook 自動
# 但手動也行:
sync.sh extract "..."
```

## 結論

**不要再手動同步兩個 store**。讓它們**自動分流**：
- LLM 寫 `~/.hermes/memories/`（per-device）
- Hook 寫 Brain（cross-device, 帶 smart 處理）

要查的時候先 Brain，**沒**才查 `~/.hermes/memories/`（設備狀態）。
