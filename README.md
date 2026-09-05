# MRSS to Telegram Release Bot (GitHub Actions Hosted)

An automated RSS/MRSS feed monitor that broadcasts new releases to Telegram channels using **Photo Collages / Sliding Carousels** and modern **Rich Text Formatting**.

Hosted **100% free with zero servers** using scheduled **GitHub Actions workflows**.

---

## 🌟 Modern Rich Text & Media Features

- **Photo Collages & Sliding Carousels (`sendMediaGroup`)**:
  - Automatically pairs the **Front Cover [High Definition]** and **Back Cover [High Definition]** into a 2-photo album/grid.
  - In Telegram, users can view them side-by-side as a collage or swipe/slide between the covers in high-res!
- **Collapsible / Expandable Sections (`<blockquote expandable>`)**:
  - The scene list is rendered in Telegram's modern expandable blockquote so long scenes don't clutter the chat until tapped.
- **Monospace & Arrow Formatting**:
  - Clean `➤`, `▪️`, `➥` arrows for metadata, dates, cast, prices, and links.
- **Automated Handshake**:
  - Automatically bypasses age-verification gates and sets session cookies without getting blocked.
- **Serverless State Persistence**:
  - Records posted item IDs in [`data/history.json`](file:///home/ranit/dev/AdvdErss/data/history.json) and commits updates back to GitHub using `github-actions[bot]`.
- **Anti-Flood & Rate Limiting**:
  - Strict 1024-character caption limits dynamically enforced with automatic fallbacks (`sendMediaGroup` -> `sendPhoto` -> `sendMessage`).

---

## 🚀 Quick Setup Guide

### 1. Create a Telegram Bot
1. Open Telegram and search for [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts to choose a bot name and username.
3. Copy the **HTTP API Token** (e.g. `7123456789:AAH...`).

### 2. Prepare Your Telegram Channel or Group
1. Create a Telegram Channel or Group.
2. Add your newly created bot to the channel/group as an **Administrator** with permission to **Post Messages**.
3. Determine your **Chat ID**:
   - For public channels: Use `@YourChannelName`
   - For private channels/groups: Forward a message to [@userinfobot](https://t.me/userinfobot) or use `https://api.telegram.org/bot<TOKEN>/getUpdates` to get the numeric ID (e.g. `-1001234567890`).

---

### 3. Push this Project to GitHub
1. Create a new repository on [GitHub](https://github.com/new).
2. Push your local project code:
   ```bash
   git remote add origin https://github.com/<YOUR-USERNAME>/<YOUR-REPO-NAME>.git
   git push -u origin main
   ```

---

### 4. Configure GitHub Repository Secrets
1. In your GitHub repository, go to **Settings** > **Secrets and variables** > **Actions**.
2. Click **New repository secret** and add:
   - `TELEGRAM_BOT_TOKEN`: The API token obtained from @BotFather.
   - `TELEGRAM_CHAT_ID`: Your channel username (e.g. `@my_releases`) or numeric ID (e.g. `-1001234567890`).

---

### 5. Enable GitHub Actions Write Permissions *(Crucial)*
GitHub Actions needs permission to commit updated history back to the repository:
1. In your GitHub repository, go to **Settings** > **Actions** > **General**.
2. Scroll down to **Workflow permissions**.
3. Select **Read and write permissions**.
4. Check **Allow GitHub Actions to create and approve pull requests**.
5. Click **Save**.

---

### 6. Test Your Setup
1. Go to the **Actions** tab in your GitHub repository.
2. Select **RSS to Telegram Bot** from the left sidebar.
3. Click **Run workflow** -> **Run workflow**.

---

## ⚙️ Environment Variables Reference

| Variable | Description | Default |
| :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | Bot API token from `@BotFather` | *(Required)* |
| `TELEGRAM_CHAT_ID` | Telegram chat or channel ID | *(Required)* |
| `FEED_URL` | Media RSS URL | Default Adult DVD Empire MRSS |
| `USE_MEDIA_COLLAGE` | Send front & back covers as a 2-photo collage album | `true` |
| `USE_EXPANDABLE_BLOCKQUOTES` | Use collapsible `<blockquote expandable>` for scene lists | `true` |
| `MAX_POSTS_PER_RUN` | Maximum new items dispatched per run | `10` |
| `INITIAL_POST_LIMIT` | Items dispatched on the first run | `5` |
| `MAX_HISTORY_SIZE` | Maximum tracked item IDs in JSON history | `1000` |
| `HISTORY_FILE` | Path to the persistent history JSON file | `data/history.json` |

---

## 💻 Local Testing

```bash
# Dry run to preview the photo collage URLs and expandable caption format
python bot.py --dry-run
```
