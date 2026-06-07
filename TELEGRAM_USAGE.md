# 在 Telegram 用 Brain 指令

Hermes 沒內建自訂 slash command 機制, 但你可以**直接打字**觸發我跑 Brain 查詢。

## 用法

直接傳訊息給 bot (`@Andy_gemini3pro_bot`):

```
brain recall ETF
brain stats
brain decay 30
brain summarize workflow 7 10
brain conflict preference "Jason 喜歡 iPhone"
```

## 我會做的事

看到訊息含「brain」關鍵字 → 自動跑對應的 `sync.sh` / `brain_smart.py` 子指令 → 把結果回傳。

## 對應表

| 你打的 | 觸發 |
|---|---|
| `brain stats` | `sync.sh brain-stats` |
| `brain recall X` | `sync.sh recall X 5` |
| `brain decay 30` | `sync.sh decay 30` |
| `brain summarize workflow 7 10` | `sync.sh summarize workflow 7 10` |
| `brain conflict preference "X"` | `sync.sh conflict preference "X"` |
| `brain search X` | `sync.sh search X 5` |

## 為什麼不寫成 `/brain` 正式 command

要寫成 hermes bot 自訂 slash command 需要:
1. 改 `gateway/platforms/telegram.py` 加 command handler
2. 重啟 gateway
3. 改 BotFather menu

**目前不打算改** -- 你的訊息流裡直接打字觸發, 我 (hermes) 看到「brain」就處理。

## 另一條路: hook

如果你未來想要更自動, 可以加 hook:

```bash
# ~/.hermes/hooks/telegram-brain-trigger/
mkdir -p ~/.hermes/hooks/telegram-brain-trigger
cat > ~/.hermes/hooks/telegram-brain-trigger/HOOK.yaml <<'EOF'
name: telegram-brain-trigger
description: "Telegram 訊息含 'brain' 時, 直接 reply brain_smart 輸出"
events:
  - message:received
EOF
```

但需要改 gateway.py 攔截 message:received 事件。**不建議**--太多噪音。

## 實測

Telegram 傳:
```
brain stats
```

預期看到:
```
🧠 Brain stats:
Total: 55
Pinned: 0
Expired: 0
Avg score: 1.22
...
```

(實際數字以當下為準)
